# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the binary download/upload endpoints
(backlog issue #13).

Python murni — pemicu P7 (L-19): every scenario drives the real
dispatcher (auth, ACL, ``ir.binary``/``http.Stream`` streaming) through
an actual HTTP request, which the YAML DSL cannot do at all. The
max-content-length test additionally uses ``mock.patch`` (P6, L-06) to
shrink the module's upload cap instead of sending a real multi-megabyte
payload. Every test method gets its own fresh ``HttpCase.opener``
(framework guarantee, see backlog issue #10's module docstring).
"""

import base64
import io
from unittest import mock

from PIL import Image

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api_binary.controllers import main as binary_main

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


def _make_png(width, height, color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


@tagged("post_install", "-at_install")
class TestSsiRestApiBinary(HttpCase):
    def setUp(self):
        super().setUp()
        self.png_content = _make_png(40, 30)
        self.manager_user = self.env["res.users"].create(
            {
                "name": "Binary Test Manager",
                "login": "ssi_rest_api_binary_manager@example.com",
                "email": "ssi_rest_api_binary_manager@example.com",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("base.group_partner_manager").id,
                        ],
                    )
                ],
            }
        )
        self.reader_user = self.env["res.users"].create(
            {
                "name": "Binary Test Reader",
                "login": "ssi_rest_api_binary_reader@example.com",
                "email": "ssi_rest_api_binary_reader@example.com",
                # `base.group_user` alone only grants *read* on
                # res.partner — deliberate, exercises the write-denied
                # scenario below.
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.manager_key = (
            self.env["res.users.apikeys"]
            .with_user(self.manager_user)
            .sudo()
            ._generate(scope="rpc", name="binary manager key", expiration_date=None)
        )
        self.reader_key = (
            self.env["res.users.apikeys"]
            .with_user(self.reader_user)
            .sudo()
            ._generate(scope="rpc", name="binary reader key", expiration_date=None)
        )
        self.partner = self.env["res.partner"].create(
            {
                "name": "Binary Fixture Partner",
                "image_1920": base64.b64encode(self.png_content),
            }
        )

    def _headers(self, key):
        return {"Authorization": f"Bearer {key}"}

    def _download_url(self, model, res_id):
        return f"/api/v1/binary/{model}/{res_id}"

    def test_download_returns_binary_content_with_etag(self):
        response = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.manager_key),
            params={"field": "image_1920"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.png_content)
        self.assertTrue(response.headers.get("ETag"))

    def test_download_conditional_request_returns_304(self):
        first = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.manager_key),
            params={"field": "image_1920"},
        )
        etag = first.headers["ETag"]
        second = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers={**self._headers(self.manager_key), "If-None-Match": etag},
            params={"field": "image_1920"},
        )
        self.assertEqual(second.status_code, 304)

    def test_download_with_resize_and_crop_returns_requested_dimensions(self):
        response = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.manager_key),
            params={"field": "image_1920", "width": 20, "height": 20, "crop": 1},
        )
        self.assertEqual(response.status_code, 200)
        resized = Image.open(io.BytesIO(response.content))
        self.assertEqual(resized.size, (20, 20))

    def test_upload_writes_binary_field(self):
        other_content = _make_png(10, 10, color=(0, 255, 0))
        response = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.manager_key),
            data={"field": "image_1920"},
            files={"file": ("avatar.png", other_content, "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["field"], "image_1920")
        self.partner.invalidate_recordset(["image_1920"])
        self.assertEqual(
            base64.b64decode(self.partner.image_1920), other_content
        )

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_download_unreadable_record_is_403(self):
        denied_partner = self.env["res.partner"].create({"name": "Denied Partner"})
        self.env["ir.rule"].create(
            {
                "name": "ssi_rest_api_binary test: deny one partner",
                "model_id": self.env.ref("base.model_res_partner").id,
                "domain_force": f"[('id', '!=', {denied_partner.id})]",
                "groups": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        response = self.url_open(
            self._download_url("res.partner", denied_partner.id),
            headers=self._headers(self.manager_key),
            params={"field": "image_1920"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "access_denied")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_download_non_binary_field_is_422(self):
        response = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.manager_key),
            params={"field": "name"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_upload_exceeding_max_content_length_is_413(self):
        with mock.patch.object(binary_main, "MAX_UPLOAD_CONTENT_LENGTH", 10):
            response = self.url_open(
                self._download_url("res.partner", self.partner.id),
                headers=self._headers(self.manager_key),
                data={"field": "image_1920"},
                files={"file": ("avatar.png", self.png_content, "image/png")},
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "payload_too_large")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_upload_without_write_access_is_403_and_record_unchanged(self):
        original = self.partner.image_1920
        response = self.url_open(
            self._download_url("res.partner", self.partner.id),
            headers=self._headers(self.reader_key),
            data={"field": "image_1920"},
            files={"file": ("avatar.png", _make_png(5, 5), "image/png")},
        )
        self.assertEqual(response.status_code, 403)
        self.partner.invalidate_recordset(["image_1920"])
        self.assertEqual(self.partner.image_1920, original)
