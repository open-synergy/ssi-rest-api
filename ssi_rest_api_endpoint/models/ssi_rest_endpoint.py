# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SsiRestEndpoint(models.Model):
    """Custom REST endpoint definition (backlog issue #17).

    Maps a ``path`` + ``http_method`` pair to a whitelisted handler — a
    model method that passes ``odoo.service.model.get_public_method``, or
    an ``ir.actions.server`` — served through the single wildcard route
    registered in ``controllers/main.py``. Registering one Odoo route per
    record is deliberately rejected (Keputusan Desain): it would mean
    routing-map invalidation on every write and O(n) memory against the
    number of records.

    Master data (``_inherit = ["mixin.master_data"]``): ``name``,
    ``code``, ``active`` and ``note`` come from the mixin and are never
    redeclared here. There is deliberately **no** ``state`` field — a
    master data model must not carry a workflow/state machine besides
    ``active`` for archival. An endpoint that must stop being callable is
    archived (``active = False``); the wildcard route only ever looks up
    active records (ORM's own ``active`` handling), so an archived
    endpoint is a plain 404, never a state check.
    """

    _name = "ssi_rest_endpoint"
    _inherit = ["mixin.master_data"]
    _description = "REST Custom Endpoint"
    _order = "path"
    # A print button is meaningless for a technical endpoint definition.
    _automatically_insert_print_button = False

    _path_uniq = models.Constraint(
        "UNIQUE (path)",
        "Path must be unique.",
    )

    path = fields.Char(
        required=True,
        help="URL segment matched against the wildcard route's "
        "<path:subpath> (e.g. 'sales/close-quarter'), combined with "
        "http_method to look up this endpoint at call time. Must be "
        "unique across every custom endpoint, active or archived.",
    )
    http_method = fields.Selection(
        selection=[
            ("GET", "GET"),
            ("POST", "POST"),
            ("PUT", "PUT"),
            ("PATCH", "PATCH"),
            ("DELETE", "DELETE"),
        ],
        required=True,
        default="GET",
        help="HTTP method this endpoint responds to. The same path may "
        "be registered more than once, each under a different "
        "http_method, to expose a different handler per verb.",
    )
    handler_type = fields.Selection(
        selection=[
            ("model_method", "Model Method"),
            ("server_action", "Server Action"),
        ],
        required=True,
        default="model_method",
        help="What runs when this endpoint is called: a whitelisted "
        "model method (model_id + method_name), or an ir.actions.server "
        "(server_action_id). Storing arbitrary Python code on a field "
        "and executing it with safe_eval is deliberately not an option "
        "here — see this module's Keputusan Desain.",
    )
    model_id = fields.Many2one(
        comodel_name="ir.model",
        help="Target model for handler_type=model_method: method_name "
        "is looked up and called on this model.",
    )
    method_name = fields.Char(
        help="Public method called on model_id's model when "
        "handler_type=model_method. Only methods accepted by "
        "odoo.service.model.get_public_method are ever executed at call "
        "time; any other method (private, unsafe attribute, ...) is "
        "rejected, never invoked.",
    )
    server_action_id = fields.Many2one(
        comodel_name="ir.actions.server",
        help="Server action run when handler_type=server_action.",
    )
    profile_ids = fields.Many2many(
        comodel_name="ssi_rest_access_profile",
        relation="ssi_rest_endpoint_profile_rel",
        column1="endpoint_id",
        column2="profile_id",
        string="Access Profiles",
        help="Access profiles allowed to call this endpoint, evaluated "
        "with the same ssi_rest_access_profile mechanism the dispatcher "
        "already applies to every ssi_rest request (see "
        "_check_rest_access below) — no separate authorization path is "
        "introduced here. Empty means no endpoint-specific restriction "
        "beyond what the caller's own applicable profiles already allow.",
    )
    is_readonly = fields.Boolean(
        string="Readonly",
        default=False,
        help="Whether calling this endpoint only ever reads data. "
        "Determines the readonly= cursor mode the wildcard route "
        "resolves for a call to this endpoint. An endpoint that may "
        "write must never be marked readonly; leave this False when "
        "unsure.",
    )
    input_schema = fields.Text(
        help="Free-form metadata describing the expected request "
        "payload shape, stored and published for API "
        "documentation/OpenAPI generation only. Not enforced against "
        "the actual request at runtime.",
    )
    output_schema = fields.Text(
        help="Free-form metadata describing the response payload shape, "
        "stored and published for API documentation/OpenAPI generation "
        "only. Not enforced against the actual response at runtime.",
    )

    @api.constrains("handler_type", "model_id", "method_name", "server_action_id")
    def _check_handler_configuration(self):
        for record in self.sudo():
            if not record._check_handler_configuration_condition():
                raise ValidationError(
                    record.env._(
                        "Document Type: %(document_type)s\n"
                        "Context: Create or update REST custom endpoint\n"
                        "Database ID: %(database_id)s\n"
                        "Problem: handler_type is '%(handler_type)s' but "
                        "the field(s) it requires are not set\n"
                        "Solution: Fill model_id and method_name for "
                        "handler_type=model_method, or server_action_id "
                        "for handler_type=server_action",
                        document_type=record._description,
                        database_id=record.id,
                        handler_type=record.handler_type,
                    )
                )

    def _check_handler_configuration_condition(self):
        self.ensure_one()
        if self.handler_type == "model_method":
            return bool(self.model_id and self.method_name)
        if self.handler_type == "server_action":
            return bool(self.server_action_id)
        return True

    def _check_rest_access(self, user):
        """Return whether ``user`` may invoke this endpoint through its
        own ``profile_ids`` allow-list.

        Reuses ``ssi_rest_access_profile._get_applicable_profiles`` and
        ``ssi_rest_access_profile._evaluate_request`` (backlog issue #7)
        exactly as they are — no new authorization mechanism is
        introduced here, only the scoping of *which* profiles are
        relevant to this specific endpoint. Free of ``sudo()``: both
        ``profile_ids`` (this model's own ACL) and
        ``ssi_rest_access_profile`` (group-less "_all_access", readable
        by every user — see ``ssi_rest_api``'s security files) are
        readable without elevation for any caller this method is ever
        invoked for.
        """
        self.ensure_one()
        if not self.profile_ids:
            # No endpoint-specific restriction configured: the generic
            # ssi_rest_access_profile check SsiRestDispatcher.pre_dispatch
            # already runs for every ssi_rest request still applies; this
            # method only ever narrows further, never grants on its own.
            return True
        applicable_ids = set(
            self.env["ssi_rest_access_profile"]._get_applicable_profiles(user).ids
        )
        candidates = self.profile_ids.filtered(lambda p: p.id in applicable_ids)
        if not candidates:
            return False
        model_name = self._get_target_model_name()
        return any(
            profile._evaluate_request(self.path, self.http_method, model_name, "call")
            for profile in candidates
        )

    def _get_target_model_name(self):
        """Return ``model_id``'s technical model name, or ``None``.

        Read via raw SQL, not ``model_id.model``: ``ir.model`` is itself
        ``base.group_system``-only (see ``ssi_rest_api_introspection``'s
        tests for the same fact), and this method must remain callable by
        any caller entitled to call the endpoint at all — the technical
        name of a model an administrator already pointed this *config*
        record at is not user data gated by the caller's own ACL. Never
        ``sudo()``, per this module's binding no-sudo invariant.
        """
        self.ensure_one()
        if not self.model_id:
            return None
        self.env.cr.execute(
            "SELECT model FROM ir_model WHERE id = %s", (self.model_id.id,)
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None
