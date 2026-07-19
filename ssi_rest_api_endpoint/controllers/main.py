# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Single wildcard REST endpoint serving every ``ssi_rest_endpoint`` record
(backlog issue #17).

Functional requirement (a data-configurable custom endpoint) was derived
from analysing ``muk_rest``'s behaviour — used **only** as a functional
reference, its license is MuK Proprietary v1.0 — and this is a clean-room
implementation: no code, naming, or file structure is copied from it.
``muk_rest``'s approach of storing Python code on a field and running it
through ``safe_eval`` is deliberately **not** adopted; see
``models/ssi_rest_endpoint.py``'s module docstring and this backlog
item's Keputusan Desain for the rationale. Handlers here are limited to
(a) an ``ir.actions.server`` — a sandbox Odoo core already gates — or
(b) a model method that passes
``odoo.service.model.get_public_method``, same whitelist
``ssi_rest_api_orm``'s ``call`` route already relies on.

BINDING (do not remove this comment when editing this file): every
endpoint call below is subject to nothing more than the caller's own real
ACL/record rules plus ``ssi_rest_endpoint._check_rest_access``.
``sudo()`` is forbidden anywhere in this module — see
``ssi_rest_api/models/ssi_rest_access_profile.py`` for the full
subtractive-only rationale this inherits from backlog issue #7.

Route shape (Keputusan Desain, binding): **one** wildcard route
(``/x/<path:subpath>``) serves every ``ssi_rest_endpoint`` record —
registering one Odoo route per record is rejected: it would mean
routing-map invalidation on every write and O(n) memory against the
number of records. Lookup of the matching record happens inside the
handler below, by ``path`` + the incoming HTTP method.
"""

import logging

from odoo import http, models, sql_db
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from . import _helpers

_logger = logging.getLogger(__name__)

#: Same client-facing text as `SsiRestDispatcher._ACCESS_DENIED_MESSAGE`
#: (`ssi_rest_api/lib/dispatcher.py`) — deliberately generic, never
#: mentions which profile/rule/model matched.
_ACCESS_DENIED_MESSAGE = "You are not allowed to perform this action."


def _custom_endpoint_readonly(controller, rule, args):
    """``readonly=`` callable for the wildcard route (3-arg convention —
    ``(controller, rule, args)`` — distinct from the unrelated single-arg
    ``max_content_length=`` callable convention used elsewhere in this
    module family; see ``ssi_rest_api_binary/controllers/main.py``).

    Runs *before* authentication and before the request's own cursor is
    opened (core dispatch order — same constraint documented on
    ``ssi_rest_api_orm.controllers._helpers.orm_call_readonly``), so
    ``request.env``/``env.user`` are not available yet. Unlike that
    sibling callable (pure Python attribute introspection, no DB access
    at all), whether *this* wildcard route may write depends on data —
    the matched ``ssi_rest_endpoint`` record's own ``is_readonly`` — so a
    short-lived, throwaway cursor is opened here purely to read that one
    column, the same raw-``cr.execute`` bypass technique
    ``ssi_rest_api_orm.controllers._helpers.paginate`` already uses for
    ``ir.config_parameter`` (deliberately **not** the ORM: no env/cursor
    exists yet to build one from). If the lookup fails for any reason
    (unknown path, endpoint not found, or even a raw DB error) this
    returns ``False`` — never ``True`` — matching this backlog item's
    hard rule: "an endpoint that may write is never run readonly=True;
    when in doubt, treat it as a write."
    """
    subpath = args.get("subpath")
    if not subpath or not request.db:
        return False
    http_method = request.httprequest.method
    try:
        with sql_db.db_connect(request.db).cursor() as cr:
            cr.execute(
                "SELECT is_readonly FROM ssi_rest_endpoint "
                "WHERE path = %s AND http_method = %s AND active IS TRUE",
                (subpath, http_method),
            )
            row = cr.fetchone()
    except Exception:
        _logger.exception(
            "ssi_rest_api_endpoint: readonly resolution failed for %s %s, "
            "defaulting to writable cursor",
            http_method,
            subpath,
        )
        return False
    return bool(row[0]) if row else False


class SsiRestEndpointController(http.Controller):
    @rest_route(
        ["/x/<path:subpath>"],
        auth="ssi_rest",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        # No single static model/operation: both vary per matched
        # ssi_rest_endpoint record, same limitation documented on
        # ssi_rest_api_orm's dynamic-model routes. An administrator
        # restricting these endpoints globally must use a profile rule's
        # path_pattern (e.g. "/api/v1/x/sales/*"); per-endpoint
        # restriction is this model's own profile_ids instead (see
        # ssi_rest_endpoint._check_rest_access).
        operation=None,
        model=None,
        readonly=_custom_endpoint_readonly,
    )
    def custom_endpoint_call(self, subpath, ids=None, **kwargs):
        http_method = request.httprequest.method
        # `search()` on a model with an `active` field excludes inactive
        # records by default (ORM's own `active_test` handling) — an
        # archived endpoint is therefore a plain 404 below, never a
        # separate state check (Keputusan Desain: no `state` field here).
        endpoint = request.env["ssi_rest_endpoint"].search(
            [("path", "=", subpath), ("http_method", "=", http_method)],
            limit=1,
        )
        if not endpoint:
            raise RestAuthError(
                "missing_record", "Endpoint not found.", status=404
            )
        if not endpoint._check_rest_access(request.env.user):
            # Deliberately generic, matching
            # `SsiRestDispatcher._ACCESS_DENIED_MESSAGE`: the matched
            # profile/rule is never disclosed to the client.
            raise RestAuthError("access_denied", _ACCESS_DENIED_MESSAGE, status=403)

        if endpoint.handler_type == "model_method":
            result = _helpers.run_model_method(request.env, endpoint, ids, kwargs)
        else:
            result = _helpers.run_server_action(endpoint, ids)

        if isinstance(result, models.BaseModel):
            result = result.ids
        return {"result": result}
