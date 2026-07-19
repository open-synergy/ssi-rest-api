# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""OAuth2 scope catalogue (backlog issue #20).

Clean-room: no code, naming, or file structure copied from the proprietary
framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring).
"""

from odoo import fields, models


class SsiRestOauthScope(models.Model):
    """A single named OAuth2 scope a client (``ssi_rest_oauth_client``) may
    request. Deliberately **not** master data (no ``mixin.master_data``,
    same reasoning as ``ssi_rest_access_profile``): a scope is a security
    configuration object, not business reference data, so ``name``/
    ``active`` are declared manually here rather than inherited.
    """

    _name = "ssi_rest_oauth_scope"
    _description = "REST OAuth2 Scope"
    _order = "code"

    _code_uniq = models.Constraint(
        "UNIQUE (code)",
        "Code must be unique.",
    )

    name = fields.Char(
        required=True,
        help="Descriptive label for this OAuth2 scope.",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive scopes are hidden from the default list view and "
        "should no longer be granted to new clients.",
    )
    code = fields.Char(
        required=True,
        help="Unique technical identifier for this scope, as carried by "
        "a token's space-separated scope string (e.g. 'read:partner').",
    )
    profile_id = fields.Many2one(
        comodel_name="ssi_rest_access_profile",
        string="Access Profile",
        help="Access profile this scope maps to when granted. Purely "
        "descriptive metadata for this backlog item: no endpoint in this "
        "module resolves it yet -- a token's effective profile always "
        "comes from its ssi_rest_oauth_client.profile_id (single profile "
        "per client, same rationale as ssi_rest_api_key.profile_id).",
    )
