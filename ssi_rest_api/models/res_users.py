# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    ssi_rest_profile_ids = fields.Many2many(
        comodel_name="ssi_rest_access_profile",
        relation="ssi_rest_access_profile_user_rel",
        column1="user_id",
        column2="profile_id",
        string="REST Access Profiles",
        groups="base.group_system",
        help="REST access profiles granted to this user, in addition to "
        "any profile granted through one of their groups.",
    )
    ssi_rest_enabled = fields.Boolean(
        string="REST API Enabled",
        default=False,
        groups="base.group_system",
        help="Whether this user may be resolved as the authenticated "
        "identity of a ssi_rest request. Does not replace normal ACL "
        "checks.",
    )
