# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """UI-only extension: every field below is wired straight to its
    ``ir.config_parameter`` key via ``config_parameter=`` (handled by
    ``res.config.settings``' own ``get_values``/``set_values``, not
    overridden here). This model stores nothing of its own.
    """

    _inherit = "res.config.settings"

    ssi_rest_api_expose_traceback = fields.Boolean(
        string="Expose Traceback",
        config_parameter="ssi_rest_api.expose_traceback",
        help="Include the Python traceback in the REST error envelope's "
        "details, for callers in the base.group_system group. Keep "
        "disabled in production.",
    )
    ssi_rest_api_default_page_size = fields.Integer(
        string="Default Page Size",
        config_parameter="ssi_rest_api.default_page_size",
        help="Number of records returned per page when a list request "
        "does not specify a page size.",
    )
    ssi_rest_api_max_page_size = fields.Integer(
        string="Max Page Size",
        config_parameter="ssi_rest_api.max_page_size",
        help="Upper bound a client can request for page size, "
        "regardless of what it asks for.",
    )
    ssi_rest_api_cors_origins = fields.Char(
        string="CORS Origins",
        config_parameter="ssi_rest_api.cors_origins",
        help="Comma-separated list of allowed CORS origins. Empty means "
        "CORS headers are not emitted.",
    )
