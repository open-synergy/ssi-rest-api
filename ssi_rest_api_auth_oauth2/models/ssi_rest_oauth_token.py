# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OAuth2 token/authorization-code storage (backlog issue #20).

One row per issued authorization code, access token, or refresh token.
Every raw value (code or token) only ever exists transiently -- as the
return value of :meth:`_issue`, shown to the caller exactly once via the
authorize redirect or the token endpoint's JSON body -- and is never
persisted; only ``token_hash`` (a ``passlib`` hash) and ``token_index`` (a
short plaintext lookup prefix, not secret on its own) are stored. Same
hashing technique as ``ssi_rest_api_key.key_hash``/
``ssi_rest_oauth_client.client_secret_hash`` (``passlib`` pbkdf2_sha512),
looked up by the indexed ``token_index`` prefix first, never a full-table
scan.

Deliberately **not** master data and has no ``name``/``active`` field
(binding, this backlog item's Keputusan Desain): a token's lifecycle is
expressed by ``revoked`` + ``expiration_date`` instead, and it is never
edited through the UI as a named record.
"""

import base64
import hashlib
import secrets
from datetime import timedelta

from passlib.context import CryptContext

from odoo import api, fields, models

#: Same algorithm family as ssi_rest_api_key.key_hash and
#: ssi_rest_oauth_client.client_secret_hash.
_CRYPT_CONTEXT = CryptContext(schemes=["pbkdf2_sha512"])

#: Static, non-secret prefix on every generated raw code/token value --
#: tooling hint only, same rationale as ssi_rest_api_key's _KEY_PREFIX.
_TOKEN_PREFIX = "sot_"

#: Length of the plaintext lookup prefix stored in token_index. Same
#: sizing rationale as ssi_rest_api_key._KEY_INDEX_SIZE: rare collisions,
#: still a cheap selective index, never trusted alone (every candidate's
#: hash is still verified).
_TOKEN_INDEX_SIZE = 12

#: Authorization code lifetime is intentionally short and fixed (RFC 6749
#: SS4.1.2 recommends a maximum of 10 minutes) -- not a per-client field,
#: since a code is a one-time, immediately-consumed artifact, unlike
#: access/refresh tokens whose lifetime is a genuine per-client policy
#: choice (ssi_rest_oauth_client.access_token_lifetime/
#: refresh_token_lifetime).
AUTH_CODE_LIFETIME_SECONDS = 300


class SsiRestOauthToken(models.Model):
    _name = "ssi_rest_oauth_token"
    _description = "REST OAuth2 Token"
    _order = "create_date desc"

    client_id = fields.Many2one(
        comodel_name="ssi_rest_oauth_client",
        string="Client",
        required=True,
        ondelete="cascade",
        help="Client this code/token was issued to.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        ondelete="cascade",
        help="Resource owner this code/token was issued for (the user "
        "who authorized the client on the authorize endpoint). Empty for "
        "a client_credentials access token, which has no resource owner "
        "-- verified requests carrying such a token run as base's own "
        "public user (see ssi_rest_auth_oauth2.py).",
    )
    token_index = fields.Char(
        readonly=True,
        index=True,
        copy=False,
        help="Plaintext prefix of the generated raw code/token, used to "
        "look up a candidate row quickly (indexed) before verifying the "
        "full value against token_hash. Not secret on its own.",
    )
    token_hash = fields.Char(
        readonly=True,
        copy=False,
        help="Salted hash of the full raw code/token value (passlib "
        "pbkdf2_sha512). The raw value itself is never stored anywhere.",
    )
    token_type = fields.Selection(
        selection=[
            ("code", "Authorization Code"),
            ("access", "Access Token"),
            ("refresh", "Refresh Token"),
        ],
        required=True,
        readonly=True,
        help="Kind of credential this row represents.",
    )
    scope = fields.Char(
        help="Space-separated scope codes this code/token carries.",
    )
    expiration_date = fields.Datetime(
        required=True,
        help="Timestamp this code/token stops being usable. An expired "
        "row is rejected as invalid, exactly like a wrong value, and is "
        "purged by _gc_expired_oauth_token below.",
    )
    revoked = fields.Boolean(
        default=False,
        copy=False,
        help="A revoked code/token is rejected as invalid, exactly like "
        "an expired one. An authorization code is marked revoked the "
        "moment it is exchanged, so it can never be redeemed twice.",
    )
    code_challenge = fields.Char(
        readonly=True,
        help="PKCE code_challenge (RFC 7636), authorization codes only. "
        "Not part of this backlog item's literal field list, but "
        "required plumbing to satisfy its own binding requirement that "
        "authorization_code be PKCE-only: without persisting the "
        "challenge alongside the code, the token endpoint would have "
        "nothing to verify a code_verifier against.",
    )
    code_challenge_method = fields.Selection(
        selection=[("S256", "S256"), ("plain", "Plain")],
        default="S256",
        help="PKCE transform used to derive code_challenge from the "
        "client's code_verifier, authorization codes only.",
    )

    def action_revoke(self):
        """UI convenience mirroring the /oauth2/revoke endpoint's own
        effect: mark every selected row revoked, idempotently. Reachable
        only by base.group_system (see ir.model.access) and, per the
        binding "own tokens only" ir.rule, only over rows the acting user
        is themselves the resource owner of.
        """
        self.write({"revoked": True})

    @api.model
    def _issue(
        self,
        client,
        user,
        token_type,
        scope,
        lifetime_seconds,
        code_challenge=None,
        code_challenge_method=None,
    ):
        """Create a new code/token row and return ``(record, raw_value)``.

        ``raw_value`` is the only place the plaintext code/token ever
        exists; the caller must hand it to the client immediately (redirect
        query string or JSON response body) and never store it itself.
        """
        raw_value = _TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = self.sudo().create(
            {
                "client_id": client.id,
                "user_id": user.id if user else False,
                "token_index": raw_value[:_TOKEN_INDEX_SIZE],
                "token_hash": _CRYPT_CONTEXT.hash(raw_value),
                "token_type": token_type,
                "scope": scope or "",
                "expiration_date": fields.Datetime.now()
                + timedelta(seconds=lifetime_seconds),
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            }
        )
        return record, raw_value

    @api.model
    def _lookup(self, raw_value, token_type, client=None):
        """Return the single active, unexpired, unrevoked row of
        ``token_type`` that ``raw_value`` belongs to, or an empty
        recordset. Looks up candidates by ``token_index`` (indexed) first
        -- never a full-table scan -- then verifies ``raw_value`` against
        each candidate's ``token_hash``. When ``client`` is given, only
        rows issued to that client are considered.
        """
        if not raw_value:
            return self.browse()
        domain = [
            ("token_index", "=", raw_value[:_TOKEN_INDEX_SIZE]),
            ("token_type", "=", token_type),
            ("revoked", "=", False),
            ("expiration_date", ">", fields.Datetime.now()),
        ]
        if client is not None:
            domain.append(("client_id", "=", client.id))
        candidates = self.sudo().search(domain)
        for candidate in candidates:
            if candidate.token_hash and _CRYPT_CONTEXT.verify(
                raw_value, candidate.token_hash
            ):
                return candidate
        return self.browse()

    @api.model
    def _lookup_for_revoke(self, raw_value, client):
        """Same lookup as :meth:`_lookup` but ignores ``token_type``
        (RFC 7009's revoke endpoint accepts either an access or a refresh
        token) and does not require the row to still be unrevoked --
        revoking an already-revoked token is idempotent, not an error.
        """
        if not raw_value:
            return self.browse()
        candidates = self.sudo().search(
            [
                ("token_index", "=", raw_value[:_TOKEN_INDEX_SIZE]),
                ("token_type", "in", ("access", "refresh")),
                ("client_id", "=", client.id),
            ]
        )
        for candidate in candidates:
            if candidate.token_hash and _CRYPT_CONTEXT.verify(
                raw_value, candidate.token_hash
            ):
                return candidate
        return self.browse()

    def _check_pkce(self, code_verifier):
        """Return whether ``code_verifier`` satisfies this authorization
        code's stored ``code_challenge`` (RFC 7636 SS4.6).
        """
        self.ensure_one()
        if not self.code_challenge or not code_verifier:
            return False
        if self.code_challenge_method == "plain":
            computed = code_verifier
        else:
            digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
            computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return secrets.compare_digest(computed, self.code_challenge)

    @api.autovacuum
    def _gc_expired_oauth_token(self):
        """Delete every code/token row whose expiration_date has passed.

        Hooked into core's ``ir.autovacuum`` mechanism via the
        ``@api.autovacuum`` decorator -- discovered and called by
        ``ir.autovacuum._run_vacuum_cleaner`` on any model, without that
        model itself inheriting ``ir.autovacuum`` (verified against Odoo
        19 core; same pattern and rationale as ssi_rest_api_log's own
        ``_gc_expired_request_log``). This is what satisfies this backlog
        item's binding Keputusan Desain ("pembersihan token kedaluwarsa
        dilakukan lewat _inherit='ir.autovacuum', bukan cron bespoke"):
        the intent -- purge through the autovacuum mechanism, no bespoke
        cron -- is met by this decorator; actually inheriting
        ``ir.autovacuum`` on this model would incorrectly make this model
        itself a *second* copy of the vacuum-cleaner runner, discovering
        and re-running every other model's own autovacuum method too.

        Unlike ssi_rest_request_log's configurable retention window, no
        ``ir.config_parameter`` is needed here: ``expiration_date`` is
        already each row's own, per-token, natural purge boundary.
        """
        expired = self.sudo().search([("expiration_date", "<", fields.Datetime.now())])
        expired.unlink()
