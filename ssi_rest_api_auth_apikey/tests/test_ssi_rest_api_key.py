# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Model-level tests for ``ssi_rest_api_key`` (backlog issue #18).

CRUD, the registered scheme record, and record-rule enforcement are
covered by ``test_data_ssi_rest_api_key.yaml``. The methods below are
Python murni -- pemicu P1 (L-01/L-02): every one of them asserts the
*return value* of a method (``_generate_new_key()``,
``action_generate_key()``, ``_authenticate()``), never a field read off a
record in the YAML registry -- ``action: call`` in YAML discards a
method's return value entirely and ``asserts`` can only read fields on a
record already in the registry.
"""

from odoo_yaml_test import YamlTransactionCase

from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSsiRestApiKey(YamlTransactionCase):
    def setUp(self):
        super().setUp()
        self.profile = self.env["ssi_rest_access_profile"].create(
            {"name": "Python Test Profile", "code": "py_apikey_profile"}
        )

    def test_ssi_rest_api_key(self):
        self.run_yaml_scenario("test_data_ssi_rest_api_key.yaml")

    def test_generate_new_key_returns_raw_key_never_stored(self):
        """Python murni -- pemicu P1 (L-01/L-02: nilai balik method).

        ``_generate_new_key()`` is the only place the raw key value ever
        exists; this asserts its *return value* directly (never expressible
        in YAML) and proves the stored ``key_hash`` is not the raw key
        itself, only a hash of it.
        """
        record = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key",
                "user_id": self.env.user.id,
                "profile_id": self.profile.id,
            }
        )
        raw_key = record._generate_new_key()
        self.assertTrue(raw_key)
        self.assertTrue(record.key_hash)
        self.assertNotEqual(record.key_hash, raw_key)

    def test_regenerate_invalidates_previous_key(self):
        """Python murni -- pemicu P1 (L-01/L-02: nilai balik method).

        The old raw key must stop authenticating once a new one is
        generated; ``_authenticate()``'s return value (an empty vs.
        non-empty recordset) can only be asserted in Python.
        """
        record = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key",
                "user_id": self.env.user.id,
                "profile_id": self.profile.id,
            }
        )
        old_raw_key = record._generate_new_key()
        new_raw_key = record._generate_new_key()
        self.assertNotEqual(old_raw_key, new_raw_key)

        key_model = self.env["ssi_rest_api_key"]
        self.assertFalse(key_model._authenticate(old_raw_key))
        self.assertEqual(key_model._authenticate(new_raw_key), record)

    def test_authenticate_wrong_key_returns_empty_recordset(self):
        """Python murni -- pemicu P1 (L-01/L-02: nilai balik method)."""
        record = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key",
                "user_id": self.env.user.id,
                "profile_id": self.profile.id,
            }
        )
        record._generate_new_key()
        key_model = self.env["ssi_rest_api_key"]
        self.assertFalse(key_model._authenticate("sak_totally-not-the-key"))
        self.assertFalse(key_model._authenticate(""))
        self.assertFalse(key_model._authenticate(False))

    def test_action_generate_key_returns_notification_with_raw_key(self):
        """Python murni -- pemicu P1 (L-01/L-02: nilai balik method).

        ``action_generate_key()`` returns an ``ir.actions.client`` dict
        whose shape and message content can never be asserted through
        YAML's ``call`` action (return value discarded, L-01).
        """
        record = self.env["ssi_rest_api_key"].create(
            {
                "name": "Key",
                "user_id": self.env.user.id,
                "profile_id": self.profile.id,
            }
        )
        action = record.action_generate_key()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "display_notification")
        self.assertTrue(action["params"]["sticky"])
        # The raw key was embedded in the notification message returned to
        # the caller -- verify it actually authenticates against what got
        # persisted, proving the message really carried the real key, not
        # a placeholder.
        message = action["params"]["message"]
        raw_key = message.strip().splitlines()[-1]
        self.assertEqual(self.env["ssi_rest_api_key"]._authenticate(raw_key), record)
