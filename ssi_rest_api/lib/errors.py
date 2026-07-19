# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Error envelope helpers for the ``ssi_rest`` dispatcher.

Every failed ``ssi_rest`` request is rendered as exactly one body shape::

    {"error": {"code", "message", "status", "request_id", "details"}}

``code`` is a stable machine string (never a Python exception class path), so
clients can branch on it without depending on server-side implementation
details. This module intentionally never touches
``odoo.http.serialize_exception()``: that helper always embeds a full
Python traceback under the ``debug`` key, which is not fit for a public
error response (see :func:`traceback_disclosure_allowed` for the one
narrow, opt-in exception to that rule).

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by (see ``lib/dispatcher.py`` module docstring for the full
rationale).
"""

import traceback

from odoo.exceptions import (
    AccessDenied,
    AccessError,
    LockError,
    MissingError,
    UserError,
)

#: ``ir.config_parameter`` key gating traceback disclosure in the error
#: envelope. Kept off by default (see ``data/ir_config_parameter_data.xml``);
#: even when on, :func:`traceback_disclosure_allowed` still requires the
#: requesting user to be in ``base.group_system``.
ICP_EXPOSE_TRACEBACK = "ssi_rest_api.expose_traceback"

#: Messages that must never repeat whatever ``str(exc)`` says, because the
#: underlying Odoo exception message is not safe to expose to a REST client.
_GENERIC_MESSAGES = {
    # `AccessError`/`AccessDenied` messages routinely name the model and/or
    # field the user was denied access to; that is exactly the kind of
    # internal detail a REST client must not learn from a 403.
    "access_denied": "You are not allowed to perform this action.",
    # Catch-all bucket: the exception itself is unknown/unclassified, so its
    # message could be anything (a raw SQL error, a Python internals
    # message, ...) and is never safe to forward as-is.
    "internal_error": "An unexpected error occurred while processing the request.",
}

#: Ordered ``(exception_class, code)`` mapping consulted top to bottom by
#: :func:`classify_exception`; the first match wins. Order matters because
#: `AccessDenied`, `AccessError`, `MissingError` and `LockError` are all
#: `UserError` subclasses in Odoo 19 (each carrying its own ``http_status``),
#: so they must be listed *before* the generic `UserError` catch-all or
#: they would incorrectly surface as ``validation_error``.
_EXCEPTION_CODE_MAP = (
    (MissingError, "missing_record"),
    (LockError, "lock_error"),
    (AccessDenied, "access_denied"),
    (AccessError, "access_denied"),
    (UserError, "validation_error"),
)


def classify_exception(exc):
    """Return ``(status, code, message)`` for ``exc``.

    ``status`` is always ``exc.http_status`` for a recognised
    :class:`~odoo.exceptions.UserError` subclass (``422``/``403``/``404``/
    ``409``), or ``500`` for anything else. ``message`` is the client-safe
    text for the envelope's ``message`` key: the exception's own message for
    every recognised code except ``access_denied`` (generic, see
    ``_GENERIC_MESSAGES``), and always generic for ``internal_error``.
    """
    for exc_class, code in _EXCEPTION_CODE_MAP:
        if isinstance(exc, exc_class):
            if code in _GENERIC_MESSAGES:
                message = _GENERIC_MESSAGES[code]
            else:
                message = str(exc)
            return exc.http_status, code, message
    return 500, "internal_error", _GENERIC_MESSAGES["internal_error"]


def traceback_disclosure_allowed(env):
    """Whether the traceback of the exception being handled may be included
    in the (still logged server-side regardless) error envelope's
    ``details``.

    Both conditions are required at once: the requesting user is in
    ``base.group_system`` *and* the ``ir.config_parameter``
    :data:`ICP_EXPOSE_TRACEBACK` is the string ``"True"`` (default
    ``"False"``, see ``data/ir_config_parameter_data.xml``). ``env`` may be
    ``None`` (no database resolved for this request yet), in which case
    disclosure is always refused.
    """
    if env is None:
        return False
    user = env.user
    if not user or not user.has_group("base.group_system"):
        return False
    icp = env["ir.config_parameter"].sudo()
    return icp.get_param(ICP_EXPOSE_TRACEBACK, "False") == "True"


def format_traceback(exc):
    """Render ``exc``'s traceback as text, the same shape
    ``odoo.http.serialize_exception()`` uses for its ``debug`` key."""
    return "".join(traceback.format_exception(exc))


def build_error_body(code, message, status, request_id, details=None):
    """Assemble the single error envelope shape used by every ``ssi_rest``
    error response."""
    return {
        "error": {
            "code": code,
            "message": message,
            "status": status,
            "request_id": request_id,
            "details": details,
        }
    }
