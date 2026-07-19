# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Redirect URI allow-list, one row per ``ssi_rest_oauth_client``
(backlog issue #20).

Detail/child model (see skill odoo-development's 04-models.md "Model
Detail/Child"): cannot stand on its own, has no view/action/menu of its
own -- shown as a One2many tab on ssi_rest_oauth_client's own form -- and
is not inherited from mixin.master_data/mixin.transaction.
"""

from odoo import fields, models


class SsiRestOauthClientRedirectUri(models.Model):
    _name = "ssi_rest_oauth_client.redirect_uri"
    _description = "REST OAuth2 Client - Redirect URI"
    _order = "client_id, sequence"

    client_id = fields.Many2one(
        comodel_name="ssi_rest_oauth_client",
        string="Client",
        required=True,
        ondelete="cascade",
        help="Client this redirect URI belongs to. Deleting the client "
        "cascades to every one of its redirect URIs, never leaving an "
        "orphan row behind.",
    )
    sequence = fields.Integer(
        required=True,
        default=10,
        help="Display order among this client's redirect URIs. Has no "
        "effect on matching: the authorize endpoint requires an exact "
        "match against any one of them, regardless of order.",
    )
    url = fields.Char(
        required=True,
        help="Exact redirect_uri value the authorize endpoint will accept "
        "for this client. Compared with a plain string equality check -- "
        "prefix or wildcard matching is never accepted.",
    )
