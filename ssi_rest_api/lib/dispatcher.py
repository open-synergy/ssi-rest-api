# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""The ``ssi_rest`` HTTP request dispatcher.

Odoo core dispatches every route through a :class:`~odoo.http.Dispatcher`
subclass looked up by ``routing_type`` in the module-level ``_dispatchers``
registry (populated automatically by ``Dispatcher.__init_subclass__``).
Subclassing :class:`~odoo.http.Json2Dispatcher` (``routing_type='json2'``)
rather than :class:`~odoo.http.Dispatcher` directly is deliberate: JSON body
parsing, ``make_json_response`` and the JSON error-serialization shape it
already implements are exactly what a JSON-first REST API needs, so only the
behaviour that genuinely differs is overridden here.

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by. That framework's approach (monkey-patching ``http.Root``) is
not applicable to Odoo 19 anyway (``Root`` no longer exists there); the
registry-based ``Dispatcher`` seam used below is the officially supported
Odoo 19 mechanism instead.
"""

import logging
import uuid

from werkzeug.exceptions import BadRequest, HTTPException

from odoo.http import Json2Dispatcher, Response

from .errors import (
    build_error_body,
    classify_exception,
    format_traceback,
    traceback_disclosure_allowed,
)

_logger = logging.getLogger(__name__)

#: Mimetypes that must be read through ``request.get_http_params()`` instead
#: of the JSON body parser (file uploads and classic form posts).
_FORM_MIMETYPES = (
    "multipart/form-data",
    "application/x-www-form-urlencoded",
)

#: Response header carrying the per-request correlation id (see
#: ``pre_dispatch`` below). Consumed by the (future) error envelope and by
#: server-side logs to correlate a client report with server logs.
REQUEST_ID_HEADER = "X-Request-Id"


class SsiRestDispatcher(Json2Dispatcher):
    """Dispatcher backing every ``type="ssi_rest"`` route registered through
    :func:`~odoo.addons.ssi_rest_api.lib.routing.rest_route`.

    Security invariant (binding, do not remove this comment when editing this
    class): routes of ``type != "http"`` never go through
    ``HttpDispatcher.dispatch``, so the CSRF check that guards ``type="http"``
    requests is *never* applied to ``ssi_rest`` routes either. This is safe
    **only** for as long as authentication for this dispatcher never accepts
    a bare session cookie as a credential (e.g. only ``Authorization``
    header-based schemes). The moment a session cookie becomes an accepted
    credential here, this dispatcher needs its own CSRF check, symmetrical to
    ``HttpDispatcher.dispatch``.
    """

    routing_type = "ssi_rest"

    @classmethod
    def is_compatible_with(cls, request):
        # Always compatible. `Json2Dispatcher.is_compatible_with` only
        # accepts `application/json` (or an empty body); a plain "not
        # compatible" rejection from `_set_request_dispatcher` for e.g.
        # `multipart/form-data` uploads would surface as a confusing 500 by
        # the time it is noticed, instead of being handled by `dispatch`
        # below.
        return True

    def dispatch(self, endpoint, args):
        mimetype = self.request.httprequest.mimetype
        if mimetype in _FORM_MIMETYPES:
            self.request.params = dict(self.request.get_http_params(), **args)
        else:
            # JSON body, or no body at all. Deliberately *not* delegated to
            # `Json2Dispatcher.dispatch` (core) here: that method only does
            # `self.request.params = self.jsonrequest | args`, which never
            # reads `request.httprequest.args` at all (verified against
            # Odoo 19 core) — a query string such as `?kind=missing` would
            # therefore silently never reach the endpoint. Precedence below,
            # most to least authoritative: path parameters (`args`,
            # structurally guaranteed by the matched route) > JSON body
            # (the caller's explicit payload) > query string (commonly used
            # for filters/defaults, e.g. on GET-style calls). This ordering
            # is the stable contract every `ssi_rest` endpoint can rely on,
            # including future CRUD endpoints (#11 and beyond).
            if self.request.httprequest.content_length:
                try:
                    self.jsonrequest = self.request.get_json_data()
                except ValueError as exc:
                    message = f"could not parse the body as json: {exc.args[0]}"
                    raise BadRequest(message) from exc
            query_params = self.request.httprequest.args.to_dict()
            self.request.params = {
                **query_params,
                **(self.jsonrequest or {}),
                **args,
            }

        if self.request.db:
            result = self.request.registry["ir.http"]._dispatch(endpoint)
        else:
            result = endpoint(**self.request.params)
        if isinstance(result, Response):
            return result
        return self.request.make_json_response(result)

    def pre_dispatch(self, rule, args):
        result = super().pre_dispatch(rule, args)
        self._ensure_request_id()
        return result

    def _ensure_request_id(self):
        """Return this request's correlation id, generating and storing one
        on ``future_response`` if none exists yet.

        Normally set once by :meth:`pre_dispatch` above. The fallback here
        exists for :meth:`handle_error`: an exception raised *before*
        ``pre_dispatch`` runs (e.g. during authentication) would otherwise
        reach ``handle_error`` with no id set at all, and the error envelope
        must always carry one.
        """
        headers = self.request.future_response.headers
        request_id = headers.get(REQUEST_ID_HEADER)
        if not request_id:
            request_id = str(uuid.uuid4())
            headers.set(REQUEST_ID_HEADER, request_id)
        return request_id

    def handle_error(self, exc: Exception) -> Response:
        """Render any exception raised while serving a ``ssi_rest`` route as
        the single error envelope shape documented in ``lib/errors.py``.

        Deliberately written from scratch rather than delegating to
        ``Json2Dispatcher.handle_error``: that implementation calls
        ``odoo.http.serialize_exception()``, which unconditionally embeds a
        full Python traceback under a ``debug`` key — not acceptable on a
        public error response. Note that ``Application.__call__`` (core)
        never routes ``handle_error``'s return value through
        ``Dispatcher.post_dispatch``/``_inject_future_response`` on the
        error path, so the ``X-Request-Id`` header is set on this response
        explicitly below rather than relying on ``future_response``.
        """
        if isinstance(exc, HTTPException) and exc.response:
            # A response already built via
            # `werkzeug.exceptions.abort(Response(...))` (e.g. the CORS
            # pre-flight short-circuit in `Dispatcher.pre_dispatch`) is a
            # deliberate result, not an error to render through the
            # envelope below.
            return exc.response

        request_id = self._ensure_request_id()
        status, code, message = classify_exception(exc)

        # Written to the server log unconditionally, regardless of whether
        # `details` below ever discloses it to the client: this is the only
        # place a traceback is guaranteed to end up correlated with the
        # `request_id` also carried by the client-visible response.
        _logger.error(
            "ssi_rest request %s failed: code=%s status=%s",
            request_id,
            code,
            status,
            exc_info=exc,
        )

        details = None
        if traceback_disclosure_allowed(self.request.env):
            details = {"traceback": format_traceback(exc)}

        body = build_error_body(
            code=code,
            message=message,
            status=status,
            request_id=request_id,
            details=details,
        )
        return self.request.make_json_response(
            body, headers=[(REQUEST_ID_HEADER, request_id)], status=status
        )
