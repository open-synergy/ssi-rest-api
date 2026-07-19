# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Authentication contract shared by every ``mixin.rest_authenticator``
provider and the ``_auth_method_ssi_rest`` classmethod that drives them
(``models/ir_http.py``).

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by (see ``lib/dispatcher.py`` module docstring for the full
rationale).
"""

from typing import NamedTuple, Optional, Sequence

from werkzeug.exceptions import HTTPException


class RestAuthResult(NamedTuple):
    """Successful outcome of ``mixin.rest_authenticator._rest_auth_verify``.

    ``profile_ids`` and ``scopes`` are forward-looking: nothing in this
    backlog item reads them yet, they exist so the access-profile and
    OAuth2-scope backlog items don't need to change this contract's shape.
    """

    uid: int
    scheme: str
    profile_ids: Sequence[int] = ()
    scopes: Sequence[str] = ()
    expires_at: Optional[object] = None


class RestAuthError(HTTPException):
    """The only exception type a ``mixin.rest_authenticator`` provider (or
    ``_auth_method_ssi_rest`` itself) may raise for an authentication
    failure (invalid/expired credential, no credential at all, ambiguous
    request, ...).

    Subclassing werkzeug's ``HTTPException`` (rather than an Odoo
    ``UserError``/``AccessDenied``) is binding, not a style choice: Odoo 19's
    ``ir.http._authenticate_explicit`` only re-raises
    ``(AccessDenied, SessionExpiredException, werkzeug.exceptions.HTTPException)``
    unchanged; any other exception type is swallowed and replaced with a
    bare ``AccessDenied()``, discarding both the intended HTTP status and
    the message. A provider that raises e.g. a plain ``ValueError`` for a
    bad credential would silently lose its 401/400 status this way.
    """

    def __init__(self, error_code, description, status=401, headers=None):
        super().__init__(description=description)
        #: HTTP status code for this failure (401 for "no/invalid
        #: credential", 400 for "ambiguous request"). Read by
        #: ``lib.errors.classify_exception``.
        self.code = status
        #: Stable machine string for the error envelope's ``error.code``
        #: key (e.g. ``"multiple_credentials"``). Never a Python exception
        #: class path.
        self.error_code = error_code
        #: Extra response headers (e.g. ``WWW-Authenticate``) the envelope
        #: must carry. Deliberately *not* relying on werkzeug's
        #: ``get_headers()`` for this: that method also injects a
        #: ``Content-Type: text/html`` header meant for werkzeug's own HTML
        #: error page, which would incorrectly override the JSON envelope's
        #: content type.
        self.rest_headers = list(headers or [])
