# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the OpenAPI document and Swagger UI routes
(backlog issue #16).

Python murni — pemicu P7 (L-19): every scenario below drives the real
dispatcher (auth, the doc-group gate, the generated document itself)
through an actual HTTP request. Every test method gets its own fresh
``HttpCase.opener`` (framework guarantee, see backlog issue #10's module
docstring).
"""

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

# `SsiRestDispatcher.handle_error` (`ssi_rest_api/lib/dispatcher.py`) logs
# every error response at ERROR level regardless of which HTTP status it
# is — including the 401/403 responses deliberately triggered below — so
# it must be muted on every test expecting a non-2xx response, same
# pattern as `ssi_rest_api_introspection`'s own tests.
_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


@tagged("post_install", "-at_install")
class TestSsiRestApiDoc(HttpCase):
    def setUp(self):
        super().setUp()
        doc_group = self.env.ref("ssi_rest_api_doc.ssi_rest_openapi_group")
        self.doc_user = self.env["res.users"].create(
            {
                "name": "REST API Doc Test User",
                "login": "ssi_rest_api_doc_test_user@example.com",
                "email": "ssi_rest_api_doc_test_user@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, doc_group.id])
                ],
            }
        )
        self.doc_rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.doc_user)
            .sudo()
            ._generate(scope="rpc", name="doc test key", expiration_date=None)
        )
        self.plain_user = self.env["res.users"].create(
            {
                "name": "Plain Test User",
                "login": "ssi_rest_api_doc_plain_user@example.com",
                "email": "ssi_rest_api_doc_plain_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.plain_rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.plain_user)
            .sudo()
            ._generate(scope="rpc", name="plain test key", expiration_date=None)
        )

    def _headers(self, rpc_key):
        return {"Authorization": f"Bearer {rpc_key}"}

    def test_document_is_openapi_31_for_grouped_user(self):
        response = self.url_open(
            "/api/v1/openapi.json", headers=self._headers(self.doc_rpc_key)
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["openapi"].startswith("3.1"))

    def test_document_lists_dependency_operation_ids(self):
        response = self.url_open(
            "/api/v1/openapi.json", headers=self._headers(self.doc_rpc_key)
        )
        body = response.json()
        operation_ids = {
            operation["operationId"]
            for path_item in body["paths"].values()
            for operation in path_item.values()
        }
        # `ssi_rest_api_orm`'s `orm_read` (backlog issue #11).
        self.assertIn("read_orm_read_get", operation_ids)
        # `ssi_rest_api_introspection`'s `introspection_model_fields`
        # (backlog issue #12).
        self.assertIn("read_introspection_model_fields_get", operation_ids)

    def test_document_only_contains_requested_version_paths(self):
        response = self.url_open(
            "/api/v1/openapi.json", headers=self._headers(self.doc_rpc_key)
        )
        body = response.json()
        self.assertTrue(body["paths"])
        self.assertTrue(all(path.startswith("/api/v1/") for path in body["paths"]))

    def test_swagger_ui_page_references_internal_document_url(self):
        response = self.url_open(
            "/api/v1/openapi/ui", headers=self._headers(self.doc_rpc_key)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/v1/openapi.json", response.text)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_document_denies_user_without_doc_group(self):
        response = self.url_open(
            "/api/v1/openapi.json", headers=self._headers(self.plain_rpc_key)
        )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertIn("error", body)
        self.assertNotIn("paths", body)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_document_rejects_anonymous_request(self):
        response = self.url_open("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 401)

    def test_document_excludes_non_ssi_rest_routes(self):
        response = self.url_open(
            "/api/v1/openapi.json", headers=self._headers(self.doc_rpc_key)
        )
        body = response.json()
        self.assertFalse(any(path.startswith("/web") for path in body["paths"]))
        self.assertNotIn("/jsonrpc", body["paths"])
