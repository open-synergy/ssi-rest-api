# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Configured external JWT issuer (backlog issue #19).

Clean-room: no code, naming, or file structure is copied from the
proprietary REST framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring for the full
rationale).
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..lib.jwks_cache import invalidate as _invalidate_jwks_cache

#: Algorithm families whose signing key is ``shared_secret`` (symmetric
#: HMAC). Everything else in ``_ALGORITHM_SELECTION`` is asymmetric and
#: resolved through ``jwks_url`` instead (see ``_check_key_source``
#: below and ``models/ssi_rest_auth_jwt.py``'s ``_resolve_signing_key``).
HMAC_ALGORITHM_PREFIX = "HS"

_ALGORITHM_SELECTION = [
    ("HS256", "HS256"),
    ("HS384", "HS384"),
    ("HS512", "HS512"),
    ("RS256", "RS256"),
    ("RS384", "RS384"),
    ("RS512", "RS512"),
    ("ES256", "ES256"),
    ("ES384", "ES384"),
    ("ES512", "ES512"),
]


class SsiRestJwtIssuer(models.Model):
    """One external identity provider (e.g. Authentik, Keycloak, Entra)
    whose JWTs the ``jwt`` ``ssi_rest_auth_scheme`` (``ssi_rest_auth_jwt``,
    ``models/ssi_rest_auth_jwt.py``) accepts as bearer credentials.

    BINDING (backlog issue #19's Keputusan Desain, do not remove this
    comment when editing this class): deliberately a **plain**
    ``models.Model`` -- neither ``mixin.master_data`` (this is a security
    credential source, administered by API administrators, not business
    reference data -- same reasoning ``ssi_rest_access_profile`` and
    ``ssi_rest_api_key`` already use) **nor** ``ssi_backend_mixin``.
    ``ssi_backend_mixin`` is rejected specifically, not merely skipped: it
    requires ``company_id`` and its ``action_running()`` deactivates every
    other running record in the same company ("one active backend per
    company"). That semantic is wrong here -- several issuers (e.g. an
    internal Authentik instance *and* a customer's Entra tenant) must be
    able to stay active at once, across companies. Because no mixin
    supplies them, ``name`` and ``active`` are declared by hand below.
    """

    _name = "ssi_rest_jwt_issuer"
    _description = "REST JWT Issuer"
    _order = "id desc"

    name = fields.Char(
        required=True,
        help="Descriptive label for this issuer configuration (e.g. "
        "which identity provider it represents).",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive issuers are never matched against a token's iss "
        "claim, exactly as if they did not exist.",
    )
    issuer = fields.Char(
        string="Issuer (iss)",
        required=True,
        help="Expected value of the token's iss claim. A token whose iss "
        "does not match any active issuer record's issuer value is "
        "rejected -- this is the lookup key used to select which issuer "
        "record verifies a given token.",
    )
    audience = fields.Char(
        string="Audience (aud)",
        required=True,
        help="Expected value of the token's aud claim, enforced on every "
        "verification with no bypass.",
    )
    algorithm = fields.Selection(
        selection=_ALGORITHM_SELECTION,
        required=True,
        default="RS256",
        help="The only signing algorithm accepted for tokens from this "
        "issuer. Passed explicitly to the JWT library's algorithm "
        "whitelist, never inferred from the token's own header, so a "
        "token claiming a different algorithm (including 'none') is "
        "always rejected.",
    )
    jwks_url = fields.Char(
        string="JWKS URL",
        help="JSON Web Key Set endpoint (RFC 7517) this issuer publishes "
        "its public signing keys at. Required, and only used, when "
        "algorithm is an asymmetric family (RS*/ES*); fetched through a "
        "TTL-bound cache (see lib/jwks_cache.py), never on every request.",
    )
    shared_secret = fields.Char(
        groups="base.group_system",
        help="Symmetric signing secret, required and only used when "
        "algorithm is an HMAC family (HS*). Readable/writable only by "
        "the base.group_system group -- excluded from fields_get()/read() "
        "for any other user, and therefore never returned by any "
        "ssi_rest endpoint either.",
    )
    user_claim = fields.Char(
        required=True,
        default="sub",
        help="Name of the token claim whose value identifies the Odoo "
        "user, looked up through user_match_field. Never used to create "
        "a user -- an unmatched claim value is rejected (401), not "
        "provisioned.",
    )
    user_match_field = fields.Selection(
        selection=[("login", "Login"), ("email", "Email")],
        required=True,
        default="login",
        help="res.users field user_claim's value is matched against.",
    )
    leeway = fields.Integer(
        default=0,
        help="Clock-skew tolerance, in seconds, applied to both exp and "
        "nbf validation.",
    )
    profile_id = fields.Many2one(
        comodel_name="ssi_rest_access_profile",
        string="Access Profile",
        ondelete="restrict",
        help="Access profile a request authenticated through this issuer "
        "is scoped to. Profiles only ever narrow access already granted "
        "by Odoo's own ACL/record rules, never widen it.",
    )

    @api.constrains("algorithm", "jwks_url", "shared_secret")
    def _check_key_source(self):
        """Enforce that the key material the configured algorithm needs is
        actually present, at save time -- so ``ssi_rest_auth_jwt`` can
        assume a well-formed issuer record instead of re-checking this on
        every request.
        """
        for record in self:
            if record.algorithm.startswith(HMAC_ALGORITHM_PREFIX):
                if not record.shared_secret:
                    raise ValidationError(
                        self.env._(
                            "Shared Secret is required when Algorithm is "
                            "an HMAC family (HS*)."
                        )
                    )
            elif not record.jwks_url:
                raise ValidationError(
                    self.env._(
                        "JWKS URL is required when Algorithm is an "
                        "asymmetric family (RS*/ES*)."
                    )
                )

    def write(self, vals):
        result = super().write(vals)
        if "jwks_url" in vals:
            for record in self:
                _invalidate_jwks_cache(record.id)
        return result

    def unlink(self):
        record_ids = self.ids
        result = super().unlink()
        for record_id in record_ids:
            _invalidate_jwks_cache(record_id)
        return result
