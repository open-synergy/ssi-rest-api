# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Tests for the ``ssi_rest_serializer`` AbstractModel (backlog issue #8).

Python murni — pemicu P1 (L-01/L-02): `_serialize()`/`_specification_from_query()`
return plain Python data (list of dict, or a specification dict) that is
never itself a record field — the YAML DSL's `assert` action only reads a
dotted `getattr` path off a record kept in its scenario registry, it has
no way to capture or compare an arbitrary method return value at all.

Uses only `res.partner`/`res.users` fields (already available from `base`,
this module's only real dependency besides `web`/`ssi_master_data_mixin`)
so these tests do not depend on any addon outside what CI actually
installs for this module.
"""

import base64
import datetime
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSsiRestSerializerConversion(TransactionCase):
    """Direct tests of the pure value-conversion helpers — no record
    needed, so a raw value is passed straight in."""

    def setUp(self):
        super().setUp()
        self.serializer = self.env["ssi_rest_serializer"]

    def test_serialize_datetime_format(self):
        value = datetime.datetime(2026, 7, 19, 13, 45, 30)
        self.assertEqual(
            self.serializer._serialize_datetime(value), "2026-07-19T13:45:30Z"
        )

    def test_serialize_datetime_false_stays_false(self):
        self.assertFalse(self.serializer._serialize_datetime(False))

    def test_serialize_date_format(self):
        value = datetime.date(2026, 7, 19)
        self.assertEqual(self.serializer._serialize_date(value), "2026-07-19")

    def test_serialize_binary_default_has_no_base64(self):
        raw = base64.b64encode(b"hello world")
        result = self.serializer._serialize_binary(raw, {})
        self.assertEqual(set(result), {"size", "checksum", "url"})
        self.assertEqual(result["size"], len(b"hello world"))
        self.assertFalse(result["url"])

    def test_serialize_binary_inline_option_returns_base64(self):
        raw = base64.b64encode(b"hello world")
        result = self.serializer._serialize_binary(raw, {"binary": "inline"})
        self.assertEqual(result, raw)


@tagged("post_install", "-at_install")
class TestSsiRestSerializerSpecification(TransactionCase):
    def setUp(self):
        super().setUp()
        self.serializer = self.env["ssi_rest_serializer"]
        self.parent = self.env["res.partner"].create({"name": "Parent Co"})
        self.partner = self.env["res.partner"].create(
            {
                "name": "Child Contact",
                "parent_id": self.parent.id,
                "type": "invoice",
                "partner_latitude": 1.23456789,
            }
        )

    def test_many2one_default_is_id_and_display_name(self):
        result = self.serializer._serialize(self.partner, {"parent_id": {}})
        self.assertEqual(
            result[0]["parent_id"], {"id": self.parent.id, "display_name": "Parent Co"}
        )

    def test_many2one_id_option_returns_bare_id(self):
        specification = self.serializer._specification_from_query(
            {"fields": "parent_id", "m2o": "id"}
        )
        result = self.serializer._serialize(self.partner, specification)
        self.assertEqual(result[0]["parent_id"], self.parent.id)

    def test_one2many_nested_specification_expands_fields(self):
        result = self.serializer._serialize(
            self.parent, {"child_ids": {"fields": {"name": {}}}}
        )
        self.assertEqual(result[0]["child_ids"], [{"name": "Child Contact"}])

    def test_one2many_without_nested_specification_is_id_list(self):
        result = self.serializer._serialize(self.parent, {"child_ids": {}})
        self.assertEqual(result[0]["child_ids"], self.partner.ids)

    def test_two_level_dotted_path_expands_via_query_options(self):
        # Two relation hops (child_ids -> parent_id) ending on a scalar
        # field (name): the nested "fields" on parent_id means parent_id
        # itself is serialized per that nested spec, not the default
        # {"id", "display_name"} shape.
        specification = self.serializer._specification_from_query(
            {"fields": "child_ids.parent_id.name"}
        )
        result = self.serializer._serialize(self.parent, specification)
        self.assertEqual(result[0]["child_ids"], [{"parent_id": {"name": "Parent Co"}}])

    def test_selection_default_is_raw_value_only(self):
        result = self.serializer._serialize(self.partner, {"type": {}})
        self.assertEqual(result[0]["type"], "invoice")

    def test_selection_labels_option_adds_label(self):
        specification = self.serializer._specification_from_query(
            {"fields": "type", "labels": "1"}
        )
        result = self.serializer._serialize(self.partner, specification)
        self.assertEqual(result[0]["type"]["value"], "invoice")
        self.assertTrue(result[0]["type"]["label"])

    def test_float_digits_rounding(self):
        result = self.serializer._serialize(self.partner, {"partner_latitude": {}})
        # res.partner.partner_latitude has digits=(10, 7).
        self.assertEqual(result[0]["partner_latitude"], round(1.23456789, 7))

    def test_fields_shorthand_matches_equivalent_specification(self):
        shorthand = self.serializer._specification_from_query(
            {"fields": "name,parent_id"}
        )
        via_shorthand = self.serializer._serialize(self.partner, shorthand)
        via_specification = self.serializer._serialize(
            self.partner, {"name": {}, "parent_id": {}}
        )
        self.assertEqual(via_shorthand, via_specification)

    def test_unknown_field_raises_validation_error_not_key_error(self):
        with self.assertRaises(ValidationError):
            self.serializer._serialize(self.partner, {"no_such_field": {}})

    def test_field_without_group_access_is_dropped_not_raised(self):
        restricted_user = self.env["res.users"].create(
            {
                "name": "Restricted Field User",
                "login": "ssi_rest_serializer_restricted_user@example.com",
                "email": "ssi_rest_serializer_restricted_user@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        field = self.partner._fields["partner_latitude"]
        partner_as_restricted = self.partner.with_user(restricted_user)
        serializer_as_restricted = self.serializer.with_user(restricted_user)
        with patch.object(field, "groups", "base.group_system"):
            result = serializer_as_restricted._serialize(
                partner_as_restricted, {"name": {}, "partner_latitude": {}}
            )
        self.assertIn("name", result[0])
        self.assertNotIn("partner_latitude", result[0])
