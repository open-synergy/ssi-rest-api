# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the custom endpoint wildcard route (backlog
issue #17).

Python murni — pemicu P7 (L-19): every scenario below drives the real
dispatcher (auth, per-record readonly cursor resolution, endpoint lookup,
access-profile enforcement, status codes) through an actual HTTP request,
which `odoo-yaml-test`'s `TransactionCase`-based DSL cannot do at all.
Every test method gets its own fresh `HttpCase.opener` (framework
guarantee, matching `ssi_rest_api_orm`'s own controller test suite) — no
case here relies on, or leaks into, another's session.
"""

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api_endpoint.controllers import main as endpoint_controller

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


@tagged("post_install", "-at_install")
class TestSsiRestApiEndpoint(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "Endpoint Test User",
                "login": "ssi_rest_api_endpoint_test_user@example.com",
                "email": "ssi_rest_api_endpoint_test_user@example.com",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("base.group_partner_manager").id,
                        ],
                    )
                ],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="endpoint test key", expiration_date=None)
        )
        self.partner = self.env["res.partner"].create(
            {"name": "Endpoint Fixture Partner"}
        )
        self.res_partner_model_id = self.env.ref("base.model_res_partner").id

    def _headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def test_server_action_endpoint_returns_result(self):
        action = self.env["ir.actions.server"].create(
            {
                "name": "Endpoint Test Action",
                "model_id": self.res_partner_model_id,
                "state": "code",
                "code": "action = {'greeting': 'hello'}",
            }
        )
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Server Action Endpoint",
                "code": "/",
                "path": "greet",
                "http_method": "GET",
                "handler_type": "server_action",
                "server_action_id": action.id,
            }
        )
        response = self.url_open(f"/api/v1/x/{endpoint.path}", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], {"greeting": "hello"})

    def test_model_method_endpoint_returns_result(self):
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Copy Partner Endpoint",
                "code": "/",
                "path": "partner/copy",
                "http_method": "POST",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "copy",
            }
        )
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}",
            headers=self._headers(),
            json={"ids": [self.partner.id]},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0], self.partner.id)

    def test_minimal_endpoint_is_active_and_callable(self):
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Minimal Endpoint",
                "code": "/",
                "path": "partner/read",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
            }
        )
        self.assertTrue(endpoint.active)
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}&fields=name",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"][0]["name"], self.partner.name)

    def test_readonly_endpoint_runs_without_error(self):
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Readonly Endpoint",
                "code": "/",
                "path": "partner/read-only",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
                "is_readonly": True,
            }
        )
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}&fields=name",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"][0]["name"], self.partner.name)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_inactive_endpoint_is_404(self):
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Soon Inactive Endpoint",
                "code": "/",
                "path": "partner/inactive",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
            }
        )
        endpoint.active = False
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 404)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_call_private_method_is_rejected_not_500(self):
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Private Method Endpoint",
                "code": "/",
                "path": "partner/private",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "_compute_display_name",
            }
        )
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}",
            headers=self._headers(),
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertNotEqual(response.status_code, 500)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_call_not_covered_by_profile_ids_is_403(self):
        other_user = self.env["res.users"].create(
            {
                "name": "Other Profile User",
                "login": "ssi_rest_api_endpoint_other_user@example.com",
                "email": "ssi_rest_api_endpoint_other_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Endpoint-only Profile",
                "code": "endpoint_only_profile",
                "default_effect": "allow",
                "user_ids": [(6, 0, [other_user.id])],
            }
        )
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Restricted Endpoint",
                "code": "/",
                "path": "partner/restricted",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
                "profile_ids": [(6, 0, [profile.id])],
            }
        )
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")

    def test_call_covered_by_profile_ids_is_200(self):
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Endpoint Allow Profile",
                "code": "endpoint_allow_profile",
                "default_effect": "allow",
                "user_ids": [(6, 0, [self.test_user.id])],
            }
        )
        endpoint = self.env["ssi_rest_endpoint"].create(
            {
                "name": "Covered Endpoint",
                "code": "/",
                "path": "partner/covered",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
                "profile_ids": [(6, 0, [profile.id])],
            }
        )
        response = self.url_open(
            f"/api/v1/x/{endpoint.path}?ids={self.partner.id}&fields=name",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"][0]["name"], self.partner.name)

    def test_route_readonly_is_the_dynamic_resolver(self):
        # The `readonly=` callable itself (`_custom_endpoint_readonly`)
        # runs *before* authentication and before the request's own
        # cursor is opened (core dispatch order, see its docstring) and
        # needs a bound `odoo.http.request` — not available from a test
        # method's own thread, only from within an actual served request.
        # What this test can and does prove without faking that context:
        # the wildcard route is wired to the dynamic resolver (an object
        # identity check), not a static `True`/`False` — the resolver's
        # own per-record SQL lookup is exercised structurally by every
        # other test in this file actually completing without a
        # read/write-cursor error, readonly or not.
        routing_map = self.env["ir.http"].routing_map()
        found = False
        for rule in routing_map.iter_rules():
            routing = getattr(rule.endpoint, "routing", None)
            if not routing or routing.get("type") != "ssi_rest":
                continue
            if not any(
                "/x/<path:subpath>" in route for route in routing.get("routes", [])
            ):
                continue
            found = True
            self.assertIs(
                routing["readonly"], endpoint_controller._custom_endpoint_readonly
            )
        self.assertTrue(found, "custom endpoint route not found in routing map")

    def test_only_one_route_registered_for_every_endpoint_record(self):
        # Two records, one route: `routing_map()` must expose exactly one
        # rule for this controller's path pattern regardless of how many
        # ssi_rest_endpoint records exist (Keputusan Desain, binding).
        self.env["ssi_rest_endpoint"].create(
            {
                "name": "Route Count Endpoint A",
                "code": "/",
                "path": "route-count/a",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
            }
        )
        self.env["ssi_rest_endpoint"].create(
            {
                "name": "Route Count Endpoint B",
                "code": "/",
                "path": "route-count/b",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": self.res_partner_model_id,
                "method_name": "read",
            }
        )
        routing_map = self.env["ir.http"].routing_map()
        matches = []
        for rule in routing_map.iter_rules():
            routing = getattr(rule.endpoint, "routing", None)
            if not routing or routing.get("type") != "ssi_rest":
                continue
            if any("/x/<path:subpath>" in route for route in routing.get("routes", [])):
                matches.append(rule)
        self.assertEqual(len(matches), 1)
