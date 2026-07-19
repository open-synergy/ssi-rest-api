# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64
import hashlib

from odoo_yaml_test import YamlTransactionCase

from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSsiRestOauthToken(YamlTransactionCase):
    def setUp(self):
        super().setUp()
        self.client = self.env["ssi_rest_oauth_client"].create(
            {"name": "Token Model Test App", "client_id": "token-model-test-app"}
        )

    def test_ssi_rest_oauth_token(self):
        self.run_yaml_scenario("test_data_ssi_rest_oauth_token.yaml")

    def test_issue_and_lookup_roundtrip(self):
        """Python murni -- pemicu P1 (L-01/L-02: _issue's raw value is
        never stored anywhere -- by design, see the model's module
        docstring -- so no YAML `assert` on a field can ever observe it;
        _lookup's returned recordset is likewise a plain method return
        value, not a field).
        """
        token_model = self.env["ssi_rest_oauth_token"]
        record, raw_value = token_model._issue(
            self.client, self.env.user, "access", "read:partner", 3600
        )
        self.assertTrue(raw_value)
        self.assertNotEqual(record.token_hash, raw_value)
        found = token_model._lookup(raw_value, "access")
        self.assertEqual(found, record)
        # Wrong raw value never matches, even with a correct prefix-length
        # guess.
        self.assertFalse(token_model._lookup("sot_wrong-value", "access"))
        # Right value, wrong token_type -- never matches either.
        self.assertFalse(token_model._lookup(raw_value, "refresh"))
        # Right value, wrong client -- never matches.
        other_client = self.env["ssi_rest_oauth_client"].create(
            {"name": "Other App", "client_id": "other-app"}
        )
        self.assertFalse(token_model._lookup(raw_value, "access", client=other_client))

    def test_lookup_excludes_revoked_and_expired_rows(self):
        """Python murni -- pemicu P1 (L-01: _lookup's returned recordset
        is a plain method return value, not a stored field an `assert`
        step could read).
        """
        token_model = self.env["ssi_rest_oauth_token"]
        revoked_record, revoked_raw = token_model._issue(
            self.client, self.env.user, "access", "", 3600
        )
        revoked_record.write({"revoked": True})
        self.assertFalse(token_model._lookup(revoked_raw, "access"))

        expired_record, expired_raw = token_model._issue(
            self.client, self.env.user, "access", "", 3600
        )
        expired_record.write({"expiration_date": "2000-01-01 00:00:00"})
        self.assertFalse(token_model._lookup(expired_raw, "access"))

    def test_check_pkce_s256(self):
        """Python murni -- pemicu P1 (L-01: _check_pkce's boolean return
        value is not a stored field).
        """
        record, _raw_code = self.env["ssi_rest_oauth_token"]._issue(
            self.client,
            self.env.user,
            "code",
            "",
            300,
            code_challenge=self._s256_challenge("correct-verifier"),
            code_challenge_method="S256",
        )
        self.assertTrue(record._check_pkce("correct-verifier"))
        self.assertFalse(record._check_pkce("wrong-verifier"))
        self.assertFalse(record._check_pkce(False))

    def test_check_pkce_plain(self):
        """Python murni -- pemicu P1 (L-01: _check_pkce's boolean return
        value is not a stored field).
        """
        record, _raw_code = self.env["ssi_rest_oauth_token"]._issue(
            self.client,
            self.env.user,
            "code",
            "",
            300,
            code_challenge="plain-verifier-value",
            code_challenge_method="plain",
        )
        self.assertTrue(record._check_pkce("plain-verifier-value"))
        self.assertFalse(record._check_pkce("something-else"))

    @staticmethod
    def _s256_challenge(verifier):
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
