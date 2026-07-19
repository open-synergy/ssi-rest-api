# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Record -> JSON serializer shared by every ``ssi_rest_api*`` endpoint
module (``orm``, ``introspection``, ``report``, ...).

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by (see ``lib/dispatcher.py`` module docstring for the full
rationale). It adopts Odoo 19's own ``specification`` dict *shape*
(``{field: {"fields": {...}}}``, as used by ``web_read``/
``web_search_read``) as the wire format for field selection, but does
**not** delegate to ``BaseModel.web_read()``: that method's defaults
differ from this module's (e.g. ``many2one`` stays a bare id unless
``"fields"`` is requested) and, more importantly, it fetches
``many2one.display_name`` through ``co_records.sudo()`` — forbidden here,
see the no-``sudo()`` note below.

The wire contract (field shapes, default vs. opt-in behaviour) is public
API: changing it after client modules are installed is a breaking change,
so every default documented here is binding, not a starting point.
"""

import base64
import hashlib

from odoo import api, models
from odoo.exceptions import ValidationError

#: Sentinel key carrying global serialization options (``m2o``, ``binary``,
#: ``labels``) inside an otherwise per-field ``specification`` dict, so the
#: public method contract stays "one specification dict in, list of dict
#: out" (see class docstring) without a parallel options parameter.
_OPTIONS_KEY = "__options__"

_TRUE_STRINGS = ("1", "true", "True")


class SsiRestSerializer(models.AbstractModel):
    """Record -> JSON serializer, ``specification``-driven.

    No stored model, no ACL of its own: every method here reads through
    whatever ``recordset`` the caller already obtained (itself already
    subject to normal ACL/record rules), and additionally drops any field
    the current user cannot read due to its own ``groups=`` restriction.
    Never uses ``sudo()`` — a caller with no real read access to a field
    or a related record must never see it leak through this serializer.
    """

    _name = "ssi_rest_serializer"
    _description = "REST Serializer"

    @api.model
    def _specification_from_query(self, query):
        """Build a normalized ``specification`` dict from raw query
        options.

        :param dict query: parsed query options, any of:

            * ``specification`` — an already-built specification dict,
              used as-is if present (nested nested nested `"fields"` and
              all).
            * ``fields`` — comma-separated shorthand, dotted paths
              allowed (e.g. ``"name,line_ids.product_id.name"``),
              expanded into the equivalent nested specification.
            * ``m2o`` — ``"id"`` to serialize every ``many2one`` as a
              bare id instead of ``{"id", "display_name"}``.
            * ``binary`` — ``"inline"`` to serialize every ``binary``
              field as base64 instead of ``{"size", "checksum", "url"}``.
            * ``labels`` — truthy (``"1"``/``"true"``) to also emit the
              label of every ``selection`` field alongside its raw value.

        :return: a specification dict with the global options folded
            into it under an internal sentinel key, ready for
            :meth:`_serialize`.
        """
        query = query or {}
        explicit_specification = query.get("specification")
        if explicit_specification:
            specification = dict(explicit_specification)
        else:
            specification = {}
            fields_param = query.get("fields")
            if fields_param:
                for dotted_path in str(fields_param).split(","):
                    dotted_path = dotted_path.strip()
                    if dotted_path:
                        self._merge_dotted_path(specification, dotted_path.split("."))
        specification[_OPTIONS_KEY] = {
            "m2o": query.get("m2o"),
            "binary": query.get("binary"),
            "labels": str(query.get("labels")) in _TRUE_STRINGS,
        }
        return specification

    def _merge_dotted_path(self, specification, path_parts):
        """Merge a single dotted path (``["line_ids", "product_id",
        "name"]``) into ``specification`` in place, as nested
        ``"fields"`` entries."""
        head, *rest = path_parts
        entry = specification.setdefault(head, {})
        if rest:
            nested = entry.setdefault("fields", {})
            self._merge_dotted_path(nested, rest)

    @api.model
    def _serialize(self, records, specification):
        """Serialize ``records`` (any recordset) into a list of dict, one
        per record, following ``specification`` (as returned by
        :meth:`_specification_from_query`, or hand-built in the same
        shape).

        :raises ValidationError: if ``specification`` names a field that
            does not exist on ``records``' model (never a raw
            ``KeyError``).
        """
        specification = dict(specification or {})
        options = specification.pop(_OPTIONS_KEY, {}) or {}
        return self._serialize_records(records, specification, options)

    def _serialize_records(self, records, specification, options):
        self._validate_specification(records, specification)
        return [
            self._serialize_record(record, specification, options) for record in records
        ]

    def _validate_specification(self, model, specification):
        for field_name, field_spec in specification.items():
            field = model._fields.get(field_name)
            if field is None:
                raise ValidationError(
                    self.env._(
                        "Unknown field %(field)s on model %(model)s.",
                        field=field_name,
                        model=model._name,
                    )
                )
            nested_fields = (field_spec or {}).get("fields")
            if not nested_fields:
                continue
            if field.type not in ("many2one", "one2many", "many2many"):
                raise ValidationError(
                    self.env._(
                        "Field %(field)s on model %(model)s is not "
                        "relational, it cannot carry a nested "
                        "specification.",
                        field=field_name,
                        model=model._name,
                    )
                )
            self._validate_specification(model.env[field.comodel_name], nested_fields)

    def _serialize_record(self, record, specification, options):
        record.ensure_one()
        readable = record.fields_get(list(specification)) if specification else {}
        values = {}
        for field_name in specification:
            if field_name not in readable:
                # Not readable by the current user (field-level `groups=`
                # restriction) -> silently dropped, never raised.
                continue
            field = record._fields[field_name]
            field_spec = specification[field_name] or {}
            values[field_name] = self._serialize_value(
                record, field, record[field_name], field_spec, options
            )
        return values

    def _serialize_value(self, record, field, value, field_spec, options):
        if field.type == "many2one":
            return self._serialize_many2one(field, value, field_spec, options)
        if field.type in ("one2many", "many2many"):
            return self._serialize_x2many(field, value, field_spec, options)
        if field.type == "datetime":
            return self._serialize_datetime(value)
        if field.type == "date":
            return self._serialize_date(value)
        if field.type == "binary":
            return self._serialize_binary(value, options)
        if field.type == "selection":
            return self._serialize_selection(record, field, value, options)
        if field.type == "monetary":
            return self._serialize_monetary(record, field, value)
        if field.type == "float":
            return self._serialize_float(record, field, value)
        return value

    def _serialize_many2one(self, field, value, field_spec, options):
        if not value:
            return False
        if options.get("m2o") == "id":
            return value.id
        nested_fields = field_spec.get("fields")
        if nested_fields:
            return self._serialize_records(value, nested_fields, options)[0]
        return {"id": value.id, "display_name": value.display_name}

    def _serialize_x2many(self, field, value, field_spec, options):
        nested_fields = field_spec.get("fields")
        if not nested_fields:
            return value.ids
        return self._serialize_records(value, nested_fields, options)

    def _serialize_datetime(self, value):
        if not value:
            return False
        # Odoo stores/reads `datetime` fields as naive UTC already; no
        # timezone conversion needed, only the ISO-8601 "Z" suffix.
        return value.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    def _serialize_date(self, value):
        if not value:
            return False
        return value.strftime("%Y-%m-%d")

    def _serialize_binary(self, value, options):
        if options.get("binary") == "inline":
            return value or False
        if not value:
            return {"size": 0, "checksum": False, "url": False}
        decoded = base64.b64decode(value)
        return {
            "size": len(decoded),
            "checksum": hashlib.md5(decoded).hexdigest(),  # noqa: S324
            # Populated once a download-route contract exists (backlog
            # item #13, "endpoint unduh dan unggah biner via ir.binary").
            "url": False,
        }

    def _serialize_selection(self, record, field, value, options):
        if not options.get("labels"):
            return value
        selection = dict(field.get_description(record.env)["selection"])
        return {"value": value, "label": selection.get(value)}

    def _serialize_monetary(self, record, field, value):
        currency_field = field.get_currency_field(record)
        currency = record[currency_field] if currency_field else False
        if not currency:
            currency = record.env.company.currency_id
        return currency.round(value) if currency else value

    def _serialize_float(self, record, field, value):
        digits = field.get_digits(record.env)
        if not digits:
            return value
        return round(value, digits[1])
