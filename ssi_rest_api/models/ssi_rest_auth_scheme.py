# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.tools import ormcache


class SsiRestAuthScheme(models.Model):
    """Registry of REST authentication schemes.

    Each active record links a scheme ``code`` (e.g. ``"basic"``,
    ``"bearer"``) to the ``mixin.rest_authenticator`` provider
    ``AbstractModel`` that implements it. ``_auth_method_ssi_rest``
    (``models/ir_http.py``) reads this registry, ordered by ``sequence``, to
    decide which providers to try for a given request. Concrete auth
    modules (Basic, Bearer, API key, JWT, OAuth2, ...) seed their own
    record here via data XML; this module only defines the registry itself,
    with no scheme seeded.

    Record-based rather than import-time registration is a deliberate
    design choice: it lets a scheme be created inside a test transaction
    (then rolled back) so the registry contract can be exercised without
    depending on any concrete auth module.
    """

    _name = "ssi_rest_auth_scheme"
    _inherit = ["mixin.master_data"]
    _description = "REST Authentication Scheme"
    _order = "sequence, id"
    # A print button is meaningless for a technical registry record.
    _automatically_insert_print_button = False

    provider_model = fields.Char(
        required=True,
        help="Technical name (_name) of the mixin.rest_authenticator "
        "AbstractModel that implements this authentication scheme.",
    )
    sequence = fields.Integer(
        required=True,
        default=10,
        help="Evaluation order among active schemes: "
        "_auth_method_ssi_rest tries providers lowest sequence first.",
    )

    @api.model
    @ormcache()
    def _get_active_schemes(self):
        """Return ``((code, provider_model), ...)`` for every active scheme,
        ordered by ``sequence``.

        Cached for the life of the registry: invalidated by :meth:`create`,
        :meth:`write` and :meth:`unlink` below whenever a scheme record
        changes.
        """
        # Registry of active schemes, realistically a handful of records
        # (config data, not user-facing bulk data) — the whole point of
        # this method is to load and cache all of them at once.
        schemes = self.sudo().search([])  # pylint: disable=no-search-all
        return tuple((scheme.code, scheme.provider_model) for scheme in schemes)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result
