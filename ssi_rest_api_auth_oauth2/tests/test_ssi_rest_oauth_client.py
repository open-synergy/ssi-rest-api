# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo_yaml_test import YamlTransactionCase
from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestSsiRestOauthClient(YamlTransactionCase):
    def test_ssi_rest_oauth_client(self):
        self.run_yaml_scenario("test_data_ssi_rest_oauth_client.yaml")

    @mute_logger("odoo.sql_db")
    def test_client_id_must_be_unique(self):
        """Python murni -- pemicu P5 (L-22: sebuah pelanggaran UNIQUE
        constraint (models.Constraint) mengangkat psycopg2.IntegrityError,
        di luar 12 tipe yang dikenali expect_error YAML).
        """
        self.env["ssi_rest_oauth_client"].create(
            {"name": "App A", "client_id": "dup-client"}
        )
        with self.assertRaises(IntegrityError):
            self.env["ssi_rest_oauth_client"].create(
                {"name": "App B", "client_id": "dup-client"}
            )

    def test_generate_client_secret_roundtrip(self):
        """Python murni -- pemicu P1 (L-01: _check_client_secret's boolean
        return value cannot be asserted by any YAML action -- `call`
        discards it, and it is not a field `assert` can read either).
        """
        client = self.env["ssi_rest_oauth_client"].create(
            {"name": "Confidential App", "client_id": "confidential-app"}
        )
        raw_secret = client._generate_new_client_secret()
        self.assertTrue(client.client_secret_hash)
        self.assertTrue(client._check_client_secret(raw_secret))
        self.assertFalse(client._check_client_secret("wrong-secret"))
        self.assertFalse(client._check_client_secret(False))

    def test_public_client_never_checks_a_secret(self):
        """Python murni -- pemicu P1 (L-01: _check_client_secret's return
        value). A public client has no meaningful secret at all: even an
        empty stored hash must never make _check_client_secret return
        True for an arbitrary guess.
        """
        client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Public App",
                "client_id": "public-app",
                "client_type": "public",
            }
        )
        self.assertFalse(client._check_client_secret("anything"))

    def test_generate_client_secret_rejected_for_public_client(self):
        """Python murni -- pemicu P1 (L-01: action_generate_client_secret
        returns an ir.actions.client dict on success; the failure path
        here raises UserError, whose message content assertRaises can
        inspect but a YAML `call` step's `asserts` -- evaluated on the
        target record, never on the raised exception -- cannot).
        """
        client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Public App",
                "client_id": "public-app-2",
                "client_type": "public",
            }
        )
        with self.assertRaises(UserError):
            client.action_generate_client_secret()

    def test_allows_grant_checks_both_whitelist_and_client_config(self):
        """Python murni -- pemicu P1 (L-01: _allows_grant's boolean return
        value is not a stored field, so no YAML `assert` can read it).
        """
        client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Grant App",
                "client_id": "grant-app",
                "grant_types": "authorization_code",
            }
        )
        self.assertTrue(client._allows_grant("authorization_code"))
        self.assertFalse(client._allows_grant("client_credentials"))
        self.assertFalse(client._allows_grant("password"))

    def test_has_redirect_uri_requires_an_exact_match(self):
        """Python murni -- pemicu P1 (L-01: _has_redirect_uri's boolean
        return value is not a stored field).
        """
        client = self.env["ssi_rest_oauth_client"].create(
            {
                "name": "Redirect App",
                "client_id": "redirect-app",
                "redirect_uri_ids": [
                    (0, 0, {"sequence": 10, "url": "https://app.example.com/cb"})
                ],
            }
        )
        self.assertTrue(client._has_redirect_uri("https://app.example.com/cb"))
        self.assertFalse(client._has_redirect_uri("https://app.example.com/cb/extra"))
        self.assertFalse(client._has_redirect_uri("https://evil.example.com/cb"))
