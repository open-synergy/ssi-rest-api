# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the OAuth2 authorization server (authorize,
token, revoke controllers + the ssi_rest_auth_oauth2 access-token
provider), backlog issue #20.

Python murni -- pemicu P7 (L-19: ``odoo-yaml-test``'s base class is locked
to ``TransactionCase``; a real HTTP request/response cycle -- redirects,
form-encoded POST bodies, the ``Authorization`` header, status codes --
is out of reach from YAML).

Every request below goes through ``HttpCase.url_open``/``self.opener``,
**not** a separately-instantiated ``requests.Session()``: ``self.opener``
*is* a ``requests.Session`` subclass (``Opener(requests.Session)``, Odoo
19 core ``odoo/tests/common.py``), recreated fresh in ``setUp()`` for
every test method already -- so using it already satisfies this backlog
item's own Skenario Uji note ("HttpCase, requests.Session() baru per
kasus") literally, and matches every other HTTP test in this repo
(``ssi_rest_api_auth_apikey``'s own ``test_controller_*.py``,
``ssi_rest_api_log``'s ``test_ssi_rest_request_log_dispatcher.py``): a
bare, separately-constructed ``requests.Session()`` would be rejected
outright by Odoo 19's own test harness (missing the ``test_request_key``
cookie ``Opener.request``/``HttpCase.allow_requests()`` sets
automatically), and working around that gate would add complexity with
no behavioural difference from what ``self.opener`` already gives us.

The test-only protected route below is declared with ``schemes=("oauth2",)``:
the built-in ``bearer`` scheme (``ssi_rest_api``) is also active in this
repo and reads the very same ``Authorization`` header unconditionally (it
has no shape of its own to filter on, unlike JWT), so an unrestricted
route would see *two* providers extract a credential for every access
token issued below and turn every case here into a
``400 multiple_credentials`` before the OAuth2 provider is ever
exercised. Restricting the route is the exact idiom
``ssi_rest_api_auth_jwt``'s own ``test_controller_ssi_rest_auth_jwt.py``
already established for this situation (itself following
``ssi_rest_api``'s own ``tests/test_rest_auth.py::test_auth_restricted``)
-- not a workaround invented here. This is a test-only concern: the
production ``/oauth2/authorize``/``/oauth2/token``/``/oauth2/revoke``
controllers never go through ``auth="ssi_rest"`` at all (see
``controllers/main.py``'s own module docstring), so no scheme extraction
happens there in the first place.
"""

import base64
import hashlib
from urllib.parse import parse_qsl, urlsplit

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"
_IR_HTTP_LOGGER = "odoo.addons.ssi_rest_api.models.ir_http"

_REGISTERED_REDIRECT_URI = "https://app.example.com/callback"
_PUBLIC_REDIRECT_URI = "https://public.example.com/callback"


def _s256_challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class SsiRestAuthOauth2TestController(http.Controller):
    """Test-only scaffolding -- see ssi_rest_api's
    test_rest_error_envelope.py module docstring for the rationale of
    defining it here rather than in a controllers/main.py."""

    @rest_route(["/test-auth-oauth2"], auth="ssi_rest", schemes=("oauth2",))
    def test_auth(self, **kwargs):
        auth = request.rest_auth
        return {
            "uid": auth.uid,
            "scheme": auth.scheme,
            "profile_ids": list(auth.profile_ids),
        }


@tagged("post_install", "-at_install")
class TestSsiRestAuthOauth2(HttpCase):
    def setUp(self):
        super().setUp()
        # Core's own `bearer` scheme stays active on purpose here (unlike
        # an earlier version of this test): models/ssi_rest_auth_oauth2.py's
        # own TOKEN_PREFIX shape check is what keeps the two schemes from
        # colliding, so leaving bearer active is itself part of what this
        # test class proves.
        self.resource_owner = self.env["res.users"].create(
            {
                "name": "OAuth2 Resource Owner",
                "login": "oauth2_resource_owner",
                "email": "oauth2_resource_owner@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.profile = self.env["ssi_rest_access_profile"].create(
            {"name": "OAuth2 Profile", "code": "http_oauth2_profile"}
        )
        self.confidential_client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Confidential App",
                "client_id": "confidential-app",
                "client_type": "confidential",
                "grant_types": "authorization_code,client_credentials,refresh_token",
                "profile_id": self.profile.id,
                "redirect_uri_ids": [
                    (0, 0, {"sequence": 10, "url": _REGISTERED_REDIRECT_URI})
                ],
            }
        )
        self.confidential_secret = (
            self.confidential_client._generate_new_client_secret()
        )
        self.public_client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Public App",
                "client_id": "public-app",
                "client_type": "public",
                "grant_types": "authorization_code,refresh_token",
                "profile_id": self.profile.id,
                "redirect_uri_ids": [
                    (0, 0, {"sequence": 10, "url": _PUBLIC_REDIRECT_URI})
                ],
            }
        )

    # -- helpers ----------------------------------------------------

    @staticmethod
    def _pkce_pair():
        verifier = "a" * 64
        return verifier, _s256_challenge(verifier)

    def _authorize(self, client, redirect_uri=None, code_challenge=None, **extra):
        params = {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": redirect_uri or client.redirect_uri_ids[0].url,
        }
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
        params.update(extra)
        return self.url_open(
            "/api/v1/oauth2/authorize", params=params, allow_redirects=False
        )

    @staticmethod
    def _extract_code(response):
        location = response.headers["Location"]
        query = dict(parse_qsl(urlsplit(location).query))
        return query["code"]

    def _token(self, **data):
        return self.url_open("/api/v1/oauth2/token", data=data)

    def _revoke(self, token, client_id, client_secret=None):
        data = {"token": token, "client_id": client_id}
        if client_secret is not None:
            data["client_secret"] = client_secret
        return self.url_open("/api/v1/oauth2/revoke", data=data)

    def _get_authorization_code(self, client, code_challenge):
        self.authenticate(self.resource_owner.login, "irrelevant")
        response = self._authorize(client, code_challenge=code_challenge)
        self.assertEqual(response.status_code, 302)
        return self._extract_code(response)

    # -- positive: full protocol flows -------------------------------

    def test_authorization_code_pkce_full_flow_returns_working_access_token(self):
        verifier, challenge = self._pkce_pair()
        code = self._get_authorization_code(self.confidential_client, challenge)

        token_response = self._token(
            grant_type="authorization_code",
            code=code,
            code_verifier=verifier,
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(token_response.status_code, 200)
        body = token_response.json()
        self.assertTrue(body["access_token"])
        self.assertTrue(body["refresh_token"])
        self.assertEqual(body["token_type"], "Bearer")

        probe_response = self.url_open(
            "/api/v1/test-auth-oauth2",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        self.assertEqual(probe_response.status_code, 200)
        probe_body = probe_response.json()
        self.assertEqual(probe_body["uid"], self.resource_owner.id)
        self.assertEqual(probe_body["scheme"], "oauth2")
        self.assertEqual(probe_body["profile_ids"], [self.profile.id])

    def test_client_credentials_grant_issues_access_token_without_refresh(self):
        response = self._token(
            grant_type="client_credentials",
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["access_token"])
        self.assertNotIn("refresh_token", body)

    def test_refresh_token_grant_issues_new_access_token(self):
        verifier, challenge = self._pkce_pair()
        code = self._get_authorization_code(self.confidential_client, challenge)
        first_body = self._token(
            grant_type="authorization_code",
            code=code,
            code_verifier=verifier,
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        ).json()

        refresh_response = self._token(
            grant_type="refresh_token",
            refresh_token=first_body["refresh_token"],
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(refresh_response.status_code, 200)
        second_body = refresh_response.json()
        self.assertTrue(second_body["access_token"])
        self.assertNotEqual(second_body["access_token"], first_body["access_token"])

    # -- negative -----------------------------------------------------

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_unregistered_redirect_uri_is_rejected_without_issuing_a_code(self):
        self.authenticate(self.resource_owner.login, "irrelevant")
        _verifier, challenge = self._pkce_pair()
        response = self._authorize(
            self.confidential_client,
            redirect_uri="https://not-registered.example.com/callback",
            code_challenge=challenge,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertFalse(
            self.env["ssi_rest_oauth_token"]
            .sudo()
            .search(
                [
                    ("client_id", "=", self.confidential_client.id),
                    ("token_type", "=", "code"),
                ]
            )
        )

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_redirect_uri_must_match_exactly_not_as_a_prefix(self):
        self.authenticate(self.resource_owner.login, "irrelevant")
        _verifier, challenge = self._pkce_pair()
        response = self._authorize(
            self.confidential_client,
            redirect_uri=_REGISTERED_REDIRECT_URI + "/extra",
            code_challenge=challenge,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_authorization_code_cannot_be_redeemed_twice(self):
        verifier, challenge = self._pkce_pair()
        code = self._get_authorization_code(self.confidential_client, challenge)
        first = self._token(
            grant_type="authorization_code",
            code=code,
            code_verifier=verifier,
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(first.status_code, 200)

        second = self._token(
            grant_type="authorization_code",
            code=code,
            code_verifier=verifier,
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error"]["code"], "invalid_grant")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_pkce_code_verifier_mismatch_is_rejected(self):
        _verifier, challenge = self._pkce_pair()
        code = self._get_authorization_code(self.confidential_client, challenge)
        response = self._token(
            grant_type="authorization_code",
            code=code,
            code_verifier="totally-wrong-verifier",
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_grant")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_client_credentials_with_wrong_secret_is_rejected(self):
        response = self._token(
            grant_type="client_credentials",
            client_id=self.confidential_client.client_id,
            client_secret="wrong-secret",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_client")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_revoked_access_token_is_401_without_fallthrough(self):
        token_body = self._token(
            grant_type="client_credentials",
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        ).json()
        access_token = token_body["access_token"]

        revoke_response = self._revoke(
            access_token,
            self.confidential_client.client_id,
            self.confidential_secret,
        )
        self.assertEqual(revoke_response.status_code, 200)

        probe_response = self.url_open(
            "/api/v1/test-auth-oauth2",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(probe_response.status_code, 401)
        self.assertEqual(probe_response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_expired_access_token_is_401(self):
        token_body = self._token(
            grant_type="client_credentials",
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
        ).json()
        record = (
            self.env["ssi_rest_oauth_token"]
            .sudo()
            .search(
                [
                    ("client_id", "=", self.confidential_client.id),
                    ("token_type", "=", "access"),
                ],
                order="id desc",
                limit=1,
            )
        )
        record.write({"expiration_date": "2000-01-01 00:00:00"})

        probe_response = self.url_open(
            "/api/v1/test-auth-oauth2",
            headers={"Authorization": f"Bearer {token_body['access_token']}"},
        )
        self.assertEqual(probe_response.status_code, 401)
        self.assertEqual(probe_response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_password_grant_type_is_rejected(self):
        response = self._token(
            grant_type="password",
            client_id=self.confidential_client.client_id,
            client_secret=self.confidential_secret,
            username="someone",
            password="secret",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unsupported_grant_type")

    @mute_logger(_DISPATCHER_LOGGER, _IR_HTTP_LOGGER)
    def test_public_client_without_pkce_is_rejected_at_authorize(self):
        self.authenticate(self.resource_owner.login, "irrelevant")
        response = self._authorize(self.public_client)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
