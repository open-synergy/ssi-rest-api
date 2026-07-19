# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Small, dependency-free helpers shared by ``controllers/main.py``.

Split out purely for readability — none of this is a public contract of
its own (unlike ``ssi_rest_serializer``, which is).
"""

import json

from odoo import models
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError

#: `ir.config_parameter` keys read on every list/group-by endpoint call.
_ICP_DEFAULT_PAGE_SIZE = "ssi_rest_api.default_page_size"
_ICP_MAX_PAGE_SIZE = "ssi_rest_api.max_page_size"


def resolve_model(env, model_name):
    """Return ``env[model_name]``, or raise a client-facing 404 if the
    name does not name a real model — never a raw ``KeyError``."""
    try:
        return env[model_name]
    except KeyError as exc:
        raise RestAuthError(
            "missing_record",
            f"Model {model_name!r} does not exist.",
            status=404,
        ) from exc


def parse_json_param(value, default):
    """Parse ``value`` as JSON if it is a string (as it always is when it
    arrived through a GET query string); pass it through unchanged
    otherwise (already-decoded JSON body value on a POST/PUT/PATCH/DELETE
    request, see ``SsiRestDispatcher.dispatch``)."""
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError as exc:
        raise RestAuthError(
            "validation_error", f"Invalid JSON: {exc}", status=422
        ) from exc


def parse_ids(value):
    """Accept ``ids`` as a single int, a comma-separated string
    (``"1,2,3"``), a JSON-encoded list string (from a query string), or
    an already-decoded list (from a JSON body) — always returns a plain
    ``list[int]``."""
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            return [int(item) for item in parse_json_param(stripped, [])]
        return [int(item) for item in stripped.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    raise RestAuthError(
        "validation_error",
        "ids must be an integer, a comma-separated string, or a list.",
        status=422,
    )


def paginate(env, limit, offset):
    """Resolve ``(limit, offset)`` against the core pagination ICP
    keys, clamping (never rejecting) a request that asks for more than
    ``max_page_size``.

    Reads ``ir.config_parameter`` through its private, ACL-free
    ``_get_param`` (the same raw-SQL bypass ``ir.config_parameter``
    itself uses internally, see ``base/models/ir_config_parameter.py``)
    rather than the public ``get_param()`` (restricted to
    ``base.group_system``) — deliberately **not** ``sudo()``, which is
    forbidden anywhere in this module's endpoint code (backlog issue #11's
    binding Keputusan Desain, inherited from issue #7's subtractive-only
    access-profile invariant).
    """
    icp = env["ir.config_parameter"]
    default_page_size = int(icp._get_param(_ICP_DEFAULT_PAGE_SIZE) or 80)
    max_page_size = int(icp._get_param(_ICP_MAX_PAGE_SIZE) or 1000)
    resolved_limit = (
        default_page_size if limit is None else min(int(limit), max_page_size)
    )
    resolved_offset = int(offset or 0)
    return resolved_limit, resolved_offset


def format_read_group_rows(groupby, aggregates, rows):
    """Turn ``_read_group()``'s list-of-tuples into a list of dict keyed
    by each ``groupby``/``aggregates`` spec, with any related-field
    groupby value (a recordset) reduced to ``{"id", "display_name"}``
    the same way the serializer's default ``many2one`` shape works."""
    specs = list(groupby) + list(aggregates)
    formatted = []
    for row in rows:
        entry = {}
        for spec, value in zip(specs, row, strict=False):
            if isinstance(value, models.BaseModel):
                entry[spec] = (
                    {"id": value.id, "display_name": value.display_name}
                    if value
                    else False
                )
            else:
                entry[spec] = value
        formatted.append(entry)
    return formatted


def orm_call_readonly(controller, rule, args):
    """``readonly=`` callable for the ``call`` route (backlog issue #11's
    binding Keputusan Desain, pattern from Odoo 19's own
    ``addons/rpc/controllers/json2.py:_web_json_2_rpc_readonly`` — same
    MRO/``_readonly``-attribute mechanism, independently written).

    Runs *before* authentication (core dispatch order), so this must
    never touch ``env.user``, ACL, or ``ir.config_parameter`` — only the
    registry's model/method introspection, which is auth-independent.
    """
    try:
        model = request.registry[args["model"]]
        method_name = args["method"]
    except KeyError:
        # Unknown model/method: no need for a read/write cursor just to
        # let the endpoint itself answer with a 404 afterwards.
        return True
    for cls in model.mro():
        method = getattr(cls, method_name, None)
        if method is not None and hasattr(method, "_readonly"):
            return method._readonly
    return False
