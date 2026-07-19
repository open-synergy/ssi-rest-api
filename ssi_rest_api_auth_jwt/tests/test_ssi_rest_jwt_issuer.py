# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Model-level tests for ``ssi_rest_jwt_issuer`` (backlog issue #19).

CRUD, the ``_check_key_source`` constraint, the registered ``jwt`` scheme,
and the 2-record ACL are covered by ``test_data_ssi_rest_jwt_issuer.yaml``.

``TestSsiRestJwtIssuerModelShape`` below is Python murni for a different
reason than the usual ``odoo-yaml-test`` escape hatches: it asserts on
*model/field metadata* (``_fields``, ``hasattr``) rather than on record
data, and the YAML DSL has no action that can read that at all -- same
rationale as ``ssi_rest_api``'s own ``tests/test_module_structure.py``.
"""

from odoo_yaml_test import YamlTransactionCase

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSsiRestJwtIssuer(YamlTransactionCase):
    def test_ssi_rest_jwt_issuer(self):
        self.run_yaml_scenario("test_data_ssi_rest_jwt_issuer.yaml")


@tagged("post_install", "-at_install")
class TestSsiRestJwtIssuerModelShape(TransactionCase):
    """Binding, backlog issue #19's Keputusan Desain: ``ssi_rest_jwt_issuer``
    must never gain ``mixin.master_data`` or ``ssi_backend_mixin``
    semantics -- several issuers must be able to stay active at once,
    across companies, which ``ssi_backend_mixin``'s "one active record per
    company" ``action_running()`` would silently break.
    """

    def test_model_has_no_backend_mixin_semantics(self):
        model = self.env["ssi_rest_jwt_issuer"]
        self.assertNotIn(
            "company_id",
            model._fields,
            "ssi_rest_jwt_issuer must not gain a company_id field -- that "
            "would mean ssi_backend_mixin (rejected by design) crept back "
            "in.",
        )
        self.assertFalse(
            hasattr(model, "action_running"),
            "ssi_rest_jwt_issuer must not gain an action_running method -- "
            "that is ssi_backend_mixin's 'one active record per company' "
            "exclusivity switch, deliberately not wanted here.",
        )

    def test_shared_secret_is_restricted_to_group_system(self):
        field = self.env["ssi_rest_jwt_issuer"]._fields["shared_secret"]
        self.assertEqual(
            field.groups,
            "base.group_system",
            "shared_secret must stay readable/writable only by "
            "base.group_system -- it must never be exposed through "
            "fields_get()/read() to any other group, and therefore never "
            "returned by any ssi_rest endpoint either.",
        )
