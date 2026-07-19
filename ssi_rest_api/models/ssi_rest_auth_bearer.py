# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Bearer API key provider — thin wrapper around Odoo's built-in
``res.users.apikeys``.

Clean-room: no code/naming/structure copied from the proprietary framework
this module is functionally inspired by (see ``lib/dispatcher.py`` module
docstring). No new credential-storage model is introduced here: key
storage, hashing, expiration and the "generate key" UI are all Odoo core's
own (``res.users.apikeys``), not reimplemented.
"""

from odoo import models
from odoo.http import request

from ..lib.auth import RestAuthError, RestAuthResult

_AUTH_HEADER_PREFIX = "Bearer "


class SsiRestAuthBearer(models.AbstractModel):
    _name = "ssi_rest_auth_bearer"
    _inherit = ["mixin.rest_authenticator"]
    _description = "REST Authentication Provider - Bearer API Key"

    def _rest_auth_code(self):
        return "bearer"

    def _rest_auth_extract(self):
        header = request.httprequest.headers.get("Authorization")
        if not header or not header.startswith(_AUTH_HEADER_PREFIX):
            return None
        token = header[len(_AUTH_HEADER_PREFIX) :].strip()
        if not token:
            return None
        return token

    def _rest_auth_verify(self, credential):
        uid = self.env["res.users.apikeys"]._check_credentials(
            scope="rpc", key=credential
        )
        if not uid:
            raise RestAuthError(
                "invalid_credential",
                "Invalid or expired API key.",
                status=401,
            )
        return RestAuthResult(uid=uid, scheme=self._rest_auth_code())

    def _rest_auth_challenge(self):
        return "Bearer"
