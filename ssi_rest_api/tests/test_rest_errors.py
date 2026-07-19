# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Unit tests for the ``lib/errors.py`` classification/envelope helpers.

Python murni — pemicu P1 (L-01): every assertion below reads the *return
value* of a plain Python function (`classify_exception`,
`traceback_disclosure_allowed`, `build_error_body`), never a record field
read through `odoo-yaml-test`'s `assert` step (L-02). `TransactionCase` is
only used (rather than bare `unittest.TestCase`) so `test_tags` gets set by
`BaseCase.__init_subclass__` and so `traceback_disclosure_allowed` can be
exercised against a real `res.users`/group setup.
"""

from odoo.exceptions import (
    AccessDenied,
    AccessError,
    LockError,
    MissingError,
    UserError,
)
from odoo.tests import TransactionCase, tagged

from odoo.addons.ssi_rest_api.lib.errors import (
    build_error_body,
    classify_exception,
    traceback_disclosure_allowed,
)


@tagged("post_install", "-at_install")
class TestClassifyException(TransactionCase):
    def test_missing_error_maps_to_404_missing_record(self):
        status, code, message = classify_exception(MissingError("gone"))
        self.assertEqual(status, 404)
        self.assertEqual(code, "missing_record")
        self.assertEqual(message, "gone")

    def test_lock_error_maps_to_409_lock_error(self):
        status, code, message = classify_exception(LockError("locked"))
        self.assertEqual(status, 409)
        self.assertEqual(code, "lock_error")
        self.assertEqual(message, "locked")

    def test_access_denied_maps_to_403_access_denied_generic_message(self):
        status, code, message = classify_exception(AccessDenied("wrong password"))
        self.assertEqual(status, 403)
        self.assertEqual(code, "access_denied")
        self.assertNotIn("password", message)

    def test_access_error_maps_to_403_access_denied_generic_message(self):
        status, code, message = classify_exception(
            AccessError("You are not allowed to access 'Secret Model' (secret.model)")
        )
        self.assertEqual(status, 403)
        self.assertEqual(code, "access_denied")
        self.assertNotIn("secret.model", message)
        self.assertNotIn("Secret Model", message)

    def test_plain_user_error_maps_to_422_validation_error(self):
        status, code, message = classify_exception(
            UserError("quantity must be positive")
        )
        self.assertEqual(status, 422)
        self.assertEqual(code, "validation_error")
        self.assertEqual(message, "quantity must be positive")

    def test_unclassified_exception_maps_to_500_internal_error(self):
        status, code, message = classify_exception(ZeroDivisionError("boom"))
        self.assertEqual(status, 500)
        self.assertEqual(code, "internal_error")
        self.assertNotIn("boom", message)

    def test_access_denied_is_not_mistaken_for_plain_user_error(self):
        # Regression: AccessDenied/AccessError are UserError subclasses, so
        # the mapping table order must put them ahead of the generic
        # UserError entry, or they would incorrectly report
        # "validation_error" instead of "access_denied".
        _status, code, _message = classify_exception(AccessDenied())
        self.assertEqual(code, "access_denied")


@tagged("post_install", "-at_install")
class TestTracebackDisclosureAllowed(TransactionCase):
    def setUp(self):
        super().setUp()
        self.icp = self.env["ir.config_parameter"].sudo()
        self.admin = self.env.ref("base.user_admin")
        self.non_admin = self.env["res.users"].create(
            {
                "name": "SSI REST Non-Admin",
                "login": "ssi_rest_test_non_admin",
                "email": "ssi_rest_test_non_admin@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.assertTrue(self.admin.has_group("base.group_system"))
        self.assertFalse(self.non_admin.has_group("base.group_system"))

    def test_none_env_never_allowed(self):
        self.assertFalse(traceback_disclosure_allowed(None))

    def test_disallowed_when_icp_false_even_for_group_system_user(self):
        self.icp.set_param("ssi_rest_api.expose_traceback", "False")
        env = self.env(user=self.admin)
        self.assertFalse(traceback_disclosure_allowed(env))

    def test_disallowed_when_user_not_in_group_system_even_if_icp_true(self):
        self.icp.set_param("ssi_rest_api.expose_traceback", "True")
        env = self.env(user=self.non_admin)
        self.assertFalse(traceback_disclosure_allowed(env))

    def test_allowed_only_when_both_conditions_hold(self):
        self.icp.set_param("ssi_rest_api.expose_traceback", "True")
        env = self.env(user=self.admin)
        self.assertTrue(traceback_disclosure_allowed(env))


@tagged("post_install", "-at_install")
class TestBuildErrorBody(TransactionCase):
    def test_shape_matches_the_single_error_envelope(self):
        body = build_error_body(
            code="validation_error",
            message="bad input",
            status=422,
            request_id="req-1",
            details=None,
        )
        self.assertEqual(
            body,
            {
                "error": {
                    "code": "validation_error",
                    "message": "bad input",
                    "status": 422,
                    "request_id": "req-1",
                    "details": None,
                }
            },
        )
