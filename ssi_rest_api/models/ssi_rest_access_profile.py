# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class SsiRestAccessProfile(models.Model):
    """Security configuration object listing REST endpoint access rules
    evaluated against an authenticated request.

    Deliberately **not** master data (no ``mixin.master_data``): a profile
    is a security configuration object administered directly by system
    administrators, not business reference data. Evaluation of
    ``rule_ids`` against an actual request is a later backlog item — this
    one only defines the model, its rules, and its administration UI.
    """

    _name = "ssi_rest_access_profile"
    _description = "REST Access Profile"

    _code_uniq = models.Constraint(
        "UNIQUE (code)",
        "Code must be unique.",
    )

    name = fields.Char(
        required=True,
        help="Descriptive label for this access profile.",
    )
    code = fields.Char(
        required=True,
        help="Unique technical identifier for this access profile.",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive profiles are ignored during request evaluation.",
    )
    default_effect = fields.Selection(
        selection=[("allow", "Allow"), ("deny", "Deny")],
        required=True,
        default="deny",
        help="Effect applied when no rule in rule_ids matches the "
        "request. Defaults to deny (fail-closed): a profile with no "
        "matching rule blocks access rather than allowing it.",
    )
    rule_ids = fields.One2many(
        comodel_name="ssi_rest_access_profile.rule",
        inverse_name="profile_id",
        string="Rules",
        help="Rules evaluated in sequence order; the first match decides "
        "the effect, falling back to default_effect if none match.",
    )
    user_ids = fields.Many2many(
        comodel_name="res.users",
        relation="ssi_rest_access_profile_user_rel",
        column1="profile_id",
        column2="user_id",
        string="Users",
        help="Users this profile is granted to.",
    )
    group_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Groups",
        help="Groups this profile is granted to.",
    )
