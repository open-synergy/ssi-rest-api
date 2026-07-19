# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OAuth2 registered client (backlog issue #20).

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring). Every model in this
module is a plain ORM model with a btree index on its lookup column --
never ``_auto=False`` + raw SQL the way that framework's own OAuth2 tables
are implemented (binding, this backlog item's Keputusan Desain).

Hashing technique note (binding, do not remove when editing this file):
same technique as ``ssi_rest_api_key`` (``ssi_rest_api_auth_apikey``) --
``passlib`` ``pbkdf2_sha512`` -- reused here for ``client_secret_hash``
instead of a plaintext or MD5 comparison.
"""

import secrets

from passlib.context import CryptContext

from odoo import fields, models
from odoo.exceptions import UserError

#: Same algorithm family as ``ssi_rest_api_key.key_hash`` and Odoo core's
#: own password hashing -- a slow, salted KDF, not a fast general purpose
#: hash vulnerable to brute-forcing a stolen ``client_secret_hash``.
_CRYPT_CONTEXT = CryptContext(schemes=["pbkdf2_sha512"])

#: Static prefix on every generated raw client secret, a human/tooling
#: hint only -- carries no security weight of its own (same rationale as
#: ssi_rest_api_key's own _KEY_PREFIX).
_SECRET_PREFIX = "soc_"

_GRANT_TYPES = ("authorization_code", "client_credentials", "refresh_token")


class SsiRestOauthClient(models.Model):
    """A registered OAuth2 client application.

    Deliberately **not** master data (no ``mixin.master_data``, same
    reasoning as ``ssi_rest_access_profile``/``ssi_rest_api_key``): a
    client is a security credential administered by an administrator, not
    business reference data, so ``name``/``active`` are declared manually.

    BINDING (do not remove this comment when editing this class): the raw
    client secret only ever exists transiently, as the return value of
    :meth:`_generate_new_client_secret` -- it is never written to any
    stored field. Only ``client_secret_hash`` is persisted, and only for
    ``client_type == 'confidential'``: a ``public`` client authenticates
    itself solely through PKCE (``code_challenge``/``code_verifier`` on
    ``ssi_rest_oauth_token``), never a secret it cannot keep confidential.
    """

    _name = "ssi_rest_oauth_client"
    _description = "REST OAuth2 Client"
    _order = "name"

    _client_id_uniq = models.Constraint(
        "UNIQUE (client_id)",
        "Client ID must be unique.",
    )

    name = fields.Char(
        required=True,
        help="Descriptive label for this OAuth2 client application.",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive clients are rejected on every OAuth2 endpoint "
        "(authorize, token, revoke), exactly like an unknown client_id.",
    )
    client_id = fields.Char(
        required=True,
        copy=False,
        help="Public identifier for this client, sent as the client_id "
        "parameter on every OAuth2 request. Not secret on its own.",
    )
    client_secret_hash = fields.Char(
        readonly=True,
        copy=False,
        help="Salted hash of this client's secret (passlib pbkdf2_sha512), "
        "confidential clients only. The raw secret itself is never "
        "stored anywhere; it only ever exists as the return value of "
        "_generate_new_client_secret(), shown to the caller once. Always "
        "empty for client_type == 'public'.",
    )
    client_type = fields.Selection(
        selection=[("confidential", "Confidential"), ("public", "Public")],
        required=True,
        default="confidential",
        help="Confidential clients (server-side apps) authenticate with "
        "client_id + client_secret and may use every grant. Public "
        "clients (SPA, mobile, CLI) cannot keep a secret confidential, "
        "so they never hold one and must always use PKCE on the "
        "authorization_code grant instead.",
    )
    redirect_uri_ids = fields.One2many(
        comodel_name="ssi_rest_oauth_client.redirect_uri",
        inverse_name="client_id",
        string="Redirect URIs",
        help="Exact redirect_uri values this client is allowed to receive "
        "an authorization code at. The authorize endpoint requires an "
        "exact string match against one of these -- prefix or wildcard "
        "matching is never accepted.",
    )
    grant_types = fields.Char(
        required=True,
        default="authorization_code,refresh_token",
        help="Comma-separated subset of authorization_code, "
        "client_credentials, refresh_token this client may use. A grant "
        "requested on the token endpoint that is not both globally "
        "supported and listed here is rejected as unauthorized_client.",
    )
    scope_ids = fields.Many2many(
        comodel_name="ssi_rest_oauth_scope",
        string="Scopes",
        help="Scopes this client may be granted on an issued token.",
    )
    access_token_lifetime = fields.Integer(
        required=True,
        default=3600,
        help="Lifetime, in seconds, of an access token issued to this "
        "client (default 1 hour).",
    )
    refresh_token_lifetime = fields.Integer(
        required=True,
        default=1209600,
        help="Lifetime, in seconds, of a refresh token issued to this "
        "client (default 14 days).",
    )
    profile_id = fields.Many2one(
        comodel_name="ssi_rest_access_profile",
        string="Access Profile",
        help="Access profile every token issued to this client carries. "
        "Same subtractive-only narrowing semantics as "
        "ssi_rest_api_key.profile_id: this can only narrow access already "
        "granted by Odoo's own ACL/record rules, never widen it.",
    )

    def action_generate_client_secret(self):
        for record in self.sudo():
            result = record._generate_client_secret_action()
        return result

    def _generate_client_secret_action(self):
        """Generate a new client secret for this record and surface it to
        the caller exactly once, through a client notification -- never
        through a stored field, so there is nothing left to read back a
        second time. Confidential clients only.
        """
        self.ensure_one()
        if self.client_type != "confidential":
            raise UserError(
                self.env._(
                    "Only confidential clients have a client secret. "
                    "Public clients authenticate with PKCE instead."
                )
            )
        raw_secret = self._generate_new_client_secret()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Client Secret Generated"),
                "message": self.env._(
                    "Copy this client secret now, it will not be shown "
                    "again:\n\n%(raw_secret)s",
                    raw_secret=raw_secret,
                ),
                "sticky": True,
            },
        }

    def _generate_new_client_secret(self):
        """Generate a brand-new raw secret for this record, persist only
        its hash, and return the raw value. Calling this again invalidates
        whatever secret this client held before (the old hash is simply
        overwritten), the same "regenerate" semantics as
        ssi_rest_api_key._generate_new_key.
        """
        self.ensure_one()
        raw_secret = _SECRET_PREFIX + secrets.token_urlsafe(32)
        self.write({"client_secret_hash": _CRYPT_CONTEXT.hash(raw_secret)})
        return raw_secret

    def _check_client_secret(self, raw_secret):
        """Return whether ``raw_secret`` matches this confidential
        client's stored hash. Always False for a public client (it has no
        meaningful secret to check) or when no secret was ever generated.
        """
        self.ensure_one()
        if self.client_type != "confidential" or not self.client_secret_hash:
            return False
        if not raw_secret:
            return False
        return _CRYPT_CONTEXT.verify(raw_secret, self.client_secret_hash)

    def _allows_grant(self, grant_type):
        """Return whether ``grant_type`` is both a globally supported
        OAuth2 grant and listed in this client's own ``grant_types``.
        """
        self.ensure_one()
        if grant_type not in _GRANT_TYPES:
            return False
        allowed = {item.strip() for item in (self.grant_types or "").split(",")}
        return grant_type in allowed

    def _has_redirect_uri(self, redirect_uri):
        """Return whether ``redirect_uri`` matches, exactly, one of this
        client's registered redirect_uri_ids. Prefix/wildcard matching is
        never accepted (binding Keputusan Desain).
        """
        self.ensure_one()
        return redirect_uri in self.redirect_uri_ids.mapped("url")
