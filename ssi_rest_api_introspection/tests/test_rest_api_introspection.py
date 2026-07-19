# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the introspection endpoints (backlog issue
#12).

Python murni — pemicu P7 (L-19): every scenario below drives the real
dispatcher (auth, ACL-filtered results, status codes) through an actual
HTTP request. Every test method gets its own fresh `HttpCase.opener`
(framework guarantee, see backlog issue #10's module docstring).
"""

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


@tagged("post_install", "-at_install")
class TestSsiRestApiIntrospection(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "Introspection Test User",
                "login": "ssi_rest_api_introspection_test_user@example.com",
                "email": "ssi_rest_api_introspection_test_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="introspection test key", expiration_date=None)
        )

    def _headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def test_models_list_only_contains_readable_models(self):
        response = self.url_open(
            "/api/v1/introspection/models", headers=self._headers()
        )
        self.assertEqual(response.status_code, 200)
        models = {entry["model"] for entry in response.json()}
        # res.partner: readable by base.group_user (see
        # base/security/ir.model.access.csv).
        self.assertIn("res.partner", models)
        # ir.model itself: base.group_user has NO access row at all.
        self.assertNotIn("ir.model", models)

    def test_access_rights_read_only_model(self):
        response = self.url_open(
            "/api/v1/introspection/access_rights?model=res.partner",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["read"])
        self.assertFalse(body["write"])
        self.assertFalse(body["create"])
        self.assertFalse(body["unlink"])

    def test_has_group_owned_group_is_true(self):
        response = self.url_open(
            "/api/v1/introspection/has_group?group_xmlid=base.group_user",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["result"])

    def test_company_info_only_includes_user_companies(self):
        response = self.url_open(
            "/api/v1/introspection/company", headers=self._headers()
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["company"]["id"], self.test_user.company_id.id)
        company_ids = {entry["id"] for entry in body["companies"]}
        self.assertEqual(company_ids, set(self.test_user.company_ids.ids))

    def test_record_metadata_includes_xmlid_and_audit_fields(self):
        group = self.env.ref("base.group_user")
        response = self.url_open(
            f"/api/v1/introspection/models/res.groups/{group.id}/metadata",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("create_date", body)
        self.assertEqual(body["xmlid"], "base.group_user")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_fields_on_unreadable_model_is_403(self):
        response = self.url_open(
            "/api/v1/introspection/models/ir.model/fields", headers=self._headers()
        )
        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "access_denied")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_has_group_unknown_xmlid_is_404(self):
        response = self.url_open(
            "/api/v1/introspection/has_group?group_xmlid=base.no_such_group_xmlid",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    @mute_logger(_DISPATCHER_LOGGER)
    def test_no_credential_is_401_with_www_authenticate(self):
        response = self.url_open("/api/v1/introspection/models")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers.get("WWW-Authenticate"))
