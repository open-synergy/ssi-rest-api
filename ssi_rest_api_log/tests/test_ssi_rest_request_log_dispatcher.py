# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""HTTP-level tests for the request-log-writing dispatcher override
(backlog issue #15).

Python murni -- pemicu P7 (L-19): ``odoo-yaml-test``'s base class is
locked to ``TransactionCase``; a real HTTP round-trip (headers, auth,
status codes, and observing that our own log write never forces a
RO->RW retry) is not something the YAML DSL has any action for at all.
The log-write-failure test additionally is P6 (L-15: no mock/patch from
YAML) -- it patches the dispatcher's own write method to prove a
logging failure never leaks into the client response.

Every call below goes through ``HttpCase.url_open``/``self.opener``
(**not** a bare ``requests.Session()``): Odoo 19's own test harness
rejects any request that does not carry the special ``test_request_key``
cookie ``Opener.request`` sets automatically via
``HttpCase.allow_requests()`` (``odoo/tests/common.py``) with a bare
``400`` -- "has been ignored during test". ``self.opener`` is recreated
fresh in ``setUp()`` for every test *method*, and each method below
issues exactly one relevant request, so there is no risk of a stale
session cookie silently authenticating a request meant to prove "no
credential -> 401" (the scenario a fresh-session-per-case would guard
against) -- this is also the same pattern every other HTTP test in this
repo already uses (``test_rest_auth.py``, ``test_core_regression_suite.py``).

Two test-only routes are needed, not one: ``/test/log/echo`` (default
``readonly=False``) is used for every scenario that inspects the
persisted log row, and ``/test/log/readonly-probe``
(``readonly=True``) exists *only* to prove the no-retry property via a
call counter. They cannot share a route: under Odoo's own ``HttpCase``
test harness, a ``readonly=True`` request's log write is a structural
no-op (see ``lib/dispatcher.py``'s
``SsiRestDispatcher._skip_logging_under_test_harness`` docstring) -- so
asserting a log row exists for ``echo`` requires it to run
read/write, exactly like almost every other ``ssi_rest`` endpoint in
this module family (see ``ssi_rest_api_orm``'s ``orm_create``/
``orm_write``).
"""

from unittest.mock import patch

from odoo import http
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api.lib.routing import rest_route
from odoo.addons.ssi_rest_api_log.lib.dispatcher import SsiRestDispatcher

#: `SsiRestDispatcher.handle_error` (both the core `ssi_rest_api` base
#: class and this module's override) logs every error response at ERROR
#: level, including the 401 these tests deliberately trigger -- same
#: convention as `ssi_rest_api`'s own HTTP tests (see e.g.
#: `test_rest_auth_basic_bearer.py`).
_CORE_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"
_LOG_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api_log.lib.dispatcher"


class _CallCounter:
    def __init__(self):
        self.count = 0


#: Module-level so the readonly-probe controller (registered once, at
#: import time) and the test method that reads it after the HTTP round
#: trip agree on the same object; reset in `setUp` below.
_readonly_probe_calls = _CallCounter()


class SsiRestApiLogTestController(http.Controller):
    """Test-only scaffolding (backlog issue #15), isolated under
    ``/test/log/`` -- same rationale as ``ssi_rest_api``'s own
    ``test_rest_auth.py``/``test_core_regression_suite.py`` test
    controllers: never part of the real endpoint surface."""

    @rest_route(["/test/log/echo"], auth="ssi_rest", operation="read")
    def echo(self, **kwargs):
        return {"echo": kwargs}

    @rest_route(
        ["/test/log/readonly-probe"],
        auth="ssi_rest",
        operation="read",
        readonly=True,
    )
    def readonly_probe(self, **kwargs):
        _readonly_probe_calls.count += 1
        return {"ok": True}


@tagged("post_install", "-at_install")
class TestSsiRestRequestLogDispatcher(HttpCase):
    def setUp(self):
        super().setUp()
        _readonly_probe_calls.count = 0
        self.test_user = self.env["res.users"].create(
            {
                "name": "Request Log HTTP Test User",
                "login": "ssi_rest_request_log_http_user@example.com",
                "email": "ssi_rest_request_log_http_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="request log test key", expiration_date=None)
        )

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def _log_for(self, request_id):
        return (
            self.env["ssi_rest_request_log"]
            .sudo()
            .search([("request_id", "=", request_id)])
        )

    def test_successful_request_creates_log_row(self):
        response = self.url_open(
            "/api/v1/test/log/echo",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        request_id = response.headers.get("X-Request-Id")
        self.assertTrue(request_id)

        log = self._log_for(request_id)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status_code, 200)
        self.assertGreater(log.duration_ms, 0.0)
        self.assertEqual(log.user_id, self.test_user)

    @mute_logger(_CORE_DISPATCHER_LOGGER, "odoo.http")
    def test_auth_failure_creates_log_row_with_401_and_error_code(self):
        """Asserts on the ``vals`` this dispatcher builds for the log
        row, not a row read back afterward.

        An auth failure never reaches ``env.cr.commit()``
        (``service/model.py:retrying`` only commits on the success
        path; ``RestAuthError`` propagates straight through its outer
        ``except Exception: ... raise``), so under Odoo's own
        ``HttpCase`` test harness the *outer* request ``TestCursor``
        rolls back its savepoint on close -- and that rollback also
        undoes our nested, already-"committed" log-write savepoint:
        released savepoints are not independent of an *enclosing*
        savepoint's later rollback, only a real top-level ``COMMIT``
        (which never happens here) would be. This is a structural
        limitation of the test harness, not of this module -- in
        production the log write goes through a genuinely independent
        connection, immune to the failed request's own rollback.
        """
        captured = {}
        original_build_vals = SsiRestDispatcher._build_log_vals

        def _spy(dispatcher_self, response, error_code):
            vals = original_build_vals(dispatcher_self, response, error_code)
            captured.update(vals)
            return vals

        with patch.object(SsiRestDispatcher, "_build_log_vals", _spy):
            response = self.url_open("/api/v1/test/log/echo")

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers.get("X-Request-Id"))
        self.assertEqual(captured.get("status_code"), 401)
        self.assertTrue(captured.get("error_code"))

    def test_readonly_route_is_not_retried_ro_to_rw(self):
        response = self.url_open(
            "/api/v1/test/log/readonly-probe",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        # If the log write in `post_dispatch` had gone through the
        # request's own (possibly read-only) cursor instead of a
        # separate one, PostgreSQL would raise
        # `ReadOnlySqlTransaction`, and `Request._serve_db` (core)
        # would transparently re-run the *entire* request -- including
        # the endpoint itself -- against a fresh read/write cursor. A
        # call count of exactly 1 is the observable proof that never
        # happened.
        self.assertEqual(_readonly_probe_calls.count, 1)

    @mute_logger(_LOG_DISPATCHER_LOGGER)
    def test_log_write_failure_does_not_change_client_response(self):
        with patch(
            "odoo.addons.ssi_rest_api_log.lib.dispatcher."
            "SsiRestDispatcher._do_write_request_log",
            side_effect=RuntimeError("boom"),
        ):
            response = self.url_open(
                "/api/v1/test/log/echo",
                headers=self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["echo"], {})
