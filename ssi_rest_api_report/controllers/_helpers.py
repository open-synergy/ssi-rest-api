# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Small, dependency-free helper shared by ``controllers/main.py``."""

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api_orm.controllers._helpers import (  # noqa: F401
    parse_ids,
)


def resolve_report(env, report_ref):
    """Return the ``ir.actions.report`` matching ``report_ref`` (its
    technical ``report_name``, an xmlid, or an id), or raise a
    client-facing 404.

    Delegates to core's own ``ir.actions.report._get_report()`` (the same
    resolver every ``_render_qweb_*`` method uses internally) rather than
    reimplementing report lookup — it already accepts every identity
    shape this endpoint needs to support. That method resolves through
    its own ``sudo()`` internally (reading a report *definition* is
    config metadata, not user data); this module still never ``sudo()``
    on the *target records* being rendered — see ``main.py``'s
    ``report_render`` for the explicit ``check_access("read")`` that
    actually enforces the caller's ACL, backlog issue #13's ``ir.binary``
    endpoint precedent.
    """
    if not report_ref:
        raise RestAuthError(
            "validation_error", "report_name is required.", status=422
        )
    try:
        return env["ir.actions.report"]._get_report(report_ref)
    except ValueError as exc:
        raise RestAuthError(
            "missing_record", f"Report {report_ref!r} does not exist.", status=404
        ) from exc
