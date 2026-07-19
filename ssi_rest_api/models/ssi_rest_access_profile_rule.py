# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class SsiRestAccessProfileRule(models.Model):
    """Detail/child model: one evaluation rule belonging to a
    ``ssi_rest_access_profile``, matched in ``_order`` (profile_id,
    sequence) — the first match decides the effect. Uses fnmatch-style
    glob patterns rather than a bespoke operator language (clean-room:
    the proprietary framework this module is functionally inspired by
    uses its own operator syntax, not reproduced here — a glob plus
    ``invert`` already covers every real case and is one sentence to
    explain to an administrator).
    """

    _name = "ssi_rest_access_profile.rule"
    _description = "REST Access Profile - Rule"
    _order = "profile_id, sequence"

    profile_id = fields.Many2one(
        comodel_name="ssi_rest_access_profile",
        string="# Profile",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(
        required=True,
        help="Evaluation order among this profile's rules; lower runs "
        "first, first match wins. No default: every rule must state its "
        "own position explicitly.",
    )
    effect = fields.Selection(
        selection=[("allow", "Allow"), ("deny", "Deny")],
        required=True,
        help="Effect applied when this rule matches the request.",
    )
    path_pattern = fields.Char(
        help="fnmatch-style glob matched against the request path (e.g. "
        "'/api/v1/orm/*'). Empty matches every path.",
    )
    invert = fields.Boolean(
        default=False,
        help="Invert the path_pattern match only, not the "
        "http_methods/model_pattern/operation match.",
    )
    http_methods = fields.Char(
        help="Comma-separated HTTP methods this rule applies to (e.g. "
        "'GET,POST'). Empty matches every method.",
    )
    model_pattern = fields.Char(
        help="fnmatch-style glob matched against the target Odoo model "
        "technical name. Empty matches every model.",
    )
    operation = fields.Selection(
        selection=[
            ("read", "Read"),
            ("write", "Write"),
            ("create", "Create"),
            ("unlink", "Unlink"),
            ("call", "Call"),
            ("any", "Any"),
        ],
        required=True,
        default="any",
        help="Operation this rule applies to.",
    )
