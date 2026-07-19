# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OpenAPI document + Swagger UI routes.

BINDING (backlog issue #16's Keputusan Desain, do not remove this comment
when editing this file): both routes below use ``auth="ssi_rest"`` (never
``auth="public"``) *and* additionally reject any authenticated caller
outside the ``ssi_rest_api_doc.ssi_rest_openapi_group`` group — the
documentation exposes this repo's entire REST API surface and must never
be reachable anonymously or by every internal user by default.

The Swagger UI page is served entirely from this module's own vendored
``static/src/lib/swagger-ui`` assets (Apache-2.0, see ``NOTICE`` next to
them), registered through the manifest's ``"assets"`` key and pulled in by
``views/swagger_ui_templates.xml`` via ``t-call-assets`` — never a CDN.
``static/src/js/swagger_ui_init.js`` additionally sets ``validatorUrl:
null``, which is what stops swagger-ui's own default behaviour of pinging
``validator.swagger.io`` on every page load.
"""

import re

from odoo import http
from odoo.http import request

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api.lib.constants import PATH_PREFIX
from odoo.addons.ssi_rest_api.lib.routing import rest_route

#: The version segment of the *current* request's own matched URL — never
#: a client-supplied parameter, so there is nothing to validate: a request
#: could not have reached this controller through any other path shape.
_VERSION_RE = re.compile(rf"^{re.escape(PATH_PREFIX)}/v(?P<version>\d+)/")

_DOC_GROUP_XMLID = "ssi_rest_api_doc.ssi_rest_openapi_group"
_ACCESS_DENIED_MESSAGE = "You are not allowed to access the API documentation."


def _current_rest_version(httprequest):
    match = _VERSION_RE.match(httprequest.path)
    return int(match.group("version"))


def _ensure_doc_group(env):
    if not env.user.has_group(_DOC_GROUP_XMLID):
        raise RestAuthError("access_denied", _ACCESS_DENIED_MESSAGE, status=403)


class SsiRestOpenapiController(http.Controller):
    @rest_route(
        ["/openapi.json"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def openapi_document(self, **kwargs):
        _ensure_doc_group(request.env)
        version = _current_rest_version(request.httprequest)
        return request.env["ssi_rest_openapi"]._build_document(version)

    @rest_route(
        ["/openapi/ui"],
        auth="ssi_rest",
        methods=["GET"],
        operation="read",
        readonly=True,
    )
    def openapi_ui(self, **kwargs):
        _ensure_doc_group(request.env)
        version = _current_rest_version(request.httprequest)
        document_url = f"{PATH_PREFIX}/v{version}/openapi.json"
        return request.render(
            "ssi_rest_api_doc.swagger_ui_page", {"document_url": document_url}
        )
