# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the built-in Basic and Bearer providers
(``models/ssi_rest_auth_basic.py``, ``models/ssi_rest_auth_bearer.py``).

Python murni — pemicu P7 (L-19: ``odoo-yaml-test``'s base class is locked to
``TransactionCase``, a real HTTP request/response cycle — including
inspecting response headers and driving the RO/RW cursor retry machinery —
is out of reach).

Both providers are already registered (``data/ssi_rest_auth_scheme_data.xml``,
loaded by every install), so unlike backlog item #4's core auth-method
tests, no additional ``ssi_rest_auth_scheme`` record needs to be created
here.

Note on the "Basic + Bearer credentials at once" scenario from this
backlog item's ``## Skenario Uji``: both providers read the *same*
``Authorization`` header and match mutually exclusive prefixes (``"Basic
"`` vs. ``"Bearer "``, see `Keputusan Desain`). A single header value can
only ever start with one of the two, so a real request carrying both
providers' credentials simultaneously is not constructible — the generic
``multiple_credentials`` (400) mechanism itself is already covered with
mocked dummy providers in backlog item #4's ``test_rest_auth.py``.
"""

import base64
import datetime

from odoo import http
from odoo.http import request
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"

#: Populated (in-process, not persisted) by `test_auth_readonly` below, to
#: prove the endpoint runs exactly once under `readonly=True` when
#: authenticated via Basic (no `_update_last_login` write to force a
#: RO->RW cursor retry).
_READONLY_ENDPOINT_CALLS = []


class SsiRestAuthBasicBearerTestController(http.Controller):
    """Test-only scaffolding — see `test_rest_error_envelope.py`'s module
    docstring for the rationale of defining it here rather than in
    `controllers/main.py`."""

    @rest_route(["/test-auth-basic-bearer"], auth="ssi_rest")
    def test_auth(self, **kwargs):
        auth = request.rest_auth
        return {"uid": auth.uid, "scheme": auth.scheme}

    @rest_route(["/test-auth-readonly"], auth="ssi_rest", readonly=True)
    def test_auth_readonly(self, **kwargs):
        _READONLY_ENDPOINT_CALLS.append(1)
        return {"uid": request.rest_auth.uid}


def _basic_header(login, password):
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _bearer_header(token):
    return {"Authorization": f"Bearer {token}"}


@tagged("post_install", "-at_install")
class TestSsiRestAuthBasicBearer(HttpCase):
    def setUp(self):
        super().setUp()
        _READONLY_ENDPOINT_CALLS.clear()
        self.password = "Sup3rSecret!"
        self.test_user = self.env["res.users"].create(
            {
                "name": "SSI REST Basic User",
                "login": "ssi_rest_basic_user@example.com",
                "email": "ssi_rest_basic_user@example.com",
                "password": self.password,
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="rpc key", expiration_date=None)
        )
        self.wrong_scope_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="not_rpc", name="wrong scope key", expiration_date=None)
        )

    def test_basic_valid_password_authenticates(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_basic_header(self.test_user.login, self.password),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["uid"], self.test_user.id)
        self.assertEqual(body["scheme"], "basic")

    def test_basic_with_api_key_as_password_authenticates(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_basic_header(self.test_user.login, self.rpc_key),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["uid"], self.test_user.id)

    def test_bearer_valid_key_authenticates(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_bearer_header(self.rpc_key),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["uid"], self.test_user.id)
        self.assertEqual(body["scheme"], "bearer")

    def test_basic_on_readonly_route_executes_endpoint_once(self):
        # Regression (binding): `_check_uid_passwd` never writes, so a
        # `readonly=True` route authenticated via Basic must stay on the
        # RO cursor for the whole request — no `_update_last_login` write
        # to force Odoo's RO->RW retry, which would otherwise run the
        # endpoint (and therefore append to `_READONLY_ENDPOINT_CALLS`)
        # twice.
        response = self.url_open(
            "/api/v1/test-auth-readonly",
            headers=_basic_header(self.test_user.login, self.password),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(_READONLY_ENDPOINT_CALLS), 1)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_no_authorization_header_is_401_not_500(self):
        # `_rest_auth_extract()` on both providers must return `None`
        # (never raise/query the DB) when the request carries no
        # `Authorization` header at all — asserted indirectly through a
        # real request, since `_rest_auth_extract` reads the
        # process-global `odoo.http.request` proxy and is only bound
        # during an actual served request (not from a bare method call).
        response = self.url_open("/api/v1/test-auth-basic-bearer")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_basic_wrong_password_is_401_without_bearer_fallthrough(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_basic_header(self.test_user.login, "not-the-password"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_basic_unknown_login_is_401_with_generic_message(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_basic_header("no-such-login@example.com", "whatever"),
        )
        self.assertEqual(response.status_code, 401)
        error = response.json()["error"]
        self.assertEqual(error["code"], "invalid_credential")
        self.assertNotIn("no-such-login", error["message"])

    @mute_logger(_DISPATCHER_LOGGER)
    def test_bearer_random_token_is_401(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_bearer_header("not-a-real-key"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_bearer_wrong_scope_key_is_401(self):
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_bearer_header(self.wrong_scope_key),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")

    @mute_logger(_DISPATCHER_LOGGER)
    def test_bearer_expired_key_is_401(self):
        expired_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(
                scope="rpc",
                name="expired key",
                expiration_date=datetime.datetime.now() - datetime.timedelta(days=1),
            )
        )
        response = self.url_open(
            "/api/v1/test-auth-basic-bearer",
            headers=_bearer_header(expired_key),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "invalid_credential")
