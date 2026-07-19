# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Core regression suite (backlog issue #10).

Locks in decisions already implemented and tested piecemeal in earlier
backlog items (#3, #4, #7), plus the pieces not yet covered anywhere:
routing-map introspection (``readonly`` on every create/write/unlink
route) and the proof that an access profile can never grant access
beyond Odoo's own ACL. Test-only scaffolding (provider, controller) lives
here under ``tests/``, never in ``models/``/``controllers/`` — see
``test_rest_error_envelope.py``'s module docstring for the rationale.

Where each of the five binding regressions from this issue's Keputusan
Desain already lives:

1. No response body ever contains a Python traceback ->
   ``test_rest_error_envelope.py::test_unclassified_exception_is_500_internal_error_without_traceback``.
2. ``routing['readonly'] is False`` for every create/write/unlink route ->
   new, see :meth:`TestSsiRestRoutingMapReadonly` below (there are no
   real create/write/unlink endpoints yet — modules #11+ add them — so
   this asserts against ``rest_operation`` and is vacuously green today,
   a forward-looking guard rather than a no-op).
3. First provider's verify failure is 401, no fallthrough ->
   ``test_rest_auth.py::test_verify_failure_is_401_without_fallthrough``.
4. Two simultaneous credentials from two providers is 400
   ``multiple_credentials`` ->
   ``test_rest_auth.py::test_two_credentials_at_once_is_400_multiple_credentials``.
5. An access profile can never grant access beyond ACL -> new, see
   :meth:`TestSsiRestAccessProfileNeverExceedsAcl` below.
"""

from unittest.mock import patch

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.auth import RestAuthResult
from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


class SsiRestCoreRegressionTestController(http.Controller):
    """Test-only scaffolding, under ``/test/`` (backlog issue #10's
    Keputusan Desain: test-only routes are isolated from the real
    endpoint surface and easy to exclude from generated docs by prefix).
    """

    @rest_route(["/test/echo"], auth="ssi_rest")
    def test_echo(self, **kwargs):
        return {"uid": request.env.uid}

    @rest_route(["/test/restricted-write"], auth="ssi_rest", operation="create")
    def test_restricted_write(self, **kwargs):
        # `ir.module.category` grants nothing at all to plain internal
        # users (only read, and only to base.group_erp_manager, see
        # base/security/ir.model.access.csv) — a real ACL wall no access
        # profile may ever widen.
        request.env["ir.module.category"].create({"name": "Should Not Exist"})
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestRoutingMapReadonly(TransactionCase):
    def test_every_create_write_unlink_route_is_not_readonly(self):
        routing_map = self.env["ir.http"].routing_map()
        offenders = []
        for rule in routing_map.iter_rules():
            routing = getattr(rule.endpoint, "routing", None)
            if not routing or routing.get("type") != "ssi_rest":
                continue
            if routing.get("rest_operation") not in ("create", "write", "unlink"):
                continue
            if routing.get("readonly") is not False:
                offenders.append((rule.endpoint, routing.get("readonly")))
        self.assertFalse(
            offenders,
            f"ssi_rest create/write/unlink routes must have readonly=False: "
            f"{offenders}",
        )


@tagged("post_install", "-at_install")
class TestSsiRestAccessProfileNeverExceedsAcl(HttpCase):
    def setUp(self):
        super().setUp()
        self.plain_user = self.env["res.users"].create(
            {
                "name": "No ACL User",
                "login": "ssi_rest_core_regression_no_acl_user@example.com",
                "email": "ssi_rest_core_regression_no_acl_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.env["ssi_rest_access_profile"].create(
            {
                "name": "Allow Everything",
                "code": "core_regression_allow_all_profile",
                "default_effect": "allow",
                "user_ids": [(6, 0, [self.plain_user.id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.plain_user)
            .sudo()
            ._generate(scope="rpc", name="regression key", expiration_date=None)
        )

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_allow_everything_profile_does_not_bypass_real_acl(self):
        response = self.url_open(
            "/api/v1/test/restricted-write",
            headers={"Authorization": f"Bearer {self.rpc_key}"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")
        self.assertEqual(
            self.env["ir.module.category"].search_count(
                [("name", "=", "Should Not Exist")]
            ),
            0,
        )


@tagged("post_install", "-at_install")
class TestSsiRestSequentialRequestsDoNotLeakSession(HttpCase):
    """Regression for the single biggest trap this issue's Keputusan
    Desain calls out: ``HttpCase.opener`` is a ``requests.Session()``
    that, if reused with a stale cookie, would silently authenticate a
    request that sent no credentials at all."""

    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "Sequential Session User",
                "login": "ssi_rest_sequential_session_user@example.com",
                "email": "ssi_rest_sequential_session_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="sequential key", expiration_date=None)
        )

    @mute_logger(_DISPATCHER_LOGGER)
    def test_authenticated_call_then_bare_call_in_same_opener_still_401(self):
        authenticated = self.url_open(
            "/api/v1/test/echo",
            headers={"Authorization": f"Bearer {self.rpc_key}"},
        )
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(authenticated.json()["uid"], self.test_user.id)

        # Same `self.opener` (no new Authorization header, and `ssi_rest`
        # never accepts a bare session cookie as credential per
        # `SsiRestDispatcher`'s own binding CSRF invariant) -> still 401,
        # never silently authenticated via a leftover cookie.
        bare = self.url_open("/api/v1/test/echo")
        self.assertEqual(bare.status_code, 401)
        self.assertEqual(bare.json()["error"]["code"], "authentication_required")


@tagged("post_install", "-at_install")
class TestSsiRestDummyProviderRegisteredInTestTransaction(HttpCase):
    """Proves the registry contract backlog issue #4 chose record-based
    (over import-time) registration specifically for: a scheme created
    via a plain ``create()`` call inside a test's own transaction is
    immediately live in the registry, with no concrete auth module
    installed, and never persists past that transaction."""

    def test_scheme_created_in_test_transaction_is_immediately_active(self):
        provider_cls = self.env.registry["mixin.rest_authenticator"]
        self.env["ssi_rest_auth_scheme"].sudo().create(
            {
                "name": "Transaction-Local Dummy",
                "code": "core_regression_dummy",
                "provider_model": "mixin.rest_authenticator",
                "sequence": 5,
            }
        )
        # A header that matches neither the real `basic` nor `bearer`
        # provider's prefix (see #5): only the mocked dummy provider
        # below is meant to extract a credential from it, never the real
        # ones (also active in the registry, seeded by data XML) —
        # otherwise this would spuriously hit `multiple_credentials`.
        with (
            patch.object(
                provider_cls, "_rest_auth_extract", side_effect=["dummy-cred"]
            ),
            patch.object(
                provider_cls,
                "_rest_auth_verify",
                side_effect=lambda credential: RestAuthResult(
                    uid=self.env.uid, scheme="core_regression_dummy"
                ),
            ),
        ):
            response = self.url_open(
                "/api/v1/test/echo", headers={"Authorization": "Dummy irrelevant"}
            )
        # The dummy scheme was picked up by the registry (its provider's
        # patched `_rest_auth_extract` was actually invoked) — proven by
        # a non-401 outcome rather than "authentication_required". That
        # this test's own `ssi_rest_auth_scheme` record never leaks past
        # this transaction is guaranteed by `TransactionCase` itself (the
        # framework rolls back after each test method), not something
        # observable from within the test that created it.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uid"], self.env.uid)
