# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the JWT bearer provider
(``models/ssi_rest_auth_jwt.py``), backlog issue #19.

Python murni -- pemicu P7 (L-19: ``odoo-yaml-test``'s base class is locked
to ``TransactionCase``, a real HTTP request/response cycle -- including
mocking the JWKS endpoint's network fetch and counting how many times it
was called -- is out of reach) and P6 (L-15: no mock/patch from YAML,
needed here to fake the network call ``jwt.PyJWKClient.fetch_data()``
makes so RS256 tests never touch the network).

Every test route below is declared with ``schemes=("jwt",)``: the built-in
``bearer`` scheme (``ssi_rest_api``) is also active in this repo and reads
the very same ``Authorization`` header unconditionally, so an unrestricted
route would see *two* providers extract a credential for the same request
and turn every case here into a ``400 multiple_credentials`` before the
JWT provider is ever exercised. Restricting the route is the exact idiom
``ssi_rest_api``'s own ``tests/test_rest_auth.py::test_auth_restricted``
already established for this situation -- not a workaround invented here.
"""

import base64
import json
import time
from collections import Counter
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"
_IR_HTTP_LOGGER = "odoo.addons.ssi_rest_api.models.ir_http"


class SsiRestAuthJwtTestController(http.Controller):
    """Test-only scaffolding -- see ``ssi_rest_api``'s own
    ``test_rest_error_envelope.py`` module docstring for the rationale of
    defining it here rather than in a ``controllers/main.py``."""

    @rest_route(["/test-auth-jwt"], auth="ssi_rest", schemes=("jwt",))
    def test_auth(self, **kwargs):
        auth = request.rest_auth
        return {
            "uid": auth.uid,
            "scheme": auth.scheme,
            "profile_ids": list(auth.profile_ids),
        }


def _bearer_header(token):
    return {"Authorization": f"Bearer {token}"}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unverified_none_alg_token(payload):
    """Build a syntactically well-formed but entirely unsigned JWT (header
    ``alg: none``) by hand -- ``jwt.encode`` itself refuses to sign with
    ``none``, so this is the only way to prove the issuer's algorithm
    whitelist (not merely the signature check) is what rejects it.
    """
    header_segment = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload_segment = _b64url(json.dumps(payload).encode())
    return f"{header_segment}.{payload_segment}.forged"


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_key, private_pem


def _jwk_for(public_key, kid):
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return jwk


class _FakeJwksHttpResponse:
    """Minimal stand-in for the context manager
    ``urllib.request.urlopen()`` normally returns, so
    ``PyJWKClient.fetch_data()`` itself runs completely unmocked --
    including populating its own Tier-1 JWK Set cache -- and only the
    actual network round-trip is faked. Mocking ``fetch_data`` directly
    would skip that cache population and defeat
    ``test_jwks_fetched_once_within_ttl_across_requests`` below (every
    call would look like a cache miss)."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):  # pylint: disable=method-required-super
        # File-like `.read()` for `json.load()` -- not an Odoo ORM
        # `read()` override, so there is no `super()` to call.
        return self._body


@tagged("post_install", "-at_install")
class TestSsiRestAuthJwt(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "SSI REST JWT User",
                "login": "ssi_rest_jwt_user@example.com",
                "email": "ssi_rest_jwt_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.profile = self.env["ssi_rest_access_profile"].create(
            {"name": "Http JWT Profile", "code": "http_jwt_profile"}
        )

        # Fakes the one network round-trip `PyJWKClient.fetch_data()`
        # makes (`urllib.request.urlopen`), keyed by JWKS URL, so RS256
        # tests never touch the network and so
        # `test_jwks_fetched_once_within_ttl_across_requests` below can
        # count real calls -- see module docstring (P6) and
        # `_FakeJwksHttpResponse` above for why the network layer is
        # faked instead of `fetch_data` itself.
        self._jwks_by_url = {}
        self._fetch_calls = Counter()

        def _fake_urlopen(req, timeout=None, context=None):
            url = req.full_url
            self._fetch_calls[url] += 1
            return _FakeJwksHttpResponse(self._jwks_by_url[url])

        patcher = patch("urllib.request.urlopen", side_effect=_fake_urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- fixtures ---------------------------------------------------------

    def _create_rs256_issuer(self, *, iss, aud="api://ssi-rest", **extra_values):
        private_key, private_pem = _generate_rsa_keypair()
        kid = f"kid-{iss}"
        host = iss.split("//")[-1]
        jwks_url = f"https://{host}/.well-known/jwks.json"
        self._jwks_by_url[jwks_url] = {
            "keys": [_jwk_for(private_key.public_key(), kid)]
        }
        values = {
            "name": f"Issuer {iss}",
            "issuer": iss,
            "audience": aud,
            "algorithm": "RS256",
            "jwks_url": jwks_url,
            "user_claim": "sub",
            "user_match_field": "login",
        }
        values.update(extra_values)
        issuer = self.env["ssi_rest_jwt_issuer"].create(values)
        return issuer, private_pem, kid

    def _create_hs256_issuer(
        self, *, iss, aud="api://ssi-rest", secret="s3cr3t", **extra_values
    ):
        values = {
            "name": f"Issuer {iss}",
            "issuer": iss,
            "audience": aud,
            "algorithm": "HS256",
            "shared_secret": secret,
            "user_claim": "sub",
            "user_match_field": "login",
        }
        values.update(extra_values)
        return self.env["ssi_rest_jwt_issuer"].create(values)

    @staticmethod
    def _encode_rs256(private_pem, kid, payload):
        return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": kid})

    @staticmethod
    def _payload(issuer, sub, exp_delta=3600, nbf_delta=None):
        now = int(time.time())
        payload = {
            "iss": issuer.issuer,
            "aud": issuer.audience,
            "sub": sub,
            "iat": now,
            "exp": now + exp_delta,
        }
        if nbf_delta is not None:
            payload["nbf"] = now + nbf_delta
        return payload

    # -- positive scenarios -------------------------------------------------

    def test_valid_rs256_token_authenticates_as_matched_user(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-positive.example.com",
            profile_id=self.profile.id,
        )
        token = self._encode_rs256(
            private_pem, kid, self._payload(issuer, sub=self.test_user.login)
        )
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["uid"], self.test_user.id)
        self.assertEqual(body["scheme"], "jwt")
        self.assertEqual(body["profile_ids"], [self.profile.id])

    def test_two_issuers_active_simultaneously_no_exclusivity(self):
        # Regression (binding Keputusan Desain): both issuers must be
        # usable while active at once, and deactivating one must never
        # cascade to the other -- proof that ssi_backend_mixin's "one
        # active backend per company" semantic was not (re)introduced.
        # See test_ssi_rest_jwt_issuer.py::test_model_has_no_backend_
        # mixin_semantics for the complementary structural proof that the
        # mixin providing that cascade isn't even inherited.
        issuer_a, pem_a, kid_a = self._create_rs256_issuer(
            iss="https://issuer-a.example.com"
        )
        issuer_b, pem_b, kid_b = self._create_rs256_issuer(
            iss="https://issuer-b.example.com"
        )
        token_a = self._encode_rs256(
            pem_a, kid_a, self._payload(issuer_a, sub=self.test_user.login)
        )
        token_b = self._encode_rs256(
            pem_b, kid_b, self._payload(issuer_b, sub=self.test_user.login)
        )

        response_a = self.url_open(
            "/api/v1/test-auth-jwt", headers=_bearer_header(token_a)
        )
        response_b = self.url_open(
            "/api/v1/test-auth-jwt", headers=_bearer_header(token_b)
        )
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)

        issuer_a.active = False
        self.assertTrue(issuer_b.active)
        response_b_again = self.url_open(
            "/api/v1/test-auth-jwt", headers=_bearer_header(token_b)
        )
        self.assertEqual(response_b_again.status_code, 200)

    def test_token_expired_within_leeway_is_accepted(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-leeway.example.com", leeway=30
        )
        payload = self._payload(issuer, sub=self.test_user.login, exp_delta=-10)
        token = self._encode_rs256(private_pem, kid, payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 200)

    def test_jwks_fetched_once_within_ttl_across_requests(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-cache.example.com"
        )
        token = self._encode_rs256(
            private_pem, kid, self._payload(issuer, sub=self.test_user.login)
        )
        response_1 = self.url_open(
            "/api/v1/test-auth-jwt", headers=_bearer_header(token)
        )
        response_2 = self.url_open(
            "/api/v1/test-auth-jwt", headers=_bearer_header(token)
        )
        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 200)
        self.assertEqual(self._fetch_calls[issuer.jwks_url], 1)

    # -- negative scenarios --------------------------------------------------

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_invalid_signature_is_401_without_fallthrough(self):
        # No other provider is left to fall through to on this route
        # (schemes=("jwt",)) -- this provider's own verification failure
        # alone decides the response.
        issuer, _private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-badsig.example.com"
        )
        _other_key, other_pem = _generate_rsa_keypair()
        token = self._encode_rs256(
            other_pem, kid, self._payload(issuer, sub=self.test_user.login)
        )
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_issuer_claim_mismatch_is_401(self):
        self._create_rs256_issuer(iss="https://issuer-real.example.com")
        # No issuer record has this iss, so `_rest_auth_verify` never even
        # picks a candidate to verify against.
        private_key, private_pem = _generate_rsa_keypair()
        kid = "kid-unregistered"
        now = int(time.time())
        payload = {
            "iss": "https://issuer-attacker.example.com",
            "aud": "api://ssi-rest",
            "sub": self.test_user.login,
            "iat": now,
            "exp": now + 3600,
        }
        token = self._encode_rs256(private_pem, kid, payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_audience_mismatch_is_401(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-aud.example.com"
        )
        payload = self._payload(issuer, sub=self.test_user.login)
        payload["aud"] = "api://someone-else"
        token = self._encode_rs256(private_pem, kid, payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_token_expired_beyond_leeway_is_401(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-expired.example.com", leeway=5
        )
        payload = self._payload(issuer, sub=self.test_user.login, exp_delta=-30)
        token = self._encode_rs256(private_pem, kid, payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_token_not_yet_valid_beyond_leeway_is_401(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-nbf.example.com", leeway=5
        )
        payload = self._payload(issuer, sub=self.test_user.login, nbf_delta=60)
        token = self._encode_rs256(private_pem, kid, payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_algorithm_none_is_rejected(self):
        issuer = self._create_hs256_issuer(iss="https://issuer-none.example.com")
        payload = self._payload(issuer, sub=self.test_user.login)
        token = _unverified_none_alg_token(payload)
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_IR_HTTP_LOGGER, _DISPATCHER_LOGGER)
    def test_unmatched_user_claim_is_401_and_creates_no_user(self):
        issuer, private_pem, kid = self._create_rs256_issuer(
            iss="https://issuer-unknown-user.example.com"
        )
        payload = self._payload(issuer, sub="no-such-login@example.com")
        token = self._encode_rs256(private_pem, kid, payload)
        user_count_before = self.env["res.users"].sudo().search_count([])
        response = self.url_open("/api/v1/test-auth-jwt", headers=_bearer_header(token))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")
        user_count_after = self.env["res.users"].sudo().search_count([])
        self.assertEqual(user_count_after, user_count_before)
