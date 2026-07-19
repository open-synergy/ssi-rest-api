# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import fnmatch

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

    def _matches_request(self, path, http_method, model, operation):
        """Return whether this rule matches the given request description.

        Free of ``odoo.http.request`` (per backlog issue #7's binding
        Keputusan Desain) so it can be exercised from a plain
        ``TransactionCase`` without a real HTTP request. Every criterion
        that is filled in must match (AND); an empty criterion matches
        everything, ``invert`` affects ``path_pattern`` only.

        :param str path: request path (e.g. ``"/api/v1/orm/res.partner"``).
        :param str http_method: HTTP method (e.g. ``"GET"``).
        :param str|None model: target model technical name, or ``None``
            for an endpoint with no single target model.
        :param str|None operation: operation identifier (e.g. ``"read"``),
            or ``None``.
        """
        self.ensure_one()
        path_matched = (
            fnmatch.fnmatchcase(path, self.path_pattern) if self.path_pattern else True
        )
        if self.invert:
            path_matched = not path_matched
        if not path_matched:
            return False

        if self.http_methods:
            allowed_methods = {
                method.strip().upper()
                for method in self.http_methods.split(",")
                if method.strip()
            }
            if http_method.upper() not in allowed_methods:
                return False

        if self.model_pattern and not fnmatch.fnmatchcase(
            model or "", self.model_pattern
        ):
            return False

        if self.operation != "any" and operation != self.operation:
            return False

        return True
