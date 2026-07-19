# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models


class SsiRestAccessProfile(models.Model):
    """Security configuration object listing REST endpoint access rules
    evaluated against an authenticated request, enforced from
    ``lib/dispatcher.py:SsiRestDispatcher.pre_dispatch``.

    Deliberately **not** master data (no ``mixin.master_data``): a profile
    is a security configuration object administered directly by system
    administrators, not business reference data.

    BINDING SUBTRACTIVE-ONLY INVARIANT (do not remove this comment when
    editing this class): a profile may only *narrow* access already
    granted by Odoo's own ACL and record rules — it can never *grant*
    access beyond them. The direct, binding consequence: ``sudo()`` is
    forbidden anywhere in this model's own methods, in
    ``ssi_rest_access_profile.rule``, and in every ``ssi_rest`` endpoint
    across this module family. The moment ``sudo()`` is used on this
    path, a request that has no real ACL for a model could still be
    "allowed" by a permissive profile, turning this mechanism from a
    narrowing one into a widening one.
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

    def _evaluate_request(self, path, http_method, model, operation):
        """Return ``True`` (allow) or ``False`` (deny) for this single
        profile against the given request description.

        Free of ``odoo.http.request`` (backlog issue #7's binding
        Keputusan Desain) so it can be exercised from a plain
        ``TransactionCase``. Rules are read via an explicit re-sort
        (rather than trusting ``rule_ids`` order as-is) because a
        recordset populated from ``(0, 0, {...})`` create commands in the
        same transaction reflects command order, not ``_order``.
        """
        self.ensure_one()
        for rule in self.rule_ids.sorted("sequence"):
            if rule._matches_request(path, http_method, model, operation):
                return rule.effect == "allow"
        return self.default_effect == "allow"

    @api.model
    def _get_applicable_profiles(self, user):
        """Return every active profile applicable to ``user``: granted
        directly (``user_ids``) or through one of the user's groups,
        implied groups included (``group_ids``).
        """
        return self.search(
            [
                "|",
                ("user_ids", "in", user.id),
                ("group_ids", "in", user.all_group_ids.ids),
            ]
        )

    @api.model
    def _check_request_access(self, user, path, http_method, model, operation):
        """Return whether ``user`` may proceed with the described
        request.

        No profile applicable to ``user`` at all -> unrestricted (``True``):
        this mechanism only ever narrows access once an administrator has
        actually installed a profile, an uninstalled/unconfigured system
        must never be locked out by default. With at least one applicable
        profile, the request is allowed if **any** of them evaluates to
        allow (union semantics, see Keputusan Desain).
        """
        profiles = self._get_applicable_profiles(user)
        if not profiles:
            return True
        return any(
            profile._evaluate_request(path, http_method, model, operation)
            for profile in profiles
        )
