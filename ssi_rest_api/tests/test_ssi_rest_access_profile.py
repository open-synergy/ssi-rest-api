# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo_yaml_test import YamlTransactionCase


@tagged("post_install", "-at_install")
class TestSsiRestAccessProfile(YamlTransactionCase):
    def test_ssi_rest_access_profile(self):
        self.run_yaml_scenario("test_data_ssi_rest_access_profile.yaml")

    def test_rule_ids_read_ordered_by_sequence(self):
        """Python murni — pemicu P3 (L-06: perbandingan o2m/m2m di YAML
        berbasis set, urutan baris tak pernah bisa di-assert)."""
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Order Profile",
                "code": "order_profile",
                "rule_ids": [
                    (0, 0, {"sequence": 30, "effect": "allow"}),
                    (0, 0, {"sequence": 10, "effect": "allow"}),
                    (0, 0, {"sequence": 20, "effect": "allow"}),
                ],
            }
        )
        self.assertEqual(profile.rule_ids.mapped("sequence"), [10, 20, 30])

    def test_deny_rule_with_lower_sequence_precedes_allow_rule(self):
        """Python murni — pemicu P3 (L-06), sama seperti di atas: urutan
        baris o2m setelah campuran sequence/effect."""
        profile = self.env["ssi_rest_access_profile"].create(
            {
                "name": "Precedence Profile",
                "code": "precedence_profile",
                "rule_ids": [
                    (0, 0, {"sequence": 20, "effect": "allow"}),
                    (0, 0, {"sequence": 10, "effect": "deny"}),
                ],
            }
        )
        self.assertEqual(profile.rule_ids[0].effect, "deny")
        self.assertEqual(profile.rule_ids[1].effect, "allow")

    def test_duplicate_code_rejected_by_database_constraint(self):
        """Python murni — pemicu P5 (L-22: keunikan code ditegakkan lewat
        models.Constraint, yaitu UNIQUE di level database yang muncul
        sebagai psycopg2.IntegrityError — tipe ini bukan salah satu dari
        12 tipe yang dikenali expect_error YAML)."""
        profile_model = self.env["ssi_rest_access_profile"]
        profile_model.create({"name": "Original", "code": "dup_code"})
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                profile_model.create({"name": "Duplicate", "code": "dup_code"})
