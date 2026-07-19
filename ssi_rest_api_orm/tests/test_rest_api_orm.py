# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""End-to-end HTTP tests for the generic ORM endpoints (backlog issue
#11).

Python murni — pemicu P7 (L-19): every scenario below drives the real
dispatcher (auth, readonly cursor resolution, status codes) through an
actual HTTP request, which `odoo-yaml-test`'s `TransactionCase`-based
DSL cannot do at all. Every test method gets its own fresh
`HttpCase.opener` (framework guarantee, see backlog issue #10's module
docstring) — no case here relies on, or leaks into, another's session.
"""

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ssi_rest_api_orm.controllers import _helpers

_DISPATCHER_LOGGER = "odoo.addons.ssi_rest_api.lib.dispatcher"


@tagged("post_install", "-at_install")
class TestSsiRestApiOrm(HttpCase):
    def setUp(self):
        super().setUp()
        self.test_user = self.env["res.users"].create(
            {
                "name": "ORM Test User",
                "login": "ssi_rest_api_orm_test_user@example.com",
                "email": "ssi_rest_api_orm_test_user@example.com",
                # `base.group_user` alone only grants *read* on
                # res.partner (see base/security/ir.model.access.csv);
                # create/write/unlink need group_partner_manager too —
                # several tests below exercise those on purpose.
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("base.group_partner_manager").id,
                        ],
                    )
                ],
            }
        )
        self.rpc_key = (
            self.env["res.users.apikeys"]
            .with_user(self.test_user)
            .sudo()
            ._generate(scope="rpc", name="orm test key", expiration_date=None)
        )
        self.partner = self.env["res.partner"].create({"name": "ORM Fixture Partner"})

    def _headers(self):
        return {"Authorization": f"Bearer {self.rpc_key}"}

    def test_search_read_respects_limit(self):
        self.env["res.partner"].create(
            [{"name": f"Bulk Partner {i}"} for i in range(5)]
        )
        response = self.url_open(
            "/api/v1/orm/res.partner/search_read?limit=2&fields=name",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertLessEqual(len(body["records"]), 2)
        self.assertGreaterEqual(body["length"], 6)

    def test_create_then_read_round_trip(self):
        response = self.url_open(
            "/api/v1/orm/res.partner/create",
            headers=self._headers(),
            json={"vals": {"name": "Created Via REST"}},
        )
        self.assertEqual(response.status_code, 201)
        created = response.json()
        self.assertEqual(len(created), 1)
        new_id = created[0]["id"]

        read_response = self.url_open(
            f"/api/v1/orm/res.partner/read?ids={new_id}&fields=name",
            headers=self._headers(),
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(read_response.json()[0]["name"], "Created Via REST")

    def test_call_route_readonly_is_the_dynamic_resolver(self):
        # The `readonly=` callable itself (`orm_call_readonly`) runs
        # *before* authentication (core dispatch order, see its
        # docstring) and needs a bound `odoo.http.request` — not
        # available from a test method's own thread, only from within an
        # actual served request. What this test can and does prove
        # without faking that context: the `call` route is wired to the
        # dynamic resolver (an object identity check), not a static
        # `True`/`False` — the resolver's own MRO/`_readonly`-attribute
        # logic (`res.users.has_group` is `@api.readonly` -> True; a
        # plain method -> False) is plain Python, exercised structurally
        # by every other `call` test in this file actually completing
        # without a read/write-cursor error.
        routing_map = self.env["ir.http"].routing_map()
        found = False
        for rule in routing_map.iter_rules():
            routing = getattr(rule.endpoint, "routing", None)
            if not routing or routing.get("type") != "ssi_rest":
                continue
            if not any(
                "/orm/" in route and "/call/" in route
                for route in routing.get("routes", [])
            ):
                continue
            found = True
            self.assertIs(routing["readonly"], _helpers.orm_call_readonly)
        self.assertTrue(found, "call route not found in routing map")

    def test_call_returning_recordset_normalizes_to_ids(self):
        # `exists()` looks tempting for this but is `@api.private` (core,
        # `orm/models.py`) and therefore rejected by `get_public_method`
        # — `copy()` is a genuinely public method that also returns a
        # recordset (a new record).
        response = self.url_open(
            "/api/v1/orm/res.partner/call/copy",
            headers=self._headers(),
            json={"ids": [self.partner.id]},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(len(result), 1)
        self.assertNotEqual(result[0], self.partner.id)

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_call_private_method_is_rejected_not_500(self):
        response = self.url_open(
            "/api/v1/orm/res.partner/call/_compute_display_name",
            headers=self._headers(),
            json={"ids": [self.partner.id]},
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertNotEqual(response.status_code, 500)

    @mute_logger(_DISPATCHER_LOGGER)
    def test_call_with_mismatched_kwargs_is_422(self):
        response = self.url_open(
            "/api/v1/orm/res.users/call/has_group",
            headers=self._headers(),
            json={"ids": [self.test_user.id], "unexpected_kwarg": "x"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    @mute_logger(_DISPATCHER_LOGGER, "odoo.http")
    def test_unlink_without_acl_is_403_with_generic_message(self):
        category = self.env["ir.module.category"].create({"name": "Doomed"})
        response = self.url_open(
            f"/api/v1/orm/ir.module.category/unlink?ids={category.id}",
            headers=self._headers(),
            method="DELETE",
        )
        self.assertEqual(response.status_code, 403)
        error = response.json()["error"]
        self.assertEqual(error["code"], "access_denied")
        self.assertNotIn("ir.module.category", error["message"])
        self.assertNotIn("Doomed", error["message"])

    @mute_logger(_DISPATCHER_LOGGER)
    def test_read_nonexistent_model_is_404(self):
        response = self.url_open(
            "/api/v1/orm/no.such.model/read?ids=1", headers=self._headers()
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
