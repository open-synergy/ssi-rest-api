# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""HTTP-level tests for the ``ssi_rest`` dispatcher, exercised through the
throwaway ``/api/v1/ping`` endpoint (see ``controllers/main.py``).

Python murni — pemicu P7 (L-19): ``odoo-yaml-test``'s base class is locked
to ``TransactionCase``; issuing a real HTTP request (headers, mimetype-
driven body parsing, status codes) is not something the YAML DSL has any
action for at all.

Each test method gets a fresh ``requests``-backed session: ``HttpCase``
creates ``self.opener`` from scratch in ``setUp()``, which unittest runs
before every test method, so no ``session_id`` cookie ever survives across
these tests (a stale cookie would make an auth-sensitive check pass for the
wrong reason).
"""

from odoo.tests import HttpCase, tagged

from odoo.addons.ssi_rest_api.lib.dispatcher import REQUEST_ID_HEADER


@tagged("post_install", "-at_install")
class TestSsiRestDispatcher(HttpCase):
    def test_get_returns_2xx_with_request_id_header(self):
        response = self.url_open("/api/v1/ping")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get(REQUEST_ID_HEADER))

    def test_post_json_body_is_parsed_like_json2(self):
        response = self.url_open("/api/v1/ping", json={"echo": "hello-json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["echo"], "hello-json")

    def test_post_multipart_form_data_is_not_a_500(self):
        response = self.url_open(
            "/api/v1/ping",
            data={"echo": "hello-form"},
            files={"upload": ("dummy.txt", b"dummy content")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["echo"], "hello-form")

    def test_two_requests_get_different_request_ids(self):
        first = self.url_open("/api/v1/ping")
        second = self.url_open("/api/v1/ping")
        self.assertNotEqual(
            first.headers.get(REQUEST_ID_HEADER),
            second.headers.get(REQUEST_ID_HEADER),
        )

    def test_unregistered_version_is_404_not_500(self):
        response = self.url_open("/api/v9/ping")
        self.assertEqual(response.status_code, 404)
