# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""External JWT bearer provider -- ``mixin.rest_authenticator``
implementation for ``ssi_rest_jwt_issuer`` (backlog issue #19).

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring).

Reads the standard ``Authorization: Bearer <token>`` header -- the header
every OIDC/OAuth2 client (Authentik, Keycloak, Entra, ...) already sends a
JWT on -- rather than a dedicated header the way ``ssi_rest_auth_apikey``
reads ``X-Api-Key``. This is a deliberate difference from that module, not
an oversight: standards compliance here matters more than avoiding the
built-in ``ssi_rest_auth_bearer`` scheme's overlap on the same header (see
``_looks_like_jwt`` below for how the two stay distinguishable in
practice, and the module docstring note further down for the one case
where they cannot).
"""

import base64
import binascii
import json
import re

import jwt
from jwt import PyJWKClientError

from odoo import models
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError, RestAuthResult

from ..lib.jwks_cache import get_client as _get_jwks_client
from .ssi_rest_jwt_issuer import HMAC_ALGORITHM_PREFIX

_AUTH_HEADER_PREFIX = "Bearer "
_INVALID_CREDENTIAL_MESSAGE = "Invalid or expired token."
_JWT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _b64url_decode(segment):
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _looks_like_jwt(token):
    """Whether ``token`` has the compact JWS shape (RFC 7515 SS3.1) a real
    JWT would have: three dot-separated, base64url segments whose first
    segment decodes to a JSON object carrying an ``alg`` key.

    Deliberately does **not** verify anything -- only shape. This is what
    keeps ``_rest_auth_extract`` cheap and DB-free (the binding contract
    every ``mixin.rest_authenticator._rest_auth_extract`` must honour):
    it lets this provider claim the credential only when the bearer token
    on this request actually looks like a JWT, so an opaque, non-JWT
    bearer token (e.g. a core ``res.users.apikeys`` value handled by
    ``ssi_rest_auth_bearer``) is correctly left for that other scheme
    instead of also being claimed here -- which would otherwise turn
    every such request into a ``400 multiple_credentials`` (see
    ``models/ir_http.py::_auth_method_ssi_rest`` in ``ssi_rest_api``).

    Note this cannot go the other way: nothing stops a genuine JWT from
    also being accepted, shape-wise, as "any non-empty token" by the
    built-in ``bearer`` scheme's own indiscriminate
    ``_rest_auth_extract`` (``ssi_rest_auth_bearer.py`` in
    ``ssi_rest_api``). A deployment that installs this module to accept
    JWTs over ``Authorization: Bearer`` and does not use the core
    ``res.users.apikeys``-backed ``bearer`` scheme at all should simply
    deactivate that scheme's ``ssi_rest_auth_scheme`` record to avoid the
    resulting ambiguity -- an operational configuration step, not a code
    path this provider can resolve unilaterally, since claiming to
    silently "win" over another already-extracted scheme is exactly the
    guessing behaviour ``_auth_method_ssi_rest`` refuses to do.
    """
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    if not all(_JWT_SEGMENT_RE.match(part) for part in parts):
        return False
    try:
        header = json.loads(_b64url_decode(parts[0]))
    except (ValueError, TypeError, binascii.Error):
        return False
    return isinstance(header, dict) and "alg" in header


class SsiRestAuthJwt(models.AbstractModel):
    _name = "ssi_rest_auth_jwt"
    _inherit = ["mixin.rest_authenticator"]
    _description = "REST Authentication Provider - JWT Bearer"

    def _rest_auth_code(self):
        return "jwt"

    def _rest_auth_extract(self):
        header = request.httprequest.headers.get("Authorization")
        if not header or not header.startswith(_AUTH_HEADER_PREFIX):
            return None
        token = header[len(_AUTH_HEADER_PREFIX) :].strip()
        if not token or not _looks_like_jwt(token):
            return None
        return token

    def _rest_auth_verify(self, credential):
        issuer_model = self.env["ssi_rest_jwt_issuer"].sudo()
        claims = self._peek_unverified_claims(credential)
        candidates = issuer_model.search([("issuer", "=", claims.get("iss"))])
        if not candidates:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        for issuer in candidates:
            try:
                return self._verify_against_issuer(issuer, credential)
            except RestAuthError:
                continue
        raise RestAuthError(
            "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
        )

    def _rest_auth_challenge(self):
        return 'Bearer realm="ssi_rest"'

    def _peek_unverified_claims(self, token):
        """Read ``token``'s claims **without verifying anything** -- used
        only to select which ``ssi_rest_jwt_issuer`` candidate(s) to
        attempt full verification against below. Never a security
        decision by itself: :meth:`_verify_against_issuer` re-validates
        signature, iss, aud, exp and nbf from scratch against the
        selected issuer's own configuration.
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except jwt.exceptions.PyJWTError as exc:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            ) from exc

    def _verify_against_issuer(self, issuer, token):
        """Fully verify ``token`` against ``issuer``: signature, iss, aud,
        exp/nbf (with leeway), algorithm whitelist -- then map its
        user_claim to a res.users record. Raises RestAuthError on any
        failure; never returns falsy (mixin.rest_authenticator contract).
        """
        signing_key = self._resolve_signing_key(issuer, token)
        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=[issuer.algorithm],
                audience=issuer.audience,
                issuer=issuer.issuer,
                leeway=issuer.leeway or 0,
                options={"require": ["exp"]},
            )
        except jwt.exceptions.PyJWTError as exc:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            ) from exc
        return self._resolve_user_result(issuer, claims)

    def _resolve_signing_key(self, issuer, token):
        """Return the key material ``jwt.decode`` needs for
        ``issuer.algorithm``: the shared secret itself for HMAC (HS*)
        algorithms, or the matching public key resolved (and TTL-cached,
        see lib/jwks_cache.py) from ``issuer.jwks_url`` for asymmetric
        (RS*/ES*) ones. A JWKS fetch failure is a verification failure
        (401), never a 500 -- binding Keputusan Desain.
        """
        if issuer.algorithm.startswith(HMAC_ALGORITHM_PREFIX):
            return issuer.shared_secret
        client = _get_jwks_client(issuer.id, issuer.jwks_url)
        try:
            return client.get_signing_key_from_jwt(token).key
        except PyJWKClientError as exc:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            ) from exc

    def _resolve_user_result(self, issuer, claims):
        claim_value = claims.get(issuer.user_claim)
        if not claim_value:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        # sudo(): this runs before the request's identity is known at all
        # (same rationale ssi_rest_auth_apikey/basic/bearer's own
        # credential lookups already document) -- there is no caller ACL
        # to respect yet. Never creates a user (binding Keputusan Desain:
        # "User yang tidak ditemukan = 401, BUKAN membuat user baru
        # otomatis").
        user = (
            self.env["res.users"]
            .sudo()
            .search([(issuer.user_match_field, "=", claim_value)], limit=1)
        )
        if not user:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        profile_ids = (issuer.profile_id.id,) if issuer.profile_id else ()
        return RestAuthResult(
            uid=user.id,
            scheme=self._rest_auth_code(),
            profile_ids=profile_ids,
        )
