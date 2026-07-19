# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Tests for access-profile evaluation and enforcement (backlog issue #7).

Python murni — pemicu P1 (L-01/L-02): every scenario below asserts the
*return value* of a method (`rule._matches_request(...)`,
`profile._evaluate_request(...)`,
`access_profile._check_request_access(...)`), never a field read off a
record in a YAML scenario's registry — the whole point of these methods
being ``request``-free (backlog issue #7's binding Keputusan Desain) is
that they can be exercised exactly this way, but the YAML DSL's `assert`
action has no way to capture or compare a bare method return value at all.
"""

from odoo import http
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


class SsiRestAccessProfileTestController(http.Controller):
    """Test-only scaffolding — see `test_rest_error_envelope.py`'s module
    docstring for the rationale of defining it here rather than in
    `controllers/main.py`."""

    @rest_route(
        ["/test-access-profile"],
        auth="ssi_rest",
        schemes=(),
        operation="read",
        model="res.partner",
    )
    def test_access_profile(self, **kwargs):
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestAccessProfileRuleMatching(TransactionCase):
    def _rule(self, **values):
        return self.env["ssi_rest_access_profile.rule"].create(
            {"profile_id": self.profile.id, "sequence": 10, "effect": "allow", **values}
        )

    def setUp(self):
        super().setUp()
        self.profile = self.env["ssi_rest_access_profile"].create(
            {"name": "Matching Profile", "code": "matching_profile"}
        )

    def test_empty_path_pattern_matches_everything(self):
        rule = self._rule()
        self.assertTrue(
            rule._matches_request("/api/v1/orm/res.partner", "GET", None, None)
        )

    def test_path_pattern_glob_match(self):
        rule = self._rule(path_pattern="/api/v1/orm/*")
        self.assertTrue(
            rule._matches_request("/api/v1/orm/res.partner", "GET", None, None)
        )
        self.assertFalse(rule._matches_request("/api/v1/ping", "GET", None, None))

    def test_invert_flips_path_pattern_match_only(self):
        rule = self._rule(path_pattern="/api/v1/ping", invert=True)
        # Path does NOT match the pattern -> invert makes this a match.
        self.assertTrue(
            rule._matches_request("/api/v1/orm/res.partner", "GET", None, None)
        )
        # Path DOES match the pattern -> invert makes this NOT a match.
        self.assertFalse(rule._matches_request("/api/v1/ping", "GET", None, None))

    def test_http_methods_filter(self):
        rule = self._rule(http_methods="GET")
        self.assertTrue(rule._matches_request("/api/v1/ping", "GET", None, None))
        self.assertFalse(rule._matches_request("/api/v1/ping", "POST", None, None))

    def test_model_pattern_filter(self):
        rule = self._rule(model_pattern="res.partner")
        self.assertTrue(
            rule._matches_request("/api/v1/orm/res.partner", "GET", "res.partner", None)
        )
        self.assertFalse(
            rule._matches_request("/api/v1/orm/res.users", "GET", "res.users", None)
        )

    def test_operation_any_matches_every_operation(self):
        rule = self._rule(operation="any")
        self.assertTrue(rule._matches_request("/x", "GET", None, "read"))
        self.assertTrue(rule._matches_request("/x", "GET", None, "write"))

    def test_operation_specific_only_matches_itself(self):
        rule = self._rule(operation="read")
        self.assertTrue(rule._matches_request("/x", "GET", None, "read"))
        self.assertFalse(rule._matches_request("/x", "GET", None, "write"))


@tagged("post_install", "-at_install")
class TestSsiRestAccessProfileEvaluation(TransactionCase):
    def test_first_matching_rule_by_sequence_wins(self):
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Precedence Profile",
                "code": "eval_precedence_profile",
                "rule_ids": [
                    (0, 0, {"sequence": 20, "effect": "allow"}),
                    (0, 0, {"sequence": 10, "effect": "deny"}),
                ],
            }
        )
        self.assertFalse(profile._evaluate_request("/x", "GET", None, None))

    def test_no_matching_rule_falls_back_to_default_effect(self):
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Fallback Profile",
                "code": "eval_fallback_profile",
                "default_effect": "deny",
                "rule_ids": [
                    (
                        0,
                        0,
                        {"sequence": 10, "effect": "allow", "path_pattern": "/never"},
                    ),
                ],
            }
        )
        self.assertFalse(profile._evaluate_request("/x", "GET", None, None))

    def test_matching_allow_rule_overrides_deny_default(self):
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Allow Rule Profile",
                "code": "eval_allow_rule_profile",
                "default_effect": "deny",
                "rule_ids": [(0, 0, {"sequence": 10, "effect": "allow"})],
            }
        )
        self.assertTrue(profile._evaluate_request("/x", "GET", None, None))

    def test_user_without_any_applicable_profile_is_allowed(self):
        user = self.env["res.users"].create(
            {
                "name": "No Profile User",
                "login": "ssi_rest_no_profile_user@example.com",
                "email": "ssi_rest_no_profile_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        allowed = self.env["ssi_rest_access_profile"]._check_request_access(
            user, "/x", "GET", None, None
        )
        self.assertTrue(allowed)

    def test_union_across_profiles_allows_if_any_profile_allows(self):
        user = self.env["res.users"].create(
            {
                "name": "Two Profile User",
                "login": "ssi_rest_two_profile_user@example.com",
                "email": "ssi_rest_two_profile_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Deny Everything",
                "code": "union_deny_profile",
                "default_effect": "deny",
                "user_ids": [(6, 0, [user.id])],
            }
        )
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Allow Everything",
                "code": "union_allow_profile",
                "default_effect": "allow",
                "user_ids": [(6, 0, [user.id])],
            }
        )
        allowed = self.env["ssi_rest_access_profile"]._check_request_access(
            user, "/x", "GET", None, None
        )
        self.assertTrue(allowed)


@tagged("post_install", "-at_install")
class TestSsiRestAccessProfileHttpEnforcement(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "Enforced User",
                "login": "ssi_rest_enforced_user@example.com",
                "email": "ssi_rest_enforced_user@example.com",
                "password": "Sup3rSecret!",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="enforcement key", expiration_date=None)
        )

    def _bearer_headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def test_no_profile_installed_request_is_allowed(self):
        response = self.url_open(
            "/api/v1/test-access-profile", headers=self._bearer_headers()
        )
        self.assertEqual(response.status_code, 200)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_deny_default_profile_without_matching_rule_is_403(self):
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Deny All",
                "code": "http_deny_all_profile",
                "default_effect": "deny",
                "user_ids": [(6, 0, [self.test_user.id])],
            }
        )
        response = self.url_open(
            "/api/v1/test-access-profile", headers=self._bearer_headers()
        )
        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "access_denied")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_denial_body_does_not_leak_profile_rule_or_model_names(self):
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Super Secret Profile Name",
                "code": "http_leak_check_profile",
                "default_effect": "deny",
                "user_ids": [(6, 0, [self.test_user.id])],
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "effect": "deny",
                            "path_pattern": "/api/v1/test-access-profile",
                        },
                    )
                ],
            }
        )
        response = self.url_open(
            "/api/v1/test-access-profile", headers=self._bearer_headers()
        )
        self.assertEqual(response.status_code, 403)
        body_text = response.text
        self.assertNotIn("Super Secret Profile Name", body_text)
        self.assertNotIn("http_leak_check_profile", body_text)
        self.assertNotIn("res.partner", body_text)

    def test_allow_rule_permits_request(self):
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Allow This Endpoint",
                "code": "http_allow_profile",
                "default_effect": "deny",
                "user_ids": [(6, 0, [self.test_user.id])],
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "effect": "allow",
                            "path_pattern": "/api/v1/test-access-profile",
                        },
                    )
                ],
            }
        )
        response = self.url_open(
            "/api/v1/test-access-profile", headers=self._bearer_headers()
        )
        self.assertEqual(response.status_code, 200)
