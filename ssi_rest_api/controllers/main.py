# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Minimal endpoint proving the ``ssi_rest`` dispatcher end-to-end.

Not a stable public API: auth, access profile, serializer and every
functional endpoint are later backlog items. This controller only exists so
the dispatcher + ``rest_route`` wiring can be exercised by an actual HTTP
request instead of only by unit-testing the helper in isolation.
"""

from odoo import http

from ..lib.routing import rest_route


class SsiRestPingController(http.Controller):
    # `auth="public"` here only because this specific endpoint has no
    # functional purpose beyond proving the dispatcher wiring end-to-end;
    # real endpoints choose their own `auth` per their own access needs
    # (later backlog item), `rest_route` does not impose a default.
    @rest_route(["/ping"], operation="ping", auth="public")
    def ping(self, **kwargs):
        return {"pong": True, "echo": kwargs.get("echo")}
