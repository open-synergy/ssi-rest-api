# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the scoped API key provider
(``models/ssi_rest_auth_apikey.py``), backlog issue #18.

Python murni -- pemicu P7 (L-19: ``odoo-yaml-test``'s base class is locked
to ``TransactionCase``, a real HTTP request/response cycle -- including
inspecting response headers and driving the RO/RW cursor retry machinery
-- is out of reach).
"""

import datetime

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"
_IR_HTTP_LOGGER = "odoo.addons.ssi_rest_api.models.ir_http"

#: Populated (in-process, not persisted) by the readonly test below, to
#: prove the endpoint runs exactly once under readonly=True when
#: authenticated via apikey -- mirrors ssi_rest_api's own
#: test_rest_auth_basic_bearer.py::_READONLY_ENDPOINT_CALLS.
_READONLY_ENDPOINT_CALLS = []


class SsiRestAuthApikeyTestController(http.Controller):
    """Test-only scaffolding -- see ssi_rest_api's
    test_rest_error_envelope.py module docstring for the rationale of
    defining it here rather than in a controllers/main.py."""

    @rest_route(["/test-auth-apikey"], auth="ssi_rest")
    def test_auth(self, **kwargs):
        auth = request.rest_auth
        return {
            "uid": auth.uid,
            "scheme": auth.scheme,
            "profile_ids": list(auth.profile_ids),
        }

    @rest_route(["/test-auth-apikey-readonly"], auth="ssi_rest", readonly=True)
    def test_auth_readonly(self, **kwargs):
        _READONLY_ENDPOINT_CALLS.append(1)
        return {"uid": request.rest_auth.uid}


def _apikey_header(raw_key):
    return {"X-Api-Key": raw_key}


@tagged("post_install", "-at_install")
class TestSsiRestAuthApikey(HttpCase):
    def setUp(self):
        super().setUp()
        _READONLY_ENDPOINT_CALLS.clear()
        self.test_user = self.env["res.users"].create(
            {
                "name": "SSI REST Apikey User",
                "login": "ssi_rest_apikey_user@example.com",
                "email": "ssi_rest_apikey_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.profile_a = self.env["ssi_rest_access_profile"].create(
            {"name": "Http Profile A", "code": "http_apikey_profile_a"}
        )
        self.profile_b = self.env["ssi_rest_access_profile"].create(
            {"name": "Http Profile B", "code": "http_apikey_profile_b"}
        )
        self.key_a = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key A",
                "user_id": self.test_user.id,
                "profile_id": self.profile_a.id,
            }
        )
        self.raw_key_a = self.key_a._generate_new_key()
        self.key_b = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key B",
                "user_id": self.test_user.id,
                "profile_id": self.profile_b.id,
            }
        )
        self.raw_key_b = self.key_b._generate_new_key()

    def test_valid_key_authenticates_with_its_own_profile(self):
        response = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(self.raw_key_a)
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["uid"], self.test_user.id)
        self.assertEqual(body["scheme"], "apikey")
        self.assertEqual(body["profile_ids"], [self.profile_a.id])

    def test_two_keys_same_user_different_profile_are_independent(self):
        response_a = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(self.raw_key_a)
        )
        response_b = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(self.raw_key_b)
        )
        profile_ids_a = response_a.json()["profile_ids"]
        profile_ids_b = response_b.json()["profile_ids"]
        self.assertEqual(profile_ids_a, [self.profile_a.id])
        self.assertEqual(profile_ids_b, [self.profile_b.id])
        self.assertNotEqual(profile_ids_a, profile_ids_b)

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_no_api_key_header_is_401(self):
        # `_rest_auth_extract()` must return `None` (never raise/query the
        # DB) when the request carries no X-Api-Key header at all --
        # asserted indirectly through a real request, since
        # `_rest_auth_extract` reads the process-global `odoo.http.request`
        # proxy and is only bound during an actual served request (same
        # rationale as ssi_rest_api's own
        # test_rest_auth_basic_bearer.py::test_no_authorization_header_is_401_not_500).
        response = self.url_open("/api/v1/test-auth-apikey")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_wrong_key_is_401_without_fallthrough(self):
        # Regression (binding, Keputusan Desain): the basic provider is
        # also active in this repo, but never extracts anything here (no
        # Authorization header sent), so apikey's own failed verification
        # alone decides the response -- there is no second extracted
        # provider left to fall through to.
        response = self.url_open(
            "/api/v1/test-auth-apikey",
            headers=_apikey_header("sak_not-a-real-key"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_expired_key_is_401(self):
        expired_key = self.env["ssi_rest_api_key"].create(
            {
                "name": "Expired",
                "user_id": self.test_user.id,
                "profile_id": self.profile_a.id,
                "expiration_date": datetime.datetime.now() - datetime.timedelta(days=1),
            }
        )
        raw_key = expired_key._generate_new_key()
        response = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(raw_key)
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_inactive_key_is_401(self):
        inactive_key = self.env["ssi_rest_api_key"].create(
            {
                "name": "Inactive",
                "user_id": self.test_user.id,
                "profile_id": self.profile_a.id,
            }
        )
        raw_key = inactive_key._generate_new_key()
        inactive_key.active = False
        response = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(raw_key)
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_apikey_and_bearer_together_is_400_multiple_credentials(self):
        # Regression: apikey reads a dedicated X-Api-Key header specifically
        # so it never collides with Authorization-header schemes, but two
        # DIFFERENT schemes both extracting a credential for the same
        # request must still be rejected as ambiguous, exactly like two
        # Authorization-header schemes would be.
        rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="rpc key", expiration_date=None)
        )
        headers = {
            "X-Api-Key": self.raw_key_a,
            "Authorization": f"Bearer {rpc_key}",
        }
        response = self.url_open("/api/v1/test-auth-apikey", headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "multiple_credentials")

    def test_last_used_date_is_updated_after_successful_auth(self):
        self.assertFalse(self.key_a.last_used_date)
        response = self.url_open(
            "/api/v1/test-auth-apikey", headers=_apikey_header(self.raw_key_a)
        )
        self.assertEqual(response.status_code, 200)
        self.key_a.invalidate_recordset()
        self.assertTrue(self.key_a.last_used_date)

    def test_readonly_route_executes_endpoint_once(self):
        # Regression (binding): last_used_date must never be written
        # through the request's own env.cr -- if it were, this
        # readonly=True route would force Odoo's RO->RW cursor retry and
        # run the endpoint (and therefore append to
        # _READONLY_ENDPOINT_CALLS) twice.
        response = self.url_open(
            "/api/v1/test-auth-apikey-readonly",
            headers=_apikey_header(self.raw_key_a),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(_READONLY_ENDPOINT_CALLS), 1)
