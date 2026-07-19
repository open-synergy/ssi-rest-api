# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OAuth2 authorization server endpoints (backlog issue #20): authorize,
token, and revoke.

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring).

Built on ``rest_route`` (``ssi_rest_api/lib/routing.py``) like every other
``ssi_rest`` endpoint, for the same JSON-body/query-string/form parsing and
uniform ``{"error": {...}}`` envelope on failure (``lib/errors.py``,
``lib/dispatcher.py``) -- ``RestAuthError`` is used throughout this
controller for every OAuth2 protocol-level rejection (``invalid_request``,
``invalid_client``, ``invalid_grant``, ``unauthorized_client``,
``unsupported_grant_type``), not only for authentication failures, the
same way ``ir_http.py``'s own ``X-Odoo-Company`` validation already does.
This is a deliberate simplification of RFC 6749's own error shape (which
would redirect ``/authorize`` errors back to ``redirect_uri`` with an
``error=`` query parameter in most cases): none of this backlog item's
Kriteria Penerimaan or Skenario Uji distinguish between a JSON error body
and a redirect-carried error, so the simpler, already-established envelope
is reused unconditionally, including for ``/authorize``.

Three endpoints, three different ``auth``:

- ``authorize`` (``auth="user"``): the resource owner's own browser
  session (Odoo login), never a bearer credential -- there is no access
  token yet at this point in the flow.
- ``token``/``revoke`` (``auth="public"``): the *client* authenticates
  itself explicitly, inside the endpoint body below (``client_id`` +
  ``client_secret`` or PKCE), never through ``auth="ssi_rest"`` -- a
  client exchanging a code for its first token cannot possibly already
  hold one.
"""

import base64
import binascii
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from odoo import http
from odoo.http import Response, request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.routing import rest_route

from ..models.ssi_rest_oauth_token import AUTH_CODE_LIFETIME_SECONDS

_GRANT_TYPES = ("authorization_code", "client_credentials", "refresh_token")


def _append_query(url, params):
    """Return ``url`` with ``params`` merged into its existing query
    string (params win on key collision), preserving everything else.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({key: value for key, value in params.items() if value is not None})
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


class SsiRestOauth2Controller(http.Controller):
    @rest_route(["/oauth2/authorize"], auth="user", methods=["GET"])
    def authorize(self, **kw):
        env = request.env
        client_id = kw.get("client_id")
        redirect_uri = kw.get("redirect_uri")
        if not client_id or not redirect_uri:
            raise RestAuthError(
                "invalid_request",
                "client_id and redirect_uri are required.",
                status=400,
            )

        client = (
            env["ssi_rest_oauth_client"]
            .sudo()
            .search([("client_id", "=", client_id), ("active", "=", True)], limit=1)
        )
        if not client:
            raise RestAuthError(
                "invalid_client", "Unknown or inactive client_id.", status=400
            )
        # Checked before every other validation below: once client_id and
        # redirect_uri are both confirmed valid together, every later
        # rejection in this method is still a plain JSON error (see module
        # docstring) rather than a redirect -- an *unregistered*
        # redirect_uri specifically must never be redirected to at all
        # (binding Keputusan Desain: "tidak menerbitkan kode").
        if not client._has_redirect_uri(redirect_uri):
            raise RestAuthError(
                "invalid_request",
                "redirect_uri is not registered for this client.",
                status=400,
            )
        if kw.get("response_type") != "code":
            raise RestAuthError(
                "unsupported_response_type",
                "response_type must be 'code'.",
                status=400,
            )
        if not client._allows_grant("authorization_code"):
            raise RestAuthError(
                "unauthorized_client",
                "This client is not allowed to use the authorization_code grant.",
                status=400,
            )
        code_challenge = kw.get("code_challenge")
        code_challenge_method = kw.get("code_challenge_method") or "S256"
        # PKCE is mandatory for every client type here (binding Keputusan
        # Desain lists the grant as "authorization_code (dengan PKCE)"
        # without qualification, and separately requires it for public
        # clients specifically -- requiring it universally is the
        # simplest reading that satisfies both, and matches OAuth 2.1's
        # own direction).
        if not code_challenge:
            raise RestAuthError(
                "invalid_request", "code_challenge is required.", status=400
            )
        if code_challenge_method not in ("S256", "plain"):
            raise RestAuthError(
                "invalid_request",
                "code_challenge_method must be S256 or plain.",
                status=400,
            )

        token_model = env["ssi_rest_oauth_token"]
        _record, raw_code = token_model._issue(
            client,
            env.user,
            "code",
            kw.get("scope"),
            AUTH_CODE_LIFETIME_SECONDS,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
        target = _append_query(
            redirect_uri, {"code": raw_code, "state": kw.get("state")}
        )
        return Response(status=302, headers=[("Location", target)])

    @rest_route(["/oauth2/token"], auth="public", methods=["POST"])
    def token(self, **kw):
        env = request.env
        grant_type = kw.get("grant_type")
        if grant_type not in _GRANT_TYPES:
            raise RestAuthError(
                "unsupported_grant_type", "Unsupported grant_type.", status=400
            )
        client_id, client_secret = self._extract_client_credentials(kw)
        if not client_id:
            raise RestAuthError("invalid_client", "client_id is required.", status=401)
        client = (
            env["ssi_rest_oauth_client"]
            .sudo()
            .search([("client_id", "=", client_id), ("active", "=", True)], limit=1)
        )
        if not client:
            raise RestAuthError(
                "invalid_client", "Unknown or inactive client_id.", status=401
            )
        if not client._allows_grant(grant_type):
            raise RestAuthError(
                "unauthorized_client",
                "This client is not allowed to use this grant_type.",
                status=400,
            )

        if grant_type == "client_credentials":
            return self._token_client_credentials(env, client, client_secret, kw)
        self._check_client_secret_if_confidential(client, client_secret)
        if grant_type == "authorization_code":
            return self._token_authorization_code(env, client, kw)
        return self._token_refresh_token(env, client, kw)

    @rest_route(["/oauth2/revoke"], auth="public", methods=["POST"])
    def revoke(self, **kw):
        env = request.env
        raw_token = kw.get("token")
        if not raw_token:
            raise RestAuthError("invalid_request", "token is required.", status=400)
        client_id, client_secret = self._extract_client_credentials(kw)
        if not client_id:
            raise RestAuthError("invalid_client", "client_id is required.", status=401)
        client = (
            env["ssi_rest_oauth_client"]
            .sudo()
            .search([("client_id", "=", client_id), ("active", "=", True)], limit=1)
        )
        if not client:
            raise RestAuthError(
                "invalid_client", "Unknown or inactive client_id.", status=401
            )
        self._check_client_secret_if_confidential(client, client_secret)

        # RFC 7009 SS2.2: revocation is idempotent -- a token unknown to
        # this client (already revoked, expired and purged, or simply
        # never existed) is not an error, the endpoint must not disclose
        # whether it ever existed.
        record = (
            env["ssi_rest_oauth_token"].sudo()._lookup_for_revoke(raw_token, client)
        )
        if record:
            record.write({"revoked": True})
        return {}

    # -- grant handlers -----------------------------------------------

    def _token_authorization_code(self, env, client, kw):
        code = kw.get("code")
        code_verifier = kw.get("code_verifier")
        if not code:
            raise RestAuthError("invalid_request", "code is required.", status=400)
        token_model = env["ssi_rest_oauth_token"]
        code_record = token_model.sudo()._lookup(code, "code", client=client)
        if not code_record:
            raise RestAuthError(
                "invalid_grant",
                "Unknown, expired, or already used authorization code.",
                status=400,
            )
        if not code_record._check_pkce(code_verifier):
            raise RestAuthError(
                "invalid_grant",
                "code_verifier does not match code_challenge.",
                status=400,
            )
        # One-time use: consumed immediately, so a second exchange attempt
        # of the same code is rejected above by _lookup (revoked rows are
        # never returned as candidates).
        code_record.sudo().write({"revoked": True})

        _access_record, raw_access = token_model._issue(
            client,
            code_record.user_id,
            "access",
            code_record.scope,
            client.access_token_lifetime,
        )
        _refresh_record, raw_refresh = token_model._issue(
            client,
            code_record.user_id,
            "refresh",
            code_record.scope,
            client.refresh_token_lifetime,
        )
        return self._token_response(
            client, raw_access, code_record.scope, refresh_token=raw_refresh
        )

    def _token_client_credentials(self, env, client, client_secret, kw):
        if client.client_type != "confidential":
            raise RestAuthError(
                "unauthorized_client",
                "client_credentials requires a confidential client.",
                status=400,
            )
        if not client._check_client_secret(client_secret):
            raise RestAuthError(
                "invalid_client", "Invalid client credentials.", status=401
            )
        scope = kw.get("scope") or " ".join(client.scope_ids.mapped("code"))
        token_model = env["ssi_rest_oauth_token"]
        # No resource owner for this grant (RFC 6749 SS4.4): user=None ->
        # ssi_rest_oauth_token.user_id stays empty, and a request
        # authenticated with the resulting access token later runs as
        # base's own public user (see models/ssi_rest_auth_oauth2.py).
        _access_record, raw_access = token_model._issue(
            client, None, "access", scope, client.access_token_lifetime
        )
        # No refresh token for this grant (binding Kriteria Penerimaan:
        # "access token terbit tanpa refresh token").
        return self._token_response(client, raw_access, scope, refresh_token=None)

    def _token_refresh_token(self, env, client, kw):
        raw_refresh = kw.get("refresh_token")
        if not raw_refresh:
            raise RestAuthError(
                "invalid_request", "refresh_token is required.", status=400
            )
        token_model = env["ssi_rest_oauth_token"]
        refresh_record = token_model.sudo()._lookup(
            raw_refresh, "refresh", client=client
        )
        if not refresh_record:
            raise RestAuthError(
                "invalid_grant",
                "Unknown, expired, or revoked refresh token.",
                status=400,
            )
        _access_record, raw_access = token_model._issue(
            client,
            refresh_record.user_id,
            "access",
            refresh_record.scope,
            client.access_token_lifetime,
        )
        # The presented refresh token is neither rotated nor revoked here:
        # this backlog item's Kriteria Penerimaan only requires "access
        # token baru terbit", never a new refresh token nor rotation of
        # the old one.
        return self._token_response(
            client, raw_access, refresh_record.scope, refresh_token=None
        )

    # -- shared helpers -------------------------------------------------

    @staticmethod
    def _token_response(client, access_token, scope, refresh_token=None):
        body = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": client.access_token_lifetime,
            "scope": scope or "",
        }
        if refresh_token:
            body["refresh_token"] = refresh_token
        return body

    @staticmethod
    def _check_client_secret_if_confidential(client, client_secret):
        if client.client_type != "confidential":
            return
        if not client._check_client_secret(client_secret):
            raise RestAuthError(
                "invalid_client", "Invalid client credentials.", status=401
            )

    @staticmethod
    def _extract_client_credentials(kw):
        """Return ``(client_id, client_secret)`` from either HTTP Basic
        auth (RFC 6749 SS2.3.1, preferred) or plain body/query parameters
        (fallback, primarily for public clients and tests using a plain
        HTTP client).
        """
        header = request.httprequest.headers.get("Authorization")
        if header and header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
            except (ValueError, UnicodeDecodeError, binascii.Error):
                decoded = ""
            client_id, _sep, client_secret = decoded.partition(":")
            if client_id:
                return client_id, client_secret
        return kw.get("client_id"), kw.get("client_secret")
