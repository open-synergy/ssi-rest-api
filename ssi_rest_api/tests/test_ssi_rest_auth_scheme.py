# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo_yaml_test import YamlTransactionCase

from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestSsiRestAuthScheme(YamlTransactionCase):
    def test_ssi_rest_auth_scheme(self):
        self.run_yaml_scenario("test_data_ssi_rest_auth_scheme.yaml")

    def test_get_active_schemes_ordered_and_cache_invalidated(self):
        """Python murni — pemicu P1 (L-01/L-02: `_get_active_schemes()`
        mengembalikan sebuah tuple, bukan efek samping pada sebuah record;
        `action: call` di YAML membuang nilai balik method dan `asserts`
        hanya bisa membaca field pada record di registry, bukan return
        value method)."""
        scheme_model = self.env["ssi_rest_auth_scheme"]
        scheme_b = scheme_model.create(
            {
                "name": "Scheme B",
                "code": "py_scheme_b",
                "provider_model": "mixin.rest_authenticator",
                "sequence": 20,
            }
        )
        scheme_a = scheme_model.create(
            {
                "name": "Scheme A",
                "code": "py_scheme_a",
                "provider_model": "mixin.rest_authenticator",
                "sequence": 10,
            }
        )

        schemes = scheme_model._get_active_schemes()
        self.assertIn(("py_scheme_a", "mixin.rest_authenticator"), schemes)
        self.assertIn(("py_scheme_b", "mixin.rest_authenticator"), schemes)
        self.assertLess(
            schemes.index(("py_scheme_a", "mixin.rest_authenticator")),
            schemes.index(("py_scheme_b", "mixin.rest_authenticator")),
        )

        scheme_a.active = False
        schemes = scheme_model._get_active_schemes()
        self.assertNotIn(("py_scheme_a", "mixin.rest_authenticator"), schemes)
        self.assertIn(("py_scheme_b", "mixin.rest_authenticator"), schemes)

        scheme_b.unlink()
        schemes = scheme_model._get_active_schemes()
        self.assertNotIn(("py_scheme_b", "mixin.rest_authenticator"), schemes)
