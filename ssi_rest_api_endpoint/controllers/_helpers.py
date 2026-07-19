# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Small, dependency-free helpers shared by ``controllers/main.py``.

Deliberately **not** shared with ``ssi_rest_api_orm/controllers/_helpers.py``:
this module's manifest depends only on ``ssi_rest_api`` and
``ssi_master_data_mixin`` (backlog issue #17's binding Keputusan Desain),
not ``ssi_rest_api_orm`` — a shared import would silently add that
dependency back.
"""

import json

from odoo.service.model import get_public_method

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError


def parse_ids(value):
    """Accept ``ids`` as a single int, a comma-separated string
    (``"1,2,3"``), a JSON-encoded list string (from a query string), or
    an already-decoded list (from a JSON body) — always returns a plain
    ``list[int]``. Same contract as
    ``ssi_rest_api_orm.controllers._helpers.parse_ids``, duplicated here
    rather than imported (see module docstring)."""
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except ValueError as exc:
                raise RestAuthError(
                    "validation_error", f"Invalid JSON: {exc}", status=422
                ) from exc
            return [int(item) for item in decoded]
        return [int(item) for item in stripped.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    raise RestAuthError(
        "validation_error",
        "ids must be an integer, a comma-separated string, or a list.",
        status=422,
    )


def run_model_method(env, endpoint, ids, kwargs):
    """Run ``endpoint``'s ``model_method`` handler and return its raw
    result (the caller normalizes a recordset result to ids).

    ``target`` is a bare (empty) recordset on the resolved model, the
    same shape ``ssi_rest_api_orm``'s ``orm_call`` passes to
    ``get_public_method`` before browsing ``ids`` onto it. Whitelisting
    happens here, not at endpoint create/write time: ``model_id`` is a
    valid ``ir.model`` by construction (a real ``Many2one``), but
    ``method_name`` is free text and is only ever resolved against the
    live method whitelist at call time.

    ``endpoint._get_target_model_name()`` (``models/ssi_rest_endpoint.py``)
    resolves ``model_id`` to its technical name via raw SQL rather than
    ``model_id.model``: ``ir.model`` is itself ``base.group_system``-only
    (same class of gate as ``ir.actions.server``, see
    ``run_server_action`` below), so the ORM path would raise
    ``AccessError`` for any caller without that group.
    """
    model_name = endpoint._get_target_model_name()
    if not model_name:
        raise RestAuthError(
            "missing_record", "Endpoint's target model no longer exists.", status=404
        )
    target = env[model_name]
    try:
        func = get_public_method(target, endpoint.method_name)
    except AttributeError as exc:
        raise RestAuthError("missing_record", str(exc), status=404) from exc
    records = target.browse(parse_ids(ids))
    return func(records, **kwargs)


def run_server_action(env, endpoint, ids):
    """Run ``endpoint``'s ``server_action`` handler and return its raw
    result.

    ``ids`` (if any) is threaded into the action's context as
    ``active_id``/``active_ids``/``active_model`` — the same context
    shape the Odoo UI itself sets before running a server action bound to
    a record — only when the action actually targets a model; an
    unbound/global server action runs with no such context.

    ``action.model_id``'s technical model name is read via one raw SQL
    join, not the ORM: both ``ir.actions.server`` and ``ir.model`` are
    themselves ``base.group_system``-only, and ``.run()`` below only
    works around that by ``sudo()``-ing itself internally (core,
    ``ir_actions.py``'s ``IrActionsServer.run()``) — this module's own
    code stays outside that sudo'd path entirely instead of relying on
    it.
    """
    action = endpoint.server_action_id
    parsed_ids = parse_ids(ids)
    context = {}
    if parsed_ids:
        env.cr.execute(
            "SELECT m.model FROM ir_act_server a "
            "JOIN ir_model m ON m.id = a.model_id "
            "WHERE a.id = %s",
            (action.id,),
        )
        row = env.cr.fetchone()
        if row:
            context.update(
                active_model=row[0],
                active_ids=parsed_ids,
                active_id=parsed_ids[0],
            )
    return action.with_context(**context).run()
