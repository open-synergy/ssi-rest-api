# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""HTTP-level test proving the request body is only ever persisted, and
only ever redacted, when ``ssi_rest_api.log_body`` is enabled (backlog
issue #15).

Python murni -- pemicu P7 (L-19): a real HTTP POST body round-trip is
out of reach for ``odoo-yaml-test``'s ``TransactionCase``-locked base
class.

Uses ``HttpCase.url_open`` (**not** a bare ``requests.Session()``) --
see ``test_ssi_rest_request_log_dispatcher.py``'s module docstring for
why a bare session fails every request with 400 under Odoo 19's own
test harness.
"""

import json

from odoo import http
from odoo.tests import HttpCase, tagged

from odoo.addons.ssi_rest_api.lib.routing import rest_route


class SsiRestApiLogBodyTestController(http.Controller):
    """Test-only scaffolding (backlog issue #15) -- see
    ``test_ssi_rest_request_log_dispatcher.py``'s module docstring for
    the same rationale."""

    @rest_route(["/test/log/echo-body"], auth="ssi_rest", methods=["POST"])
    def echo_body(self, **kwargs):
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestRequestLogBodyRedaction(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "Request Log Body Test User",
                "login": "ssi_rest_request_log_body_user@example.com",
                "email": "ssi_rest_request_log_body_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(
                scope="rpc", name="body redaction test key", expiration_date=None
            )
        )

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def _log_for(self, request_id):
        return (
            self.env["ssi_rest_request_log"]
            .sudo()
            .search([("request_id", "=", request_id)])
        )

    def test_request_body_is_redacted_when_log_body_enabled(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "ssi_rest_api.log_body", "True"
        )
        response = self.url_open(
            "/api/v1/test/log/echo-body",
            json={"username": "alice", "password": "super-secret"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-Id")

        log = self._log_for(request_id)
        self.assertEqual(len(log), 1)
        self.assertTrue(log.request_body)
        body = json.loads(log.request_body)
        self.assertEqual(body.get("username"), "alice")
        self.assertEqual(body.get("password"), "***")
        self.assertNotIn("super-secret", log.request_body)

    def test_request_body_empty_when_log_body_disabled(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "ssi_rest_api.log_body", "False"
        )
        response = self.url_open(
            "/api/v1/test/log/echo-body",
            json={"username": "alice", "password": "super-secret"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-Id")

        log = self._log_for(request_id)
        self.assertEqual(len(log), 1)
        self.assertFalse(log.request_body)
