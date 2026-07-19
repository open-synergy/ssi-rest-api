# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the report list/render endpoints (backlog
issue #14).

Python murni — pemicu P7 (L-19): every scenario drives the real
dispatcher (auth, ACL, ``ir.actions.report`` rendering) through an actual
HTTP request. Every scenario reuses core's own built-in
``base.report_irmodeloverview`` (target model ``ir.model``) instead of
defining a new report action — this backlog item's scope explicitly
excludes creating/changing report definitions. ``ir.model`` is
deliberately only readable by ``base.group_system``/``group_erp_manager``
(see ``ssi_rest_api_introspection``'s tests for the same fact), which
this file leans on to exercise both the readable and unreadable paths
without adding any bespoke security rule. Every test method gets its own
fresh ``HttpCase.opener`` (framework guarantee, see backlog issue #10's
module docstring).
"""

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"
_MODEL_OVERVIEW_REPORT = "base.report_irmodeloverview"


@tagged("post_install", "-at_install")
class TestSsiRestApiReport(HttpCase):
    def setUp(self):
        super().setUp()
        self.manager_user = self.env["res.users"].create(
            {
                "name": "Report Test Manager",
                "login": "ssi_rest_api_report_manager@example.com",
                "email": "ssi_rest_api_report_manager@example.com",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("base.group_system").id,
                        ],
                    )
                ],
            }
        )
        self.reader_user = self.env["res.users"].create(
            {
                "name": "Report Test Reader",
                "login": "ssi_rest_api_report_reader@example.com",
                "email": "ssi_rest_api_report_reader@example.com",
                # `base.group_user` alone has no access to `ir.model` —
                # deliberate, exercises the ACL-filtered/denied scenarios.
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.manager_key = (
            self.env["res.users.apikeys"]
            .with_user(self.manager_user)
            .sudo()
            ._generate(scope="rpc", name="report manager key", expiration_date=None)
        )
        self.reader_key = (
            self.env["res.users.apikeys"]
            .with_user(self.reader_user)
            .sudo()
            ._generate(scope="rpc", name="report reader key", expiration_date=None)
        )
        ir_model = self.env["ir.model"].sudo()
        self.partner_model_id = ir_model.search(
            [("model", "=", "res.partner")], limit=1
        ).id
        self.company_model_id = ir_model.search(
            [("model", "=", "res.company")], limit=1
        ).id

    def _headers(self, key):
        return {"Authorization": f"Bearer {key}"}

    def test_list_includes_report_when_model_readable(self):
        response = self.url_open(
            "/api/v1/report/list", headers=self._headers(self.manager_key)
        )
        self.assertEqual(response.status_code, 200)
        names = {entry["report_name"] for entry in response.json()}
        self.assertIn(_MODEL_OVERVIEW_REPORT, names)

    def test_list_excludes_report_when_model_unreadable(self):
        response = self.url_open(
            "/api/v1/report/list", headers=self._headers(self.reader_key)
        )
        self.assertEqual(response.status_code, 200)
        names = {entry["report_name"] for entry in response.json()}
        self.assertNotIn(_MODEL_OVERVIEW_REPORT, names)

    def test_list_filtered_by_model(self):
        response = self.url_open(
            "/api/v1/report/list",
            headers=self._headers(self.manager_key),
            params={"model": "ir.model"},
        )
        self.assertEqual(response.status_code, 200)
        entries = response.json()
        self.assertTrue(entries)
        self.assertTrue(all(entry["model"] == "ir.model" for entry in entries))

    def test_render_pdf_single_id(self):
        response = self.url_open(
            "/api/v1/report/render",
            headers=self._headers(self.manager_key),
            params={
                "report_name": _MODEL_OVERVIEW_REPORT,
                "ids": self.partner_model_id,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_render_pdf_multiple_ids_returns_one_document(self):
        response = self.url_open(
            "/api/v1/report/render",
            headers=self._headers(self.manager_key),
            params={
                "report_name": _MODEL_OVERVIEW_REPORT,
                "ids": f"{self.partner_model_id},{self.company_model_id}",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_render_unknown_report_name_is_404(self):
        response = self.url_open(
            "/api/v1/report/render",
            headers=self._headers(self.manager_key),
            params={"report_name": "ssi_rest_api_report.no_such_report", "ids": 1},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_render_unreadable_record_is_403(self):
        response = self.url_open(
            "/api/v1/report/render",
            headers=self._headers(self.reader_key),
            params={
                "report_name": _MODEL_OVERVIEW_REPORT,
                "ids": self.partner_model_id,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_render_without_ids_is_422(self):
        response = self.url_open(
            "/api/v1/report/render",
            headers=self._headers(self.manager_key),
            params={"report_name": _MODEL_OVERVIEW_REPORT},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
