# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Generic CRUD + method-call REST endpoints over arbitrary Odoo models.

Functional requirements were derived from analysing ``muk_rest``'s
behaviour (used **only** as a functional reference — its license is
MuK Proprietary v1.0), and this is a clean-room implementation: no code,
naming, or file structure is copied from it. The ``call`` endpoint's
readonly-resolution and argument-validation mechanism instead follows
Odoo 19's own built-in ``addons/rpc/controllers/json2.py`` (a core
module, AGPL-licensed, explicitly named as the pattern to follow by this
backlog item's Keputusan Desain) — independently written here, not
copied, using this module's own route/envelope/serializer conventions.

BINDING (do not remove this comment when editing this file): every
endpoint below is subject to nothing more than the caller's own real
ACL/record rules. ``sudo()`` is forbidden anywhere in this module — see
``ssi_rest_api/models/ssi_rest_access_profile.py`` for the full
subtractive-only rationale this inherits from backlog issue #7.

Binding risk (Keputusan Desain): ``service_model.retrying`` (core) can
re-run any of these methods more than once, on a serialization failure or
on a readonly->read/write cursor retry. None of the endpoints below have
a non-DB side effect (no outbound HTTP, no email, no filestore write, no
sequence consumption) for exactly this reason; a future endpoint that
needs one must schedule it through ``cr.postcommit``, never inline here.

Route shape (Keputusan Desain, binding): the target model is a path
segment, arguments are query parameters for read endpoints and a JSON
body for write endpoints. Access-profile ``model_pattern`` matching
(backlog #7) cannot see this dynamic per-request model — enforcement
only has the *static* ``rest_model`` a route declares at import time,
and these routes serve every model through one path pattern — so an
administrator restricting these endpoints per-model must do it with
``path_pattern`` (e.g. ``"/api/v1/orm/res.partner/*"``), not
``model_pattern``. Teaching the dispatcher to read a dynamic model out of
the route's own path arguments is a ``lib/`` change, out of this
module-only backlog item's scope.
"""

import inspect

from odoo import http, models
from odoo.http import request
from odoo.service.model import get_public_method

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from . import _helpers


class SsiRestOrmController(http.Controller):
    @rest_route(
        ["/orm/<string:model>/search"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def orm_search(self, model, domain=None, limit=None, offset=None, order=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        domain = _helpers.parse_json_param(domain, [])
        limit, offset = _helpers.paginate(request.env, limit, offset)
        records = target.search(domain, limit=limit, offset=offset, order=order)
        return {"ids": records.ids, "length": target.search_count(domain)}

    @rest_route(
        ["/orm/<string:model>/read"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def orm_read(self, model, ids=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        records = target.browse(_helpers.parse_ids(ids))
        serializer = request.env["ssi_rest_serializer"]
        specification = serializer._specification_from_query(kwargs)
        return serializer._serialize(records, specification)

    @rest_route(
        ["/orm/<string:model>/search_read"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def orm_search_read(
        self, model, domain=None, limit=None, offset=None, order=None, **kwargs
    ):
        target = _helpers.resolve_model(request.env, model)
        domain = _helpers.parse_json_param(domain, [])
        limit, offset = _helpers.paginate(request.env, limit, offset)
        records = target.search(domain, limit=limit, offset=offset, order=order)
        serializer = request.env["ssi_rest_serializer"]
        specification = serializer._specification_from_query(kwargs)
        return {
            "records": serializer._serialize(records, specification),
            "length": target.search_count(domain),
        }

    @rest_route(
        ["/orm/<string:model>/read_group"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def orm_read_group(
        self,
        model,
        domain=None,
        groupby=None,
        aggregates=None,
        limit=None,
        offset=None,
        order=None,
        **kwargs,
    ):
        target = _helpers.resolve_model(request.env, model)
        domain = _helpers.parse_json_param(domain, [])
        groupby = _helpers.parse_json_param(groupby, [])
        aggregates = _helpers.parse_json_param(aggregates, [])
        limit, offset = _helpers.paginate(request.env, limit, offset)
        rows = target._read_group(
            domain, groupby, aggregates, offset=offset, limit=limit, order=order
        )
        return {"groups": _helpers.format_read_group_rows(groupby, aggregates, rows)}

    @rest_route(
        ["/orm/<string:model>/create"],
        auth="ssi_rest",
        methods=["POST"],
        operation="create",
        readonly=False,
    )
    def orm_create(self, model, vals=None, vals_list=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        if vals_list is None:
            if vals is None:
                raise RestAuthError(
                    "validation_error", "vals or vals_list is required.", status=422
                )
            vals_list = [vals]
        records = target.create(vals_list)
        serializer = request.env["ssi_rest_serializer"]
        specification = serializer._specification_from_query(kwargs)
        body = serializer._serialize(records, specification)
        return request.make_json_response(body, status=201)

    @rest_route(
        ["/orm/<string:model>/write"],
        auth="ssi_rest",
        methods=["PUT", "PATCH"],
        operation="write",
        readonly=False,
    )
    def orm_write(self, model, ids=None, vals=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        if vals is None:
            raise RestAuthError("validation_error", "vals is required.", status=422)
        records = target.browse(_helpers.parse_ids(ids))
        records.write(vals)
        serializer = request.env["ssi_rest_serializer"]
        specification = serializer._specification_from_query(kwargs)
        return serializer._serialize(records, specification)

    @rest_route(
        ["/orm/<string:model>/unlink"],
        auth="ssi_rest",
        methods=["DELETE"],
        operation="unlink",
        readonly=False,
    )
    def orm_unlink(self, model, ids=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        target.browse(_helpers.parse_ids(ids)).unlink()
        return request.make_json_response(None, status=204)

    @rest_route(
        ["/orm/<string:model>/call/<string:method>"],
        auth="ssi_rest",
        methods=["POST"],
        operation="call",
        readonly=_helpers.orm_call_readonly,
    )
    def orm_call(self, model, method, ids=None, **kwargs):
        target = _helpers.resolve_model(request.env, model)
        try:
            func = get_public_method(target, method)
        except AttributeError as exc:
            raise RestAuthError("missing_record", str(exc), status=404) from exc
        # `AccessError` (private method, unsafe attribute, ...) propagates
        # unchanged -> classified 403 by `lib/errors.py:classify_exception`.

        records = target.browse(_helpers.parse_ids(ids))
        signature = inspect.signature(func)
        try:
            signature.bind(records, **kwargs)
        except TypeError as exc:
            raise RestAuthError("validation_error", str(exc), status=422) from exc

        result = func(records, **kwargs)
        if isinstance(result, models.BaseModel):
            result = result.ids
        return {"result": result}
