# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Extends ``ssi_rest_api``'s :class:`SsiRestDispatcher` (registered under
``_dispatchers['ssi_rest']`` by ``odoo.http.Dispatcher.__init_subclass__``)
so every request/response is persisted as one ``ssi_rest_request_log`` row.

Subclassing the core dispatcher and re-registering under the same
``routing_type`` -- rather than monkey-patching or editing
``ssi_rest_api``'s own ``lib/dispatcher.py`` -- is the officially supported
Odoo 19 extension seam for this class (``_dispatchers`` is a plain
class-level registry keyed by ``routing_type``, last import wins; see the
core module's own docstring). Because ``ssi_rest_api_log`` ``depends`` on
``ssi_rest_api``, Odoo fully imports ``ssi_rest_api`` -- including its own
``lib/dispatcher`` import, which performs the *first* registration --
before this package is imported at all, so by the time this module's
``class SsiRestDispatcher(...)`` statement below runs, replacing the
registry entry is safe and deterministic.

BINDING (do not remove this comment when editing this file, see backlog
issue #15's Keputusan Desain): a row is written through
``env.registry.cursor()`` -- a cursor/transaction entirely independent of
the request's own ``env.cr`` -- and committed on success, **never** through
``self.request.env.cr``. Writing through the request's own cursor on a
``readonly=True`` route would raise ``psycopg2.errors.ReadOnlySqlTransaction``
on every single request, which ``Request._serve_db`` (core) recovers from
by re-running the *entire* request (auth, dispatch, endpoint, ...) against
a fresh read/write cursor -- silently doubling latency and, for a
non-idempotent endpoint, its side effects. Verified against Odoo 19 core
(``odoo/http.py``): ``Dispatcher.post_dispatch``/``handle_error`` both run
*inside* the same ``service_model.retrying(serve_func, env=self.env)`` call
as the endpoint itself (``Request._serve_ir_http``), so anything written
through ``self.request.env.cr`` here is subject to exactly that retry.

Logging itself must never change what the client receives: every write
below is wrapped so a failure is logged server-side and swallowed, never
re-raised into the response path (binding, same Keputusan Desain).

Test-only wrinkle (see :meth:`SsiRestDispatcher._skip_logging_under_test_harness`):
Odoo's own ``HttpCase`` test harness makes *every* cursor in a test share
one physical connection via nested savepoints, and that layer refuses to
open a read/write nested cursor on top of a read-only one. A
``readonly=True`` route therefore cannot have its log row written while
running under a test -- this is a structural limitation of Odoo's test
harness, not of this module; the log write happens exactly as designed
in production, on every route, readonly or not.
"""

import json
import logging
import time

from odoo import SUPERUSER_ID, api

from odoo.addons.ssi_rest_api.lib.dispatcher import (
    SsiRestDispatcher as _CoreSsiRestDispatcher,
)
from odoo.addons.ssi_rest_api.lib.errors import classify_exception

_logger = logging.getLogger(__name__)

#: ``ir.config_parameter`` key gating whether the (always redacted) request
#: body is persisted at all. Default off (already seeded by ssi_rest_api's
#: own ``data/ir_config_parameter_data.xml``).
ICP_LOG_BODY = "ssi_rest_api.log_body"

#: Hard cap on the persisted (already-redacted) request body, so a huge
#: payload never bloats this log table unbounded.
_MAX_BODY_CHARS = 10000

#: Key names (case-insensitive) whose value is never persisted, even when
#: ``ICP_LOG_BODY`` is enabled -- binding, backlog issue #15's Keputusan
#: Desain ("Nilai kredensial, token, dan password tidak pernah tersimpan
#: mentah").
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "otp",
    }
)

#: Recursion guard for :func:`_redact` -- a request body is JSON, never
#: self-referential, but a pathological/very deep payload must not blow the
#: stack while redacting it.
_MAX_REDACT_DEPTH = 8


def _redact(value, depth=0):
    """Return ``value`` with every dict key in :data:`_SENSITIVE_KEYS`
    (case-insensitive) replaced by ``"***"``, recursively."""
    if depth > _MAX_REDACT_DEPTH:
        return "***"
    if isinstance(value, dict):
        return {
            key: (
                "***"
                if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS
                else _redact(val, depth + 1)
            )
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value]
    return value


def _estimate_record_count(response):
    """Best-effort guess at how many records ``response``'s JSON body
    carries, for the log's ``record_count`` column. Never raises: an
    unparsable/non-JSON body (e.g. a binary download) simply counts 0.
    """
    try:
        data = response.get_data()
        if not data:
            return 0
        payload = json.loads(data)
    except Exception:  # noqa: BLE001 - never let this break the response
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        length = payload.get("length")
        if isinstance(length, int):
            return length
        for key in ("records", "ids", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        if "id" in payload:
            return 1
    return 0


class SsiRestDispatcher(_CoreSsiRestDispatcher):
    """``ssi_rest`` dispatcher that additionally persists a
    ``ssi_rest_request_log`` row per request, on both the success
    (:meth:`post_dispatch`) and error (:meth:`handle_error`) paths -- the
    only two points every ``ssi_rest`` request passes through exactly
    once, whichever way it ends (see module docstring above for why
    ``post_dispatch``/``handle_error`` are each called exactly once per
    client-visible response, even under ``service_model.retrying``).
    """

    def __init__(self, request):
        super().__init__(request)
        # Set as early as possible (before authentication even runs) so
        # `duration_ms` reflects the full request, including an
        # authentication failure -- `pre_dispatch` below only runs
        # *after* authentication succeeds (see `_serve_ir_http`, core).
        self._log_start_time = time.monotonic()
        self._log_rule = None
        self._log_args = None

    def pre_dispatch(self, rule, args):
        result = super().pre_dispatch(rule, args)
        # Only reached once authentication (and access-profile
        # enforcement) already passed; an auth/profile failure leaves
        # these `None`, and `_write_request_log` below degrades
        # gracefully (empty `route_pattern`/`model_name`/`method_name`).
        self._log_rule = rule
        self._log_args = args
        return result

    def post_dispatch(self, response):
        result = super().post_dispatch(response)
        self._write_request_log(response)
        return result

    def handle_error(self, exc):
        response = super().handle_error(exc)
        # `handle_error` (core `Dispatcher.handle_error`, overridden by
        # `ssi_rest_api`) short-circuits to an already-built response for
        # an `HTTPException` carrying one (e.g. the CORS pre-flight 204
        # from `Dispatcher.pre_dispatch`, see `lib/dispatcher.py` in
        # `ssi_rest_api`) -- that is a deliberate result, not a failure,
        # so it must never be classified as an error code.
        error_code = None
        status_code = getattr(response, "status_code", None)
        if status_code is None or status_code >= 400:
            try:
                _status, error_code, _message = classify_exception(exc)
            except Exception:  # noqa: BLE001 - never break the response
                error_code = None
        self._write_request_log(response, error_code=error_code)
        return response

    def _write_request_log(self, response, error_code=None):
        if self._skip_logging_under_test_harness():
            return
        try:
            self._do_write_request_log(response, error_code)
        except Exception:  # noqa: BLE001 - never break the client response
            _logger.exception("ssi_rest_api_log: failed to persist request log entry")

    def _skip_logging_under_test_harness(self):
        """Whether attempting a log write right now would hit a
        structural limitation of Odoo's own ``HttpCase`` test harness,
        unrelated to this module's own correctness.

        Odoo's test-mode ``registry.cursor()`` (patched by
        ``odoo.tests.common._registry_test_mode_patches``) never opens a
        genuinely independent connection: every cursor in a test shares
        *one* physical connection via nested savepoints
        (``odoo.tests.test_cursor.TestCursor``), and that layer
        deliberately refuses to open a **read/write** nested cursor while
        the *currently active* one is **read-only**
        (``TestCursor._check_cursor_readonly``, raises "Opening a
        read/write test cursor from a readonly one") -- there is no way
        to satisfy both "independent transaction" and "single shared
        connection" at once. This is exactly the scenario a
        ``readonly=True`` route (e.g. the ``/test/log/readonly-probe``
        test route) puts every request in.

        This never applies in production: outside tests,
        ``registry.cursor()`` always opens a genuinely separate
        connection (from the pool, or the read replica if configured),
        so the log row is written exactly as this module's Keputusan
        Desain requires, on every route, readonly or not.
        """
        request = self.request
        cr = getattr(request.env, "cr", None)
        if cr is None or not getattr(cr, "readonly", False):
            return False
        from odoo import modules  # local import: test-mode flag only

        if not modules.module.current_test:
            return False
        _logger.debug(
            "ssi_rest_api_log: skipping request log write for a "
            "read-only cursor request under Odoo's own HttpCase test "
            "harness (nested read/write test cursors from a read-only "
            "one are not supported there); unaffected in production."
        )
        return True

    def _do_write_request_log(self, response, error_code):
        request = self.request
        if not request.db:
            # Only db-bound requests are ever routed through the ssi_rest
            # dispatcher in practice, but guard anyway: no registry, no
            # log row.
            return

        vals = self._build_log_vals(response, error_code)

        # BINDING: a brand-new cursor/transaction from the same registry,
        # never `request.env.cr` -- see module docstring.
        with request.env.registry.cursor() as cr:
            log_env = api.Environment(cr, SUPERUSER_ID, {})
            log_env["ssi_rest_request_log"].create(vals)

    def _build_log_vals(self, response, error_code):
        request = self.request
        duration_ms = (time.monotonic() - self._log_start_time) * 1000.0

        routing = self._log_rule.endpoint.routing if self._log_rule else {}
        args = self._log_args or {}
        model_name = args.get("model") or routing.get("rest_model") or None
        method_name = args.get("method") or routing.get("rest_operation") or None
        route_pattern = self._log_rule.rule if self._log_rule else None

        rest_auth = getattr(request, "rest_auth", None)
        auth_scheme = getattr(rest_auth, "scheme", None)

        try:
            status_code = response.status_code
        except AttributeError:
            status_code = None

        try:
            response_size = len(response.get_data())
        except Exception:  # noqa: BLE001
            response_size = 0

        httprequest = request.httprequest
        user_agent = httprequest.user_agent.string if httprequest.user_agent else None

        return {
            "request_id": self._ensure_request_id(),
            "user_id": request.env.uid or None,
            "auth_scheme": auth_scheme,
            "http_method": httprequest.method,
            "path": httprequest.path,
            "route_pattern": route_pattern,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "remote_addr": httprequest.remote_addr,
            "user_agent": user_agent,
            "model_name": model_name,
            "method_name": method_name,
            "record_count": _estimate_record_count(response),
            "error_code": error_code,
            "request_body": self._redacted_request_body(),
            "response_size": response_size,
        }

    def _redacted_request_body(self):
        """Return the redacted, size-capped request body as a JSON
        string, or ``False`` when ``ICP_LOG_BODY`` is disabled, no body
        was parsed (e.g. authentication failed before ``dispatch()``
        ever ran), or the body can't be serialised back to JSON.

        Reads the ICP through the private, ACL-free ``_get_param`` (a
        plain ``SELECT``, safe on a read-only cursor -- unlike the
        actual log row write, this never needs the separate cursor from
        :meth:`_do_write_request_log`) rather than ``sudo()``, the same
        style ``ssi_rest_api_orm``'s own endpoint helpers use.
        """
        icp = self.request.env["ir.config_parameter"]
        if icp._get_param(ICP_LOG_BODY) != "True":
            return False
        params = getattr(self.request, "params", None)
        if not params:
            return False
        try:
            body = json.dumps(_redact(params))
        except (TypeError, ValueError):
            return False
        if len(body) > _MAX_BODY_CHARS:
            body = body[:_MAX_BODY_CHARS]
        return body
