# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""One row per ``ssi_rest`` HTTP request/response (backlog issue #15).

Every field is ``readonly=True``: this model is an audit trail, never
edited through the UI (see
``security/ir_model_access/ssi_rest_request_log.xml`` -- only
``base.group_system`` may even read it, and no group is granted
create/write/unlink from the UI at all). Rows are written from
``lib/dispatcher.py`` through a cursor entirely independent of the
request's own transaction -- never through this model's ``create()``
while bound to the request's own ``env`` -- see that module's docstring
for the full rationale.
"""

from datetime import timedelta

from odoo import api, fields, models


class SsiRestRequestLog(models.Model):
    """Audit trail of every ``ssi_rest`` HTTP request served by this
    database: who called what, with which credential, and what the
    server answered back. Purged automatically by
    :meth:`_gc_expired_request_log` below, never through a bespoke cron
    (binding, backlog issue #15's Keputusan Desain).
    """

    _name = "ssi_rest_request_log"
    _description = "REST Request Log"
    _order = "id desc"
    _rec_name = "request_id"

    request_id = fields.Char(
        readonly=True,
        index=True,
        help="Correlation id carried by the X-Request-Id response header "
        "for this request, letting a client-reported issue be matched "
        "back to this row.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        readonly=True,
        help="Authenticated user this request ran as (the public user "
        "for an unauthenticated auth='public' request).",
    )
    auth_scheme = fields.Char(
        readonly=True,
        help="Code of the ssi_rest_auth_scheme that authenticated this "
        "request (e.g. 'basic', 'bearer'); empty when authentication "
        "never completed (e.g. no credential at all).",
    )
    http_method = fields.Char(
        readonly=True,
        help="HTTP method of the request (GET, POST, ...).",
    )
    path = fields.Char(
        readonly=True,
        index=True,
        help="Raw request path, e.g. /api/v1/orm/res.partner/search.",
    )
    route_pattern = fields.Char(
        readonly=True,
        help="Werkzeug rule pattern that matched this request, e.g. "
        "/api/v1/orm/<string:model>/search. Empty when the request "
        "never reached routing (e.g. authentication failed first).",
    )
    status_code = fields.Integer(
        readonly=True,
        help="HTTP status code returned to the client.",
    )
    duration_ms = fields.Float(
        readonly=True,
        help="Wall-clock time, in milliseconds, between this request "
        "entering the dispatcher and its response being ready.",
    )
    remote_addr = fields.Char(
        readonly=True,
        help="Client IP address as seen by the WSGI server.",
    )
    user_agent = fields.Char(
        readonly=True,
        help="Raw User-Agent request header.",
    )
    model_name = fields.Char(
        readonly=True,
        help="Odoo model this request targeted, when the route "
        "operates on a single model.",
    )
    method_name = fields.Char(
        readonly=True,
        help="Operation or method name this request invoked (e.g. "
        "'read', 'create', or a called method's name).",
    )
    record_count = fields.Integer(
        readonly=True,
        help="Best-effort count of records the response body carried.",
    )
    error_code = fields.Char(
        readonly=True,
        help="Stable error envelope code (see ssi_rest_api's "
        "lib/errors.py) for a failed request; empty on success.",
    )
    request_body = fields.Text(
        readonly=True,
        help="Redacted request body, only ever populated when the "
        "ssi_rest_api.log_body system parameter is enabled. Always "
        "empty otherwise; credential-shaped keys (password, token, "
        "secret, authorization, ...) are always redacted even when "
        "enabled.",
    )
    response_size = fields.Integer(
        readonly=True,
        help="Size, in bytes, of the response body sent to the client.",
    )

    @api.autovacuum
    def _gc_expired_request_log(self):
        """Delete rows older than the configured retention window.

        Hooked into core's ``ir.autovacuum`` mechanism: any
        ``@api.autovacuum``-decorated method on *any* model is
        discovered and called by ``ir.autovacuum._run_vacuum_cleaner``
        (``inspect.getmembers(model.__class__, is_autovacuum)`` over
        every model in ``self.env.values()`` -- see
        ``odoo/addons/base/models/ir_autovacuum.py``); inheriting
        ``ir.autovacuum`` itself is neither required nor correct for
        this (verified against Odoo 19 core, see this method's
        docstring continuation below) -- this is exactly the pattern
        core's own ``res.device.log._gc_device_log`` follows on its own
        (non-``ir.autovacuum``-inheriting) model. Deliberately not a
        bespoke ``ir.cron`` record (binding, backlog issue #15's
        Keputusan Desain: the intent -- purge through the autovacuum
        mechanism, no bespoke cron -- is met by this decorator; the
        issue's literal wording ("_inherit ir.autovacuum") would in
        fact double-run every *other* module's autovacuum method too,
        since ``_run_vacuum_cleaner`` would then discover them a second
        time through this model's own inherited members).

        Retention window comes from the ``ir.config_parameter``
        ``ssi_rest_api.log_retention_days`` (already seeded by
        ``ssi_rest_api``, default 30); a non-positive or unparsable
        value disables purging rather than deleting everything.
        """
        icp = self.env["ir.config_parameter"].sudo()
        try:
            retention_days = int(icp.get_param("ssi_rest_api.log_retention_days", "30"))
        except ValueError:
            retention_days = 30
        if retention_days <= 0:
            return
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        expired = self.sudo().search([("create_date", "<", cutoff)])
        expired.unlink()
