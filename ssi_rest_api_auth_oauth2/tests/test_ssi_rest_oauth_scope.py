# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo_yaml_test import YamlTransactionCase
from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestSsiRestOauthScope(YamlTransactionCase):
    def test_ssi_rest_oauth_scope(self):
        self.run_yaml_scenario("test_data_ssi_rest_oauth_scope.yaml")

    @mute_logger("odoo.sql_db")
    def test_code_must_be_unique(self):
        """Python murni -- pemicu P5 (L-22: sebuah pelanggaran UNIQUE
        constraint (models.Constraint) mengangkat psycopg2.IntegrityError,
        di luar 12 tipe yang dikenali expect_error YAML).
        mute_logger("odoo.sql_db") membungkam baris ERROR yang NORMAL
        dituliskan PostgreSQL di sini; tanpa itu oca_checklog_odoo
        menggagalkan CI walau test-nya sendiri lulus.
        """
        self.env["ssi_rest_oauth_scope"].create(
            {"name": "Read Partner", "code": "read:partner"}
        )
        with self.assertRaises(IntegrityError):
            self.env["ssi_rest_oauth_scope"].create(
                {"name": "Read Partner Again", "code": "read:partner"}
            )

    @mute_logger("odoo.sql_db")
    def test_name_is_required(self):
        """Python murni -- pemicu P5 (L-22: field name required=True tanpa
        default punya kolom NOT NULL di database tapi tidak ada validasi
        Python-level yang mengangkat ValidationError sebelum INSERT --
        yang terangkat adalah psycopg2.IntegrityError (NotNullViolation),
        di luar 12 tipe yang dikenali expect_error YAML).
        """
        with self.assertRaises(IntegrityError):
            self.env["ssi_rest_oauth_scope"].create({"code": "no:name"})
