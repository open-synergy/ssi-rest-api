# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the ``ssi_rest`` error envelope
(``lib/dispatcher.py:SsiRestDispatcher.handle_error`` + ``lib/errors.py``).

Python murni — pemicu P7 (L-19): ``odoo-yaml-test``'s base class is locked
to ``TransactionCase``; issuing a real HTTP request (status code, response
headers, JSON error body shape) is not something the YAML DSL has any
action for at all.

The ``SsiRestErrorTestController`` below is test-only scaffolding, deliberately
defined here rather than in ``controllers/main.py``: its only purpose is to
raise a specific exception on demand so ``handle_error`` can be exercised
through a real request/response cycle instead of only by unit-testing the
helper in isolation (same rationale as the throwaway ``/ping`` endpoint in
``controllers/main.py``). It uses ``auth="public"`` for the same reason
``/ping`` does: ``SsiRestDispatcher`` never checks CSRF (binding invariant
documented on the class), so no route registered through it may rely on a
session cookie as its *sole* credential. This does not stop an already
authenticated ``HttpCase`` session from being reflected in
``request.env.user`` (``_auth_method_public`` only forces the public user
when no session is present at all), which is exactly what the
``expose_traceback`` tests below rely on to simulate an admin/non-admin
caller without turning the endpoint into an ``auth="user"`` route.
"""

from odoo import http
from odoo.exceptions import AccessError, LockError, MissingError, UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.dispatcher import REQUEST_ID_HEADER
from odoo.addons.ssi_rest_api.lib.routing import rest_route

_ACCESS_ERROR_MESSAGE = (
    "You are not allowed to access 'Secret Configuration' (secret.config) records."
)
_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


class SsiRestErrorTestController(http.Controller):
    @rest_route(["/test-error"], auth="public")
    def test_error(self, kind=None, **kwargs):
        if kind == "missing":
            raise MissingError(self.env._("The requested record no longer exists."))
        if kind == "validation":
            raise UserError(self.env._("quantity must be a positive number"))
        if kind == "lock":
            raise LockError(
                self.env._("Could not obtain a lock on the requested record(s).")
            )
        if kind == "access":
            raise AccessError(self.env._(_ACCESS_ERROR_MESSAGE))
        if kind == "boom":
            raise ZeroDivisionError("integer division or modulo by zero")
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestSuccessEnvelope(HttpCase):
    def test_success_response_has_no_result_wrapper(self):
        response = self.url_open("/api/v1/test-error")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})


@tagged("post_install", "-at_install")
class TestSsiRestErrorEnvelope(HttpCase):
    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_missing_error_is_404_missing_record(self):
        response = self.url_open("/api/v1/test-error?kind=missing")
        self.assertEqual(response.status_code, 404)
        error = response.json()["error"]
        self.assertEqual(error["code"], "missing_record")
        self.assertEqual(error["status"], 404)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_user_error_is_422_validation_error(self):
        response = self.url_open("/api/v1/test-error?kind=validation")
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(error["status"], 422)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_lock_error_is_409_lock_error(self):
        response = self.url_open("/api/v1/test-error?kind=lock")
        self.assertEqual(response.status_code, 409)
        error = response.json()["error"]
        self.assertEqual(error["code"], "lock_error")
        self.assertEqual(error["status"], 409)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_error_body_request_id_matches_response_header(self):
        response = self.url_open("/api/v1/test-error?kind=missing")
        error = response.json()["error"]
        self.assertTrue(error["request_id"])
        self.assertEqual(error["request_id"], response.headers.get(REQUEST_ID_HEADER))

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_access_error_message_does_not_leak_model_or_field(self):
        response = self.url_open("/api/v1/test-error?kind=access")
        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "access_denied")
        self.assertNotIn("secret.config", error["message"])
        self.assertNotIn("Secret Configuration", error["message"])

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_unclassified_exception_is_500_internal_error_without_traceback(self):
        # Regression (binding): with `expose_traceback` at its default
        # (`False`), no response may ever contain a raw Python traceback,
        # regardless of what exception was raised.
        self.env["ir.config_parameter"].sudo().set_param(
            "ssi_rest_api.expose_traceback", "False"
        )
        response = self.url_open("/api/v1/test-error?kind=boom")
        self.assertEqual(response.status_code, 500)
        error = response.json()["error"]
        self.assertEqual(error["code"], "internal_error")
        self.assertNotIn("Traceback (most recent call last)", response.text)
        self.assertIsNone(error["details"])


@tagged("post_install", "-at_install")
class TestSsiRestTracebackDisclosureGate(HttpCase):
    def setUp(self):
        super().setUp()
        self.icp = self.env["ir.config_parameter"].sudo()
        self.non_admin = self.env["res.users"].create(
            {
                "name": "SSI REST Non-Admin (HTTP)",
                "login": "ssi_rest_test_non_admin_http",
                "email": "ssi_rest_test_non_admin_http@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_group_system_user_with_icp_true_sees_traceback_in_details(self):
        self.icp.set_param("ssi_rest_api.expose_traceback", "True")
        self.authenticate("admin", "admin")
        response = self.url_open("/api/v1/test-error?kind=boom")
        self.assertEqual(response.status_code, 500)
        error = response.json()["error"]
        traceback_text = error["details"]["traceback"]
        self.assertIn("Traceback (most recent call last)", traceback_text)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_non_group_system_user_with_icp_true_never_sees_traceback(self):
        self.icp.set_param("ssi_rest_api.expose_traceback", "True")
        self.authenticate("ssi_rest_test_non_admin_http", "irrelevant")
        response = self.url_open("/api/v1/test-error?kind=boom")
        self.assertEqual(response.status_code, 500)
        error = response.json()["error"]
        self.assertIsNone(error["details"])
        self.assertNotIn("Traceback (most recent call last)", response.text)
