# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Retention test for ``ssi_rest_request_log._gc_expired_request_log``
(backlog issue #15).

Python murni -- pemicu P10 (L-09..L-11: no YAML action can execute raw
SQL, and ``create_date`` is not writable through a normal
``create()``/``write()`` call at all -- backdating a row's
``create_date`` to simulate an "old" log entry needs a real ``UPDATE``
statement, which is out of reach for ``EVAL:``'s narrow whitelist).
"""

from datetime import timedelta

from odoo.fields import Datetime
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSsiRestRequestLogGc(TransactionCase):
    def _create_log(self, request_id):
        return (
            self.env["ssi_rest_request_log"]
            .sudo()
            .create(
                {
                    "request_id": request_id,
                    "http_method": "GET",
                    "path": "/api/v1/ping",
                    "status_code": 200,
                }
            )
        )

    def _backdate(self, record, days):
        self.env.cr.execute(
            "UPDATE ssi_rest_request_log SET create_date = %s WHERE id = %s",
            (Datetime.now() - timedelta(days=days), record.id),
        )

    def test_gc_deletes_only_rows_older_than_retention(self):
        old_log = self._create_log("gc-old")
        new_log = self._create_log("gc-new")
        self._backdate(old_log, days=40)
        self._backdate(new_log, days=5)
        self.env["ir.config_parameter"].sudo().set_param(
            "ssi_rest_api.log_retention_days", "30"
        )

        self.env["ssi_rest_request_log"]._gc_expired_request_log()

        self.assertFalse(old_log.exists())
        self.assertTrue(new_log.exists())
