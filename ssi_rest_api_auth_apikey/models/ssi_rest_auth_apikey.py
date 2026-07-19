# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Scoped API key provider -- ``mixin.rest_authenticator`` implementation
for ``ssi_rest_api_key`` (backlog issue #18).

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring).

Deliberately reads a dedicated ``X-Api-Key`` header rather than the
``Authorization`` header: ``ssi_rest_auth_basic``/``ssi_rest_auth_bearer``
(``ssi_rest_api``) already claim the ``Basic``/``Bearer`` schemes on
``Authorization`` for password and Odoo-core ``res.users.apikeys`` login
respectively; a distinct header keeps this scoped-key scheme's credential
unambiguous and lets a caller send it alongside (or instead of) either of
those without any prefix-matching overlap.
"""

import logging

from odoo import models
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError, RestAuthResult

_logger = logging.getLogger(__name__)

_HEADER_NAME = "X-Api-Key"
_INVALID_CREDENTIAL_MESSAGE = "Invalid or expired API key."


class SsiRestAuthApikey(models.AbstractModel):
    _name = "ssi_rest_auth_apikey"
    _inherit = ["mixin.rest_authenticator"]
    _description = "REST Authentication Provider - Scoped API Key"

    def _rest_auth_code(self):
        return "apikey"

    def _rest_auth_extract(self):
        raw_key = request.httprequest.headers.get(_HEADER_NAME)
        if not raw_key:
            return None
        raw_key = raw_key.strip()
        if not raw_key:
            return None
        return raw_key

    def _rest_auth_verify(self, credential):
        key_model = self.env["ssi_rest_api_key"].sudo()
        record = key_model._authenticate(credential)
        if not record:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        # Never through the request's own env.cr -- see
        # _touch_last_used_date's docstring (models/ssi_rest_api_key.py)
        # for the full, binding rationale.
        record._touch_last_used_date()
        return RestAuthResult(
            uid=record.user_id.id,
            scheme=self._rest_auth_code(),
            profile_ids=(record.profile_id.id,),
        )

    def _rest_auth_challenge(self):
        return 'ApiKey realm="ssi_rest"'
