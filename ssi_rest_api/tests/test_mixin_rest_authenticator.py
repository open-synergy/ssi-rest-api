# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMixinRestAuthenticator(TransactionCase):
    def test_contract_methods_raise_not_implemented(self):
        """Python murni — pemicu P1 (L-01/L-02): asserting that a bare
        method call raises, on an env recordset that carries no record at
        all (``mixin.rest_authenticator`` is an ``AbstractModel``) — the
        YAML DSL's ``assert`` action only reads fields off a record saved
        in the registry, it has no action for "call this and expect it to
        raise" outside a `create`/`write`/`call`/`wizard`/`form` step tied
        to an actual record.
        """
        provider = self.env["mixin.rest_authenticator"]
        with self.assertRaises(NotImplementedError):
            provider._rest_auth_code()
        with self.assertRaises(NotImplementedError):
            provider._rest_auth_extract()
        with self.assertRaises(NotImplementedError):
            provider._rest_auth_verify("some-credential")
        with self.assertRaises(NotImplementedError):
            provider._rest_auth_challenge()
