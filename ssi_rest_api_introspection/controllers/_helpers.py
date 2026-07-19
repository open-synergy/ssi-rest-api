# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Small, dependency-free helper shared by ``controllers/main.py``."""

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError


def resolve_readable_model(env, model_name):
    """Return ``env[model_name]``, after confirming it exists and the
    current user may read it.

    :raises RestAuthError: 422 if ``model_name`` is empty, 404 if it does
        not name a real model.
    :raises odoo.exceptions.AccessError: (via ``ir.model.access.check``,
        propagated unchanged) if the model exists but the user has no
        read access to it — classified 403 by
        ``lib/errors.py:classify_exception`` with a generic message, the
        same path every other ACL denial in this module family takes.
    """
    if not model_name:
        raise RestAuthError("validation_error", "model is required.", status=422)
    try:
        target = env[model_name]
    except KeyError as exc:
        raise RestAuthError(
            "missing_record", f"Model {model_name!r} does not exist.", status=404
        ) from exc
    env["ir.model.access"].check(model_name, "read", raise_exception=True)
    return target
