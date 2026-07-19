# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Read-only introspection endpoints: which models/fields the caller can
access, record metadata, server/company info, and the caller's own
access rights and groups.

Functional requirements were derived from analysing ``muk_rest``'s
behaviour (used **only** as a functional reference — its license is MuK
Proprietary v1.0), and this is a clean-room implementation: no code,
naming, or file structure is copied from it. The ``/session`` endpoint
present in that reference is deliberately dropped — meaningless for a
stateless API (backlog issue #12's binding Keputusan Desain). Odoo 19's
own ``addons/api_doc`` already provides a full interactive model browser
in the backend UI; this module is a REST surface over the same kind of
information, not a duplicate of that UI.

BINDING (do not remove this comment when editing this file): every
endpoint is subject to nothing more than the caller's own real ACL —
``sudo()`` is forbidden anywhere in this module (inherited from backlog
issue #7's subtractive-only rationale, see
``ssi_rest_api/models/ssi_rest_access_profile.py``). Model/field listings
are filtered through ``ir.model.access.check()``, a public, ACL-safe
introspection primitive that queries the access-rights tables directly
by raw SQL (core, ``base/models/ir_model.py``) rather than through the
ORM's own ACL-gated read path — this is why it can safely answer "what
can this user access" even for models (like ``ir.model`` and
``ir.module.module`` themselves) the caller has no read access to.
"""

import odoo.release
from odoo import http
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from . import _helpers


class SsiRestIntrospectionController(http.Controller):
    @rest_route(
        ["/introspection/models"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_models(self, **kwargs):
        access = request.env["ir.model.access"]
        result = []
        for model_name in sorted(request.env.registry):
            if model_name.startswith("mixin."):
                continue
            if not access.check(model_name, "read", raise_exception=False):
                continue
            model_cls = request.env.registry[model_name]
            result.append({"model": model_name, "name": model_cls._description})
        return result

    @rest_route(
        ["/introspection/models/<string:model>"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_model_detail(self, model, **kwargs):
        target = _helpers.resolve_readable_model(request.env, model)
        return {"model": model, "name": target._description}

    @rest_route(
        ["/introspection/models/<string:model>/fields"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_model_fields(self, model, **kwargs):
        target = _helpers.resolve_readable_model(request.env, model)
        return target.fields_get()

    @rest_route(
        ["/introspection/models/<string:model>/<int:res_id>/metadata"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_record_metadata(self, model, res_id, **kwargs):
        target = _helpers.resolve_readable_model(request.env, model)
        record = target.browse(res_id)
        serializer = request.env["ssi_rest_serializer"]
        specification = {
            "id": {},
            "create_uid": {},
            "create_date": {},
            "write_uid": {},
            "write_date": {},
        }
        body = serializer._serialize(record, specification)[0]
        body["xmlid"] = record.get_external_id().get(record.id) or False
        return body

    @rest_route(
        ["/introspection/server"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_server(self, **kwargs):
        modules = request.env["ir.module.module"].search([("state", "=", "installed")])
        return {
            "version": odoo.release.version,
            "modules": sorted(modules.mapped("name")),
        }

    @rest_route(
        ["/introspection/company"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_company(self, **kwargs):
        user = request.env.user
        serializer = request.env["ssi_rest_serializer"]
        specification = {"id": {}, "name": {}}
        return {
            "company": serializer._serialize(user.company_id, specification)[0],
            "companies": serializer._serialize(user.company_ids, specification),
        }

    @rest_route(
        ["/introspection/access_rights"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_access_rights(self, model=None, **kwargs):
        if not model:
            raise RestAuthError("validation_error", "model is required.", status=422)
        access = request.env["ir.model.access"]
        return {
            mode: access.check(model, mode, raise_exception=False)
            for mode in ("read", "write", "create", "unlink")
        }

    @rest_route(
        ["/introspection/access_fields"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_access_fields(self, model=None, fields=None, **kwargs):
        target = _helpers.resolve_readable_model(request.env, model)
        field_names = [name.strip() for name in fields.split(",")] if fields else None
        readable = target.fields_get(field_names)
        can_write = request.env["ir.model.access"].check(
            model, "write", raise_exception=False
        )
        return {
            field_name: {
                "readable": True,
                "writable": can_write and not description.get("readonly", False),
            }
            for field_name, description in readable.items()
        }

    @rest_route(
        ["/introspection/groups"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_groups(self, **kwargs):
        serializer = request.env["ssi_rest_serializer"]
        return serializer._serialize(
            request.env.user.all_group_ids, {"id": {}, "name": {}}
        )

    @rest_route(
        ["/introspection/has_group"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def introspection_has_group(self, group_xmlid=None, **kwargs):
        if not group_xmlid:
            raise RestAuthError(
                "validation_error", "group_xmlid is required.", status=422
            )
        group = request.env.ref(group_xmlid, raise_if_not_found=False)
        if group is None or group._name != "res.groups":
            raise RestAuthError(
                "missing_record",
                f"No res.groups record for xmlid {group_xmlid!r}.",
                status=404,
            )
        return {"result": request.env.user.has_group(group_xmlid)}
