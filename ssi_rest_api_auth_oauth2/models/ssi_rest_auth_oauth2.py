# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OAuth2 access token provider -- ``mixin.rest_authenticator``
implementation for ``ssi_rest_oauth_token`` (backlog issue #20).

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring).

Reads the standard ``Authorization: Bearer <token>`` header -- the header
every OAuth2 client already sends its access token on -- rather than a
dedicated header. This deliberately overlaps with the built-in
``ssi_rest_auth_bearer`` scheme's own indiscriminate extraction on the
same header, exactly the situation ``ssi_rest_api_auth_jwt`` already
documents and accepts (see that module's ``models/ssi_rest_auth_jwt.py``
module docstring): unlike a JWT, an opaque OAuth2 access token has no
distinguishing shape ``_rest_auth_extract`` could use to tell it apart
from a core ``res.users.apikeys`` value without querying the database
(forbidden -- see ``mixin.rest_authenticator._rest_auth_extract``'s own
contract). A deployment that installs this module and does not use the
core ``bearer`` scheme at all should deactivate that scheme's
``ssi_rest_auth_scheme`` record to avoid the resulting
``400 multiple_credentials`` -- an operational configuration step, not a
code path this provider can resolve unilaterally.
"""

from odoo import models
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError, RestAuthResult

_AUTH_HEADER_PREFIX = "Bearer "
_INVALID_CREDENTIAL_MESSAGE = "Invalid, expired, or revoked access token."


class SsiRestAuthOauth2(models.AbstractModel):
    _name = "ssi_rest_auth_oauth2"
    _inherit = ["mixin.rest_authenticator"]
    _description = "REST Authentication Provider - OAuth2 Bearer Token"

    def _rest_auth_code(self):
        return "oauth2"

    def _rest_auth_extract(self):
        header = request.httprequest.headers.get("Authorization")
        if not header or not header.startswith(_AUTH_HEADER_PREFIX):
            return None
        token = header[len(_AUTH_HEADER_PREFIX) :].strip()
        return token or None

    def _rest_auth_verify(self, credential):
        # sudo(): this runs before the request's identity is known at all
        # (same rationale ssi_rest_auth_apikey/basic/bearer/jwt's own
        # credential lookups already document) -- there is no caller ACL
        # to respect yet.
        token_model = self.env["ssi_rest_oauth_token"].sudo()
        record = token_model._lookup(credential, "access")
        if not record:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        # client_credentials tokens carry no resource owner (user_id is
        # empty, see ssi_rest_oauth_token.user_id's own help text): such a
        # request runs as Odoo's own public user, mirroring how every
        # other public, unauthenticated-as-a-person ssi_rest request
        # already runs (auth="public" routes).
        uid = (
            record.user_id.id if record.user_id else self.env.ref("base.public_user").id
        )
        profile = record.client_id.profile_id
        return RestAuthResult(
            uid=uid,
            scheme=self._rest_auth_code(),
            profile_ids=(profile.id,) if profile else (),
            scopes=tuple((record.scope or "").split()),
            expires_at=record.expiration_date,
        )

    def _rest_auth_challenge(self):
        return 'Bearer realm="ssi_rest"'
