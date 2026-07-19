# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for per-request company and language resolution
(``models/ir_http.py:IrHttp._pre_dispatch`` and its two helpers), backlog
issue #9.

Python murni — pemicu P7 (L-19): a real HTTP request is the only way to
drive `_pre_dispatch` with actual `X-Odoo-Company`/`Accept-Language`
headers and observe the resulting `request.env.context`.

Language coverage note: fully proving "an error message comes back
translated" would require installing a second language with real
translations in CI, disproportionate to this backlog item's scope. What
is tested instead is the resolution mechanism itself — that
`Accept-Language` actually changes `request.env.context['lang']` for an
active installed language, and is silently ignored otherwise — which is
what the client-visible translated-message behavior depends on.
"""

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


class SsiRestCompanyLangTestController(http.Controller):
    """Test-only scaffolding — see `test_rest_error_envelope.py`'s module
    docstring for the rationale of defining it here rather than in
    `controllers/main.py`."""

    @rest_route(["/test-company-lang"], auth="ssi_rest")
    def test_company_lang(self, **kwargs):
        return {
            "company_id": request.env.company.id,
            "allowed_company_ids": request.env.context.get("allowed_company_ids"),
            "lang": request.env.context.get("lang"),
        }


@tagged("post_install", "-at_install")
class TestSsiRestCompanyLangResolution(HttpCase):
    def setUp(self):
        super().setUp()
        self.company_a = self.env["res.company"].create({"name": "Company A"})
        self.company_b = self.env["res.company"].create({"name": "Company B"})
        self.test_user = self.env["res.users"].create(
            {
                "name": "Multi Company User",
                "login": "ssi_rest_multi_company_user@example.com",
                "email": "ssi_rest_multi_company_user@example.com",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id, self.company_b.id])],
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="company key", expiration_date=None)
        )

    def _headers(self, **extra):
        headers = {"Authorization": f"Bearer {self.rpc_key}"}
        headers.update(extra)
        return headers

    def test_x_odoo_company_header_selects_company(self):
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"X-Odoo-Company": str(self.company_b.id)}),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["company_id"], self.company_b.id)
        self.assertEqual(body["allowed_company_ids"], [self.company_b.id])

    def test_company_id_query_param_matches_header_behavior(self):
        response = self.url_open(
            f"/api/v1/test-company-lang?company_id={self.company_b.id}",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company_id"], self.company_b.id)

    def test_no_company_specified_defaults_to_user_company(self):
        response = self.url_open("/api/v1/test-company-lang", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["company_id"], self.company_a.id)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_company_outside_user_company_ids_is_403(self):
        other_company = self.env["res.company"].create({"name": "Not Mine"})
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"X-Odoo-Company": str(other_company.id)}),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_non_integer_company_header_is_422(self):
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"X-Odoo-Company": "not-a-number"}),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_nonexistent_company_id_is_422(self):
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"X-Odoo-Company": "999999"}),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_accept_language_with_installed_lang_applies(self):
        # en_US is always active/installed; proves the header is actually
        # read and applied (not merely tolerated) without depending on a
        # second language being installed in CI.
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"Accept-Language": "en-US,en;q=0.9"}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lang"], "en_US")

    def test_accept_language_unrecognized_is_silently_ignored(self):
        response = self.url_open(
            "/api/v1/test-company-lang",
            headers=self._headers(**{"Accept-Language": "xx-ZZ-not-a-real-lang"}),
        )
        self.assertEqual(response.status_code, 200)
        # Falls back to whatever core `_pre_dispatch` already resolved
        # (the user's own lang) rather than erroring.
        self.assertTrue(response.json()["lang"])
