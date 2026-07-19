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

import uuid

from odoo.http import Json2Dispatcher, Response

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
            if self.request.db:
                result = self.request.registry["ir.http"]._dispatch(endpoint)
            else:
                result = endpoint(**self.request.params)
            if isinstance(result, Response):
                return result
            return self.request.make_json_response(result)
        # JSON body, or no body at all: `Json2Dispatcher.dispatch` already
        # does the right thing (it parses the body only when
        # `content_length` is truthy).
        return super().dispatch(endpoint, args)

    def pre_dispatch(self, rule, args):
        result = super().pre_dispatch(rule, args)
        request_id = str(uuid.uuid4())
        self.request.future_response.headers.set(REQUEST_ID_HEADER, request_id)
        return result
