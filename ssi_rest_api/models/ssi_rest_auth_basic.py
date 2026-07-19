# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""HTTP Basic provider.

Clean-room: no code/naming/structure copied from the proprietary framework
this module is functionally inspired by (see ``lib/dispatcher.py`` module
docstring).

Security note (binding, do not remove when editing this file):
``res.users._check_uid_passwd`` is decorated ``@tools.ormcache('uid',
'passwd')`` (Odoo core, ``base/models/res_users.py``), so a verified
plaintext password sits in the server's in-memory ORM cache for as long as
that cache entry lives. This is a conscious, accepted trade-off — the same
trust level Odoo's own XML-RPC API already operates under — not an
oversight introduced here.

``res.users.authenticate()`` is deliberately never called on this path:
it calls ``_update_last_login()``, which **writes** a ``res.users.log``
record. Under a readonly cursor that write forces Odoo's RO→RW retry,
executing the whole request twice. ``_check_uid_passwd`` verifies
credentials without writing anything.
"""

import base64
import binascii

from odoo import models
from odoo.exceptions import AccessDenied
from odoo.http import request

from ..lib.auth import RestAuthError, RestAuthResult

_AUTH_HEADER_PREFIX = "Basic "
_INVALID_CREDENTIAL_MESSAGE = "Invalid login or password."


class SsiRestAuthBasic(models.AbstractModel):
    _name = "ssi_rest_auth_basic"
    _inherit = ["mixin.rest_authenticator"]
    _description = "REST Authentication Provider - HTTP Basic"

    def _rest_auth_code(self):
        return "basic"

    def _rest_auth_extract(self):
        header = request.httprequest.headers.get("Authorization")
        if not header or not header.startswith(_AUTH_HEADER_PREFIX):
            return None
        encoded = header[len(_AUTH_HEADER_PREFIX) :].strip()
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise RestAuthError(
                "malformed_credential",
                "Malformed Basic Authorization header.",
                status=400,
            ) from exc
        if ":" not in decoded:
            raise RestAuthError(
                "malformed_credential",
                "Malformed Basic Authorization header.",
                status=400,
            )
        login, _sep, password = decoded.partition(":")
        return (login, password)

    def _rest_auth_verify(self, credential):
        login, password = credential
        users = self.env["res.users"].sudo()
        domain = users._get_login_domain(login)
        user = users.search(domain, order=users._get_login_order(), limit=1)
        if not user:
            # Same generic message as the wrong-password branch below: a
            # distinct "unknown login" message would let a caller enumerate
            # valid logins.
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            )
        try:
            users._check_uid_passwd(user.id, password)
        except AccessDenied as exc:
            raise RestAuthError(
                "invalid_credential", _INVALID_CREDENTIAL_MESSAGE, status=401
            ) from exc
        return RestAuthResult(uid=user.id, scheme=self._rest_auth_code())

    def _rest_auth_challenge(self):
        return 'Basic realm="ssi_rest"'
