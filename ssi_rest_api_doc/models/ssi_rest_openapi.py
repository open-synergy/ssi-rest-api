# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OpenAPI 3.1 document generator for every ``routing_type='ssi_rest'``
route registered in this repo.

BINDING (backlog issue #16's Keputusan Desain, do not remove this comment
when editing this file): the routing map built by Odoo core
(``env['ir.http'].routing_map()``, see ``odoo/addons/base/models/ir_http.py``)
is the *only* source of truth for what this document describes — there is
no hand-written route list anywhere in this module. Every
``werkzeug.routing.Rule`` yielded by that map carries the full ``@route()``
kwargs (merged, including the ``rest_version``/``rest_operation``/
``rest_model``/``type`` keys ``ssi_rest_api.lib.routing.rest_route``
injects) on ``rule.endpoint.routing`` — verified against Odoo 19 core
(``odoo/http.py:_generate_routing_rules``), not assumed. Routes whose
``type`` is not ``ssi_rest`` (``/web/*``, core JSON-RPC, ...) are skipped
outright, so they structurally can never appear in the generated document.

Each ``rest_route(...)`` call expands into one URL per supported API
version (``/api/v1/...``, a future ``/api/v2/...``, ...) while sharing one
``routing`` dict across all of them — so the *version* a given
``werkzeug.routing.Rule`` belongs to has to be read back out of its own
URL pattern (``rule.rule``), not out of ``routing['rest_version']`` (which
always lists every version the endpoint supports, regardless of which
expanded URL is being inspected).

Component schemas are intentionally derived by delegating to
``ssi_rest_api_introspection``'s own ``resolve_readable_model()`` +
``fields_get()`` call (the same primitive backing the
``/introspection/models/<model>/fields`` endpoint) rather than
reimplementing field introspection here a second time, so field
definitions never fork between the two modules.
"""

import re

from odoo import api, models
from odoo.exceptions import AccessError

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api_introspection.controllers._helpers import (
    resolve_readable_model,
)

#: Matches a werkzeug path converter segment, e.g. ``<string:model>`` or
#: the converter-less ``<model>`` — group 2 is always the parameter name.
_PATH_PARAM_RE = re.compile(r"<(?:(?P<converter>\w+):)?(?P<name>\w+)>")

#: werkzeug/``routing_map()`` always adds these to ``rule.methods`` on top
#: of whatever ``rest_route(..., methods=[...])`` declared (``HEAD`` is
#: implied by ``GET``, ``OPTIONS`` by ``routing_map()`` itself) — neither
#: is a real ``ssi_rest`` operation of its own.
_IGNORED_HTTP_METHODS = frozenset({"HEAD", "OPTIONS"})

_CONVERTER_OPENAPI_TYPES = {
    "int": "integer",
    "float": "number",
}

_FIELD_OPENAPI_TYPES = {
    "integer": "integer",
    "float": "number",
    "monetary": "number",
    "boolean": "boolean",
    "many2one": "integer",
    "one2many": "array",
    "many2many": "array",
}

_ERROR_SCHEMA = {
    "type": "object",
    "description": "The single error envelope shape every failed "
    "ssi_rest request is rendered as (see "
    "ssi_rest_api/lib/errors.py:build_error_body).",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "status": {"type": "integer"},
                "request_id": {"type": "string"},
                "details": {"type": ["object", "null"]},
            },
            "required": ["code", "message", "status", "request_id"],
        },
    },
    "required": ["error"],
}


def _field_openapi_type(description):
    return _FIELD_OPENAPI_TYPES.get(description.get("type"), "string")


class SsiRestOpenapi(models.AbstractModel):
    """Public contract (binding): :meth:`_build_document` is safe for
    another module to ``_inherit`` and extend — e.g. to splice extra
    ``paths``/``components`` entries in before returning — as long as the
    override still returns a plain, JSON-serialisable ``dict`` shaped like
    an OpenAPI 3.1 document.
    """

    _name = "ssi_rest_openapi"
    _description = "SSI REST API - OpenAPI Document Generator"

    @api.model
    def _build_document(self, version):
        """Return an OpenAPI 3.1 document (a plain ``dict``) describing
        every ``routing_type='ssi_rest'`` route registered for API
        ``version`` (e.g. ``1``)."""
        paths = {}
        model_names = set()
        for rule in self.env["ir.http"].routing_map().iter_rules():
            routing = rule.endpoint.routing
            if routing.get("type") != "ssi_rest":
                continue
            if not self._rule_matches_version(rule.rule, version):
                continue
            path, parameters = self._openapi_path(rule.rule)
            paths.setdefault(path, {}).update(
                self._build_operations(rule, routing, parameters)
            )
            model_name = routing.get("rest_model")
            if model_name:
                model_names.add(model_name)

        return {
            "openapi": "3.1.0",
            "info": {
                "title": "SSI REST API",
                "version": f"{version}.0.0",
            },
            "paths": dict(sorted(paths.items())),
            "components": {
                "securitySchemes": self._security_schemes(),
                "schemas": self._component_schemas(model_names),
            },
        }

    @api.model
    def _rule_matches_version(self, werkzeug_pattern, version):
        match = re.match(r"^/api/v(?P<version>\d+)/", werkzeug_pattern)
        return bool(match) and int(match.group("version")) == version

    @api.model
    def _openapi_path(self, werkzeug_pattern):
        """Turn a werkzeug path template (``/api/v1/orm/<string:model>/read``)
        into an OpenAPI path template (``/api/v1/orm/{model}/read``) plus
        the list of ``parameters`` objects describing each substitution."""
        parameters = []

        def _replace(match):
            parameters.append(
                {
                    "name": match.group("name"),
                    "in": "path",
                    "required": True,
                    "schema": {
                        "type": _CONVERTER_OPENAPI_TYPES.get(
                            match.group("converter"), "string"
                        )
                    },
                }
            )
            return "{" + match.group("name") + "}"

        return _PATH_PARAM_RE.sub(_replace, werkzeug_pattern), parameters

    @api.model
    def _build_operations(self, rule, routing, parameters):
        operation_name = routing.get("rest_operation")
        tag = self._tag_for_path(rule.rule)
        security = [] if routing.get("auth") == "public" else self._operation_security()
        methods = (rule.methods or {"GET"}) - _IGNORED_HTTP_METHODS
        operations = {}
        for http_method in sorted(methods):
            operations[http_method.lower()] = {
                "operationId": self._operation_id(rule, http_method, operation_name),
                "tags": [tag],
                "parameters": parameters,
                "security": security,
                "responses": {
                    "200": {"description": "Successful response."},
                    "default": {
                        "description": "Error response.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Error"}
                            }
                        },
                    },
                },
            }
        return operations

    @api.model
    def _operation_id(self, rule, http_method, operation_name):
        # `rule.endpoint.__name__` is the controller method name, carried
        # over from the bound method through `route()`'s
        # `functools.wraps` and `_generate_routing_rules`'s
        # `functools.update_wrapper` (verified against Odoo 19 core).
        endpoint_name = getattr(rule.endpoint, "__name__", "endpoint")
        parts = (operation_name, endpoint_name, http_method.lower())
        return "_".join(part for part in parts if part)

    @api.model
    def _tag_for_path(self, werkzeug_pattern):
        match = re.match(r"^/api/v\d+/(?P<segment>[^/]+)", werkzeug_pattern)
        return match.group("segment") if match else "default"

    @api.model
    def _operation_security(self):
        return [{"bearerAuth": []}, {"basicAuth": []}]

    @api.model
    def _security_schemes(self):
        # Mirrors the two providers `ssi_rest_auth_scheme` ships out of
        # the box (see `ssi_rest_api/models/ssi_rest_auth_{basic,bearer}.py`).
        return {
            "bearerAuth": {"type": "http", "scheme": "bearer"},
            "basicAuth": {"type": "http", "scheme": "basic"},
        }

    @api.model
    def _component_schemas(self, model_names):
        schemas = {"Error": _ERROR_SCHEMA}
        for model_name in sorted(model_names):
            try:
                target = resolve_readable_model(self.env, model_name)
            except (RestAuthError, AccessError):
                continue
            schemas[self._schema_name(model_name)] = self._model_schema(target)
        return schemas

    @api.model
    def _schema_name(self, model_name):
        return model_name.replace(".", "_")

    @api.model
    def _model_schema(self, target):
        properties = {
            field_name: {"type": _field_openapi_type(description)}
            for field_name, description in target.fields_get().items()
        }
        return {"type": "object", "properties": properties}
