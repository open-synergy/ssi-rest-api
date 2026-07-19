# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Scoped, profile-bound REST API key (backlog issue #18).

Clean-room: no code, naming, or file structure is copied from the
proprietary REST framework this module is functionally inspired by (see
``ssi_rest_api/lib/dispatcher.py``'s module docstring for the full
rationale).

This deliberately does **not** duplicate Odoo core's own
``res.users.apikeys`` (already wrapped, as-is, by ``ssi_rest_auth_bearer``
in ``ssi_rest_api``): every key here carries its own ``profile_id``
(``ssi_rest_access_profile``), so one user can hold several keys with
different, narrower scopes -- something a single flat
``res.users.apikeys`` scope cannot express.

Hashing technique note (binding, do not remove when editing this file):
verified against Odoo 19 core's own ``res.users.apikeys`` (``base/models/
res_users_apikeys.py``), which hashes the raw key with a ``passlib``
``CryptContext`` and stores a short plaintext ``index`` prefix alongside it
for a fast, targeted lookup -- never a full-table scan followed by
verifying every row. The same technique is reused here (``passlib`` is
already an Odoo core dependency, used for password hashing itself), not a
plaintext or MD5 comparison.
"""

import logging
import secrets

from passlib.context import CryptContext

from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

#: `pbkdf2_sha512` is the same algorithm family Odoo core's own password
#: hashing (`res.users._crypt_context`) and `res.users.apikeys` already
#: rely on -- a slow, salted, industry-standard KDF, not a fast general
#: purpose hash (MD5/SHA-256) that would be vulnerable to brute-forcing a
#: stolen `key_hash`.
_CRYPT_CONTEXT = CryptContext(schemes=["pbkdf2_sha512"])

#: Static prefix on every generated raw key, purely a human/tooling hint
#: ("this looks like a SSI REST API key") -- carries no security weight of
#: its own.
_KEY_PREFIX = "sak_"

#: Length of the plaintext lookup prefix stored in `key_index`. Long enough
#: to keep collisions rare (roughly 8 characters of real randomness after
#: the static `_KEY_PREFIX`), short enough to stay a cheap, highly
#: selective index -- collisions, if any, are still resolved correctly by
#: `_authenticate` verifying every candidate's hash, never trusted alone.
_KEY_INDEX_SIZE = 12


class SsiRestApiKey(models.Model):
    """One profile-scoped REST API key belonging to a single user.

    Deliberately **not** master data (no ``mixin.master_data``, matching
    ``ssi_rest_access_profile``'s own reasoning): a key is a security
    credential administered by its owner (or an administrator), not
    business reference data.

    BINDING (do not remove this comment when editing this class): the raw
    key value only ever exists transiently, as the return value of
    :meth:`_generate_new_key` -- it is never written to any stored field.
    Only ``key_hash`` (a ``passlib`` hash) and ``key_index`` (a short
    plaintext lookup prefix, not secret on its own) are persisted.
    """

    _name = "ssi_rest_api_key"
    _description = "REST API Key"
    _order = "id desc"

    name = fields.Char(
        required=True,
        help="Descriptive label for this API key (e.g. which integration "
        "it was issued to), shown in place of the key value itself.",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.user,
        help="User this key authenticates as when used on a ssi_rest "
        "request. A single user may hold several keys, each with its own "
        "profile_id.",
    )
    profile_id = fields.Many2one(
        comodel_name="ssi_rest_access_profile",
        string="Access Profile",
        required=True,
        ondelete="restrict",
        help="Access profile this key is scoped to. A request "
        "authenticated with this key only ever carries this single "
        "profile -- never the union of every profile user_id might "
        "otherwise qualify for -- and a profile can only narrow access "
        "already granted by Odoo's own ACL/record rules, never widen it.",
    )
    key_index = fields.Char(
        readonly=True,
        index=True,
        copy=False,
        help="Plaintext prefix of the generated raw key, used to look up "
        "a candidate row quickly (indexed) before verifying the full key "
        "against key_hash. Not secret on its own: knowing this prefix "
        "alone never authenticates a request.",
    )
    key_hash = fields.Char(
        readonly=True,
        copy=False,
        help="Salted hash of the full raw key (passlib pbkdf2_sha512). "
        "The raw key itself is never stored anywhere; it only ever "
        "exists as the return value of _generate_new_key(), shown to the "
        "caller once.",
    )
    expiration_date = fields.Datetime(
        help="Optional expiration timestamp. A request authenticated "
        "with a key whose expiration_date has passed is rejected as an "
        "invalid credential, exactly like a wrong key.",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive keys are rejected as an invalid credential, "
        "exactly like a wrong or expired key, and are hidden from the "
        "default list view.",
    )
    last_used_date = fields.Datetime(
        readonly=True,
        copy=False,
        help="Timestamp of this key's last successful authentication. "
        "Updated through a cursor independent of the authenticating "
        "request's own transaction (see _touch_last_used_date), never "
        "through that request's own env.cr.",
    )

    def action_generate_key(self):
        for record in self.sudo():
            result = record._generate_key_action()
        return result

    def _generate_key_action(self):
        """Generate a new raw key for this record and surface it to the
        caller exactly once, through a client notification -- never
        through a stored field, so there is nothing left to read back a
        second time.
        """
        self.ensure_one()
        raw_key = self._generate_new_key()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("API Key Generated"),
                "message": self.env._(
                    "Copy this key now, it will not be shown again:\n\n%(raw_key)s",
                    raw_key=raw_key,
                ),
                "sticky": True,
            },
        }

    def _generate_new_key(self):
        """Generate a brand-new raw key for this record, persist only its
        hash and lookup index, and return the raw value.

        This is the *only* point in this model's entire lifecycle where
        the raw key value exists at all; the caller (a button, a script, a
        test) is responsible for using it immediately -- it is discarded
        the moment this method returns. Calling this again on the same
        record invalidates whatever key it held before (the old key_hash
        is simply overwritten), the same "regenerate" semantics as every
        comparable API key UI.
        """
        self.ensure_one()
        raw_key = self._generate_raw_key()
        self.write(
            {
                "key_index": raw_key[:_KEY_INDEX_SIZE],
                "key_hash": _CRYPT_CONTEXT.hash(raw_key),
            }
        )
        return raw_key

    @api.model
    def _generate_raw_key(self):
        # `secrets.token_urlsafe` (CSPRNG, `os.urandom` under the hood) --
        # never `random`, which is not safe for security tokens.
        return _KEY_PREFIX + secrets.token_urlsafe(32)

    @api.model
    def _authenticate(self, raw_key):
        """Return the single active, unexpired ``ssi_rest_api_key`` record
        ``raw_key`` belongs to, or an empty recordset.

        Looks up candidates by ``key_index`` (indexed prefix) first --
        never a full-table scan -- then verifies ``raw_key`` against each
        candidate's ``key_hash`` with ``passlib``, which compares in
        constant time internally. ``sudo()`` here mirrors
        ``ssi_rest_auth_basic``/``ssi_rest_auth_bearer``'s own credential
        lookup (``res.users.sudo()``/``res.users.apikeys``): this runs
        *before* the request's identity is known at all, so there is no
        caller ACL to respect yet.
        """
        if not raw_key:
            return self.browse()
        prefix = raw_key[:_KEY_INDEX_SIZE]
        now = fields.Datetime.now()
        candidates = self.sudo().search(
            [
                ("key_index", "=", prefix),
                ("active", "=", True),
                "|",
                ("expiration_date", "=", False),
                ("expiration_date", ">", now),
            ]
        )
        for candidate in candidates:
            if candidate.key_hash and _CRYPT_CONTEXT.verify(
                raw_key, candidate.key_hash
            ):
                return candidate
        return self.browse()

    def _touch_last_used_date(self):
        """Record this key's last successful use.

        BINDING (backlog issue #18's Keputusan Desain, same rationale as
        ``ssi_rest_api_log``'s ``lib/dispatcher.py``): writes through
        ``self.env.registry.cursor()`` -- a cursor/transaction entirely
        independent of the authenticating request's own ``env.cr`` -- and
        commits on success, **never** through ``self.env.cr`` directly.
        Writing through the request's own cursor here would force Odoo's
        RO->RW cursor retry on *every* ``readonly=True`` ssi_rest request
        authenticated with an API key, silently running the whole request
        twice. A failure to record this is never allowed to break the
        authentication response: logged and swallowed, never re-raised.
        """
        self.ensure_one()
        if self._skip_last_used_write_under_test_harness():
            return
        key_id = self.id
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["ssi_rest_api_key"].browse(key_id).write(
                    {"last_used_date": fields.Datetime.now()}
                )
        except Exception:  # noqa: BLE001 - never break the auth response
            _logger.exception(
                "ssi_rest_api_auth_apikey: failed to update last_used_date "
                "for ssi_rest_api_key %s",
                key_id,
            )

    def _skip_last_used_write_under_test_harness(self):
        """Whether attempting the last_used_date write right now would hit
        a structural limitation of Odoo's own ``HttpCase`` test harness,
        unrelated to this module's own correctness.

        Mirrors ``ssi_rest_api_log``'s
        ``SsiRestDispatcher._skip_logging_under_test_harness``
        (``lib/dispatcher.py``) for the identical reason: every cursor in
        a test shares *one* physical connection via nested savepoints, and
        that layer refuses to open a read/write nested cursor while the
        currently active one is read-only -- exactly the situation a
        ``readonly=True`` route puts every request in. Never applies in
        production, where ``registry.cursor()`` always opens a genuinely
        separate connection.
        """
        cr = getattr(self.env, "cr", None)
        if cr is None or not getattr(cr, "readonly", False):
            return False
        from odoo import modules  # local import: test-mode flag only

        if not modules.module.current_test:
            return False
        _logger.debug(
            "ssi_rest_api_auth_apikey: skipping last_used_date write for a "
            "read-only cursor request under Odoo's own HttpCase test "
            "harness (nested read/write test cursors from a read-only one "
            "are not supported there); unaffected in production."
        )
        return True
