# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import models


class MixinRestAuthenticator(models.AbstractModel):
    """Contract every REST authentication provider must implement.

    A concrete provider (Basic, Bearer, API key, JWT, OAuth2, ... — each its
    own later backlog item) is an ``AbstractModel`` that ``_inherit``s this
    mixin and is referenced, by its ``_name``, from a ``ssi_rest_auth_scheme``
    record's ``provider_model`` field. ``_auth_method_ssi_rest``
    (``models/ir_http.py``) looks providers up through that registry and
    calls the four methods below on ``self.env[provider_model]`` — an empty
    recordset used purely as a namespace, the same way ``env['ir.http']``
    itself is used; no record of the provider's own model is ever created,
    read, written or unlinked.
    """

    _name = "mixin.rest_authenticator"
    _description = "Mixin for REST Authentication Providers"

    def _rest_auth_code(self):
        """Return this provider's ``ssi_rest_auth_scheme.code`` (e.g.
        ``"basic"``, ``"bearer"``, ``"oauth2"``, ``"jwt"``).

        :rtype: str
        """
        raise NotImplementedError

    def _rest_auth_extract(self):
        """Read this scheme's credential off the current request, if
        present.

        Must be cheap and must never query the database: it runs once per
        active scheme on *every* ``ssi_rest`` request, including requests
        that end up using a different scheme entirely.

        :return: the raw credential (whatever shape ``_rest_auth_verify``
            below expects), or ``None`` if this request carries no
            credential for this scheme at all — the only condition under
            which ``_auth_method_ssi_rest`` silently moves on to the next
            scheme instead of treating the request as failed.
        """
        raise NotImplementedError

    def _rest_auth_verify(self, credential):
        """Verify ``credential`` (as returned by :meth:`_rest_auth_extract`)
        and resolve it to an authenticated user.

        :param credential: the value :meth:`_rest_auth_extract` returned.
        :return: a :class:`~odoo.addons.ssi_rest_api.lib.auth.RestAuthResult`
            on success.
        :rtype: ~odoo.addons.ssi_rest_api.lib.auth.RestAuthResult
        :raises .lib.auth.RestAuthError: on any verification failure. Must
            never return a falsy value to signal failure, and must never
            raise any exception type other than
            :class:`~odoo.addons.ssi_rest_api.lib.auth.RestAuthError` — see
            that class's docstring for why.
        """
        raise NotImplementedError

    def _rest_auth_challenge(self):
        """Return this scheme's ``WWW-Authenticate`` challenge value (e.g.
        ``"Basic"``, ``'Bearer realm="ssi_rest"'``).

        Combined with every other active scheme's challenge by
        ``_auth_method_ssi_rest`` when a request carries no credential at
        all.

        :rtype: str
        """
        raise NotImplementedError
