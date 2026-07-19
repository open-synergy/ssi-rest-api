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
dedicated header, so it necessarily shares that header with the built-in
``ssi_rest_auth_bearer`` scheme's own indiscriminate extraction. Unlike
``ssi_rest_api_auth_jwt`` (which tells a JWT apart from an opaque
``res.users.apikeys`` value by its three-segment shape),
:meth:`_rest_auth_extract` here disambiguates the *other* way: it only
claims a bearer value that starts with ``ssi_rest_oauth_token.TOKEN_PREFIX``
(``"sot_"``) -- every token this module itself ever issues -- and leaves
anything else (including a genuine core API key) for ``ssi_rest_auth_bearer``
to claim instead. This is not optional polish: this repo's own test suite
installs every ``ssi_rest_api*`` module together in one database (CI), so
without this check *every* bearer-authenticated request anywhere in the
repo -- not just this module's own -- would extract two credentials at
once and fail as ``400 multiple_credentials``, regardless of whether the
caller ever touches OAuth2 at all.

This only protects the one direction this provider controls: it cannot
stop ``ssi_rest_auth_bearer`` from *also* claiming one of this module's
own ``"sot_"``-prefixed tokens, since that scheme's own extraction is
shape-blind by design. A route that must accept only OAuth2 access
tokens restricts itself with ``rest_route(..., schemes=("oauth2",))``
(the same idiom ``ssi_rest_api_auth_jwt``'s own tests already use, see
``tests/test_controller_ssi_rest_auth_oauth2.py``); a deployment that
wants every route to accept OAuth2 tokens without that restriction
should deactivate the ``bearer`` ``ssi_rest_auth_scheme`` record instead
-- an operational configuration step, not a code path this provider can
resolve unilaterally.
"""

from odoo import models
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError, RestAuthResult

from .ssi_rest_oauth_token import TOKEN_PREFIX

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
        # Shape check only (cheap, no DB query) -- see module docstring:
        # this is what keeps a core res.users.apikeys bearer value (or
        # any other scheme's opaque token) from also being claimed here.
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        return token

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
