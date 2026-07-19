# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from psycopg2 import IntegrityError

from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo_yaml_test import YamlTransactionCase


@tagged("post_install", "-at_install")
class TestSsiRestEndpoint(YamlTransactionCase):
    def test_ssi_rest_endpoint(self):
        self.run_yaml_scenario("test_data_ssi_rest_endpoint.yaml")

    @mute_logger("odoo.sql_db")
    def test_duplicate_path_is_rejected_at_db_level(self):
        """Python murni — pemicu P5 (L-22: `psycopg2.IntegrityError`, di
        luar 12 tipe yang dikenali `expect_error`, untuk constraint
        UNIQUE `path` yang didefinisikan lewat `models.Constraint` — lihat
        11-version-matrix.md §9). `code="/"` dipakai di kedua record agar
        yang diuji murni constraint `path`, bukan constraint `code` milik
        mixin (yang mengabaikan code `"/"`). `mute_logger("odoo.sql_db")`
        membungkam baris ERROR yang NORMAL dituliskan PostgreSQL di sini;
        tanpa itu `oca_checklog_odoo` menggagalkan CI walau test-nya
        sendiri lulus.
        """
        model_id = self.env.ref("base.model_res_partner").id
        self.env["ssi_rest_endpoint"].create(
            {
                "name": "Dup Path A",
                "code": "/",
                "path": "dummy/dup-path",
                "http_method": "GET",
                "handler_type": "model_method",
                "model_id": model_id,
                "method_name": "read",
            }
        )
        with self.assertRaises(IntegrityError):
            self.env["ssi_rest_endpoint"].create(
                {
                    "name": "Dup Path B",
                    "code": "/",
                    "path": "dummy/dup-path",
                    "http_method": "GET",
                    "handler_type": "model_method",
                    "model_id": model_id,
                    "method_name": "read",
                }
            )
