# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Pure-Python tests for the ``rest_route`` routing helper.

Python murni — pemicu P1 (L-01): what every assertion below reads is the
*return value* of the ``rest_route``/``route`` decorator (the
``original_routing`` dict attached to the wrapped function) or a raised
``ValueError`` — neither is a record field. ``odoo-yaml-test``'s ``assert``
step only ever reads a dotted ``getattr`` path off a record kept in its
scenario registry (L-02); there is no Odoo record involved here at all, so
none of this can be expressed in YAML.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.ssi_rest_api.lib.constants import PATH_PREFIX
from odoo.addons.ssi_rest_api.lib.routing import rest_route


def _dummy(self, **kwargs):
    return None


@tagged("post_install", "-at_install")
class TestRestRoute(TransactionCase):
    def test_versions_expand_to_one_route_per_version(self):
        wrapped = rest_route(["/thing"], versions=(1, 2))(_dummy)
        routing = wrapped.original_routing
        self.assertEqual(
            routing["routes"],
            [f"{PATH_PREFIX}/v1/thing", f"{PATH_PREFIX}/v2/thing"],
        )
        self.assertEqual(routing["rest_version"], (1, 2))

    def test_routing_carries_binding_invariants(self):
        wrapped = rest_route(["/thing"])(_dummy)
        routing = wrapped.original_routing
        self.assertEqual(routing["type"], "ssi_rest")
        self.assertFalse(routing["save_session"])
        self.assertFalse(routing["csrf"])

    def test_routing_carries_rest_schemes_and_operation_kwargs(self):
        wrapped = rest_route(["/thing"], schemes="dummy-schema", operation="dummy-op")(
            _dummy
        )
        routing = wrapped.original_routing
        self.assertEqual(routing["rest_schemes"], "dummy-schema")
        self.assertEqual(routing["rest_operation"], "dummy-op")

    def test_single_path_string_is_accepted(self):
        wrapped = rest_route("/thing")(_dummy)
        self.assertEqual(
            wrapped.original_routing["routes"], [f"{PATH_PREFIX}/v1/thing"]
        )

    def test_empty_versions_raises(self):
        with self.assertRaises(ValueError):
            rest_route(["/thing"], versions=())
