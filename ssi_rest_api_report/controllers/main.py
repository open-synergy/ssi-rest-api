# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""List/render REST endpoints over ``ir.actions.report``.

Functional requirements were derived from analysing ``muk_rest``'s
behaviour (used **only** as a functional reference — its license is MuK
Proprietary v1.0); this is a clean-room implementation: no code, naming,
or file structure is copied from it.

BINDING (do not remove this comment when editing this file): ``sudo()``
is forbidden anywhere in this module's own code. Core's
``ir.actions.report._get_report()``/``_render_qweb_*`` do internally
``sudo()`` the *report definition* (config metadata, not user data) —
that is core's own established behaviour, not something this module
opts into — but the *target records* being rendered are never sudo'd
here: ``report_render`` below calls ``records.check_access("read")``
itself, the same explicit-check pattern backlog issue #13 established
for ``ir.binary`` (which likewise never checks row-level access on an
arbitrary model on its own).

Binding risk (Keputusan Desain): a PDF render with ``report.attachment``
configured makes core write an ``ir.attachment`` row *inside*
``_render_qweb_pdf`` itself — not something this endpoint's body can
defer to ``cr.postcommit``, since it happens inside the call being made,
not after it. ``report_pdf_no_attachment=True`` (passed via context
below) disables that read/write path entirely, keeping rendering a pure,
retry-safe, side-effect-free operation regardless of how the report
action being rendered is configured.
"""

from odoo import http
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from . import _helpers

#: ``report_type`` (``ir.actions.report``) -> response ``Content-Type``.
#: Mirrors what core's own ``/report/<converter>/<reportname>`` controller
#: hand-builds per converter branch (``web/controllers/report.py``) —
#: there is no reusable mapping helper for this in core.
_CONTENT_TYPES = {
    "qweb-pdf": "application/pdf",
    "qweb-html": "text/html",
    "qweb-text": "text/plain",
}


class SsiRestReportController(http.Controller):
    @rest_route(
        ["/report/list"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def report_list(self, model=None, **kwargs):
        domain = [("model", "=", model)] if model else []
        reports = request.env["ir.actions.report"].search(domain)
        access = request.env["ir.model.access"]
        result = []
        for report in reports:
            # A report not tied to any model has nothing to filter; a
            # report tied to a model the caller cannot read must not be
            # listed (Keputusan Desain: "daftar laporan wajib tersaring
            # ACL").
            if report.model and not access.check(
                report.model, "read", raise_exception=False
            ):
                continue
            result.append(
                {
                    "report_name": report.report_name,
                    "name": report.name,
                    "model": report.model,
                    "report_type": report.report_type,
                    "xmlid": report.get_external_id().get(report.id) or False,
                }
            )
        return result

    @rest_route(
        ["/report/render"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=False,
    )
    def report_render(self, report_name=None, ids=None, **kwargs):
        report = _helpers.resolve_report(request.env, report_name)
        record_ids = _helpers.parse_ids(ids)
        if not record_ids:
            raise RestAuthError("validation_error", "ids is required.", status=422)
        if report.model:
            records = request.env[report.model].browse(record_ids)
            records.check_access("read")
        content_type = _CONTENT_TYPES.get(report.report_type)
        if content_type is None:
            raise RestAuthError(
                "validation_error",
                f"Report type {report.report_type!r} is not supported.",
                status=422,
            )
        report_model = request.env["ir.actions.report"].with_context(
            report_pdf_no_attachment=True
        )
        content, _kind = report_model._render(report.report_name, record_ids)
        return request.make_response(content, headers=[("Content-Type", content_type)])
