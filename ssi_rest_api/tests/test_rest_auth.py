# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the ``auth="ssi_rest"`` auth method
(``models/ir_http.py:IrHttp._auth_method_ssi_rest``).

Python murni — pemicu P7 (L-19: ``odoo-yaml-test``'s base class is locked to
``TransactionCase``, a real HTTP request/response cycle is out of reach) and
P6 (L-15: no mock/patch from YAML). Two ``mixin.rest_authenticator``
providers are needed to exercise the "which of several active schemes
claimed this request" branches (no credential / one credential / two
credentials at once) — rather than defining new ORM model classes in this
package (registering a genuinely new model from a module's ``tests/``
directory, after the registry has already been built for
``--test-enable``, is not a reliable pattern), both scheme records below
share the *same* already-registered provider model
(``mixin.rest_authenticator`` itself, part of this backlog item) and its
four contract methods are monkey-patched per test with
``unittest.mock.patch.object``. Call order across the two active schemes is
deterministic (``sequence`` ascending), so a ``side_effect`` list lines up
one entry per scheme in the same order ``_auth_method_ssi_rest`` visits
them.
"""

from unittest.mock import patch

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError, RestAuthResult
from odoo.addons.ssi_rest_api.lib.routing import rest_route

_IR_HTTP_LOGGER = "odoo.addons.ssi_rest_api.models.ir_http"


class SsiRestAuthTestController(http.Controller):
    """Test-only scaffolding, deliberately defined here rather than in
    ``controllers/main.py`` — see ``test_rest_error_envelope.py``'s module
    docstring for the same rationale applied to error-envelope testing."""

    @rest_route(["/test-auth"], auth="ssi_rest")
    def test_auth(self, **kwargs):
        auth = request.rest_auth
        return {"uid": auth.uid, "scheme": auth.scheme}

    @rest_route(["/test-auth-restricted"], auth="ssi_rest", schemes=("dummy2",))
    def test_auth_restricted(self, **kwargs):
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestAuthMethod(HttpCase):
    def setUp(self):
        super().setUp()
        scheme_model = self.env["ssi_rest_auth_scheme"].sudo()
        self.dummy1 = scheme_model.create(
            {
                "name": "Dummy 1",
                "code": "dummy1",
                "provider_model": "mixin.rest_authenticator",
                "sequence": 10,
            }
        )
        self.dummy2 = scheme_model.create(
            {
                "name": "Dummy 2",
                "code": "dummy2",
                "provider_model": "mixin.rest_authenticator",
                "sequence": 20,
            }
        )
        self.provider_cls = self.env.registry["mixin.rest_authenticator"]

    def test_valid_credential_authenticates_and_sets_rest_auth(self):
        with (
            patch.object(
                self.provider_cls, "_rest_auth_extract", side_effect=["good-cred", None]
            ),
            patch.object(
                self.provider_cls,
                "_rest_auth_verify",
                side_effect=lambda credential: RestAuthResult(
                    uid=self.env.ref("base.user_admin").id, scheme="dummy1"
                ),
            ),
        ):
            response = self.url_open("/api/v1/test-auth")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["uid"], self.env.ref("base.user_admin").id)
        self.assertEqual(body["scheme"], "dummy1")

    @mute_logger(_IR_HTTP_LOGGER)
    def test_no_credential_is_401_with_combined_challenge(self):
        with (
            patch.object(
                self.provider_cls, "_rest_auth_extract", side_effect=[None, None]
            ),
            patch.object(
                self.provider_cls,
                "_rest_auth_challenge",
                side_effect=["Dummy1Challenge", "Dummy2Challenge"],
            ),
        ):
            response = self.url_open("/api/v1/test-auth")
        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "authentication_required")
        www_authenticate = response.headers.get("WWW-Authenticate", "")
        self.assertIn("Dummy1Challenge", www_authenticate)
        self.assertIn("Dummy2Challenge", www_authenticate)

    @mute_logger(_IR_HTTP_LOGGER)
    def test_two_credentials_at_once_is_400_multiple_credentials(self):
        with (
            patch.object(
                self.provider_cls,
                "_rest_auth_extract",
                side_effect=["cred-a", "cred-b"],
            ),
            patch.object(self.provider_cls, "_rest_auth_verify") as verify_mock,
        ):
            response = self.url_open("/api/v1/test-auth")
        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], "multiple_credentials")
        verify_mock.assert_not_called()

    @mute_logger(_IR_HTTP_LOGGER)
    def test_verify_failure_is_401_without_fallthrough(self):
        # Regression (binding): even though `dummy2` is a second active
        # scheme, it never extracts a credential for this request (its
        # `_rest_auth_extract` returns `None`) so it is never a fallthrough
        # candidate; `dummy1`'s failed verification alone must decide the
        # response.
        with (
            patch.object(
                self.provider_cls,
                "_rest_auth_extract",
                side_effect=["bad-cred", None],
            ),
            patch.object(
                self.provider_cls,
                "_rest_auth_verify",
                side_effect=RestAuthError("invalid_credential", "bad credential"),
            ) as verify_mock,
        ):
            response = self.url_open("/api/v1/test-auth")
        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "invalid_credential")
        verify_mock.assert_called_once_with("bad-cred")

    @mute_logger(_IR_HTTP_LOGGER)
    def test_unexpected_provider_exception_is_500_not_401(self):
        with (
            patch.object(
                self.provider_cls,
                "_rest_auth_extract",
                side_effect=["some-cred", None],
            ),
            patch.object(
                self.provider_cls,
                "_rest_auth_verify",
                side_effect=ZeroDivisionError("boom"),
            ),
        ):
            response = self.url_open("/api/v1/test-auth")
        self.assertEqual(response.status_code, 500)
        error = response.json()["error"]
        self.assertEqual(error["code"], "internal_error")

    @mute_logger(_IR_HTTP_LOGGER)
    def test_rest_schemes_restriction_ignores_disallowed_scheme_credential(self):
        # `dummy1` has a real credential in this request, but the endpoint
        # restricts to `schemes=("dummy2",)`: `dummy1` must never even be
        # asked to extract, and since `dummy2` finds nothing, the request
        # is unauthenticated (401), not silently accepted via `dummy1`.
        with (
            patch.object(
                self.provider_cls, "_rest_auth_extract", side_effect=[None]
            ) as extract_mock,
            patch.object(
                self.provider_cls,
                "_rest_auth_challenge",
                return_value="Dummy2Challenge",
            ),
        ):
            response = self.url_open("/api/v1/test-auth-restricted")
        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "authentication_required")
        extract_mock.assert_called_once()
