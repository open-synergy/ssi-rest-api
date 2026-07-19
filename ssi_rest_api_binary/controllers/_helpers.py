# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Small, dependency-free helpers shared by ``controllers/main.py``."""

from odoo.addons.ssi_rest_api.lib.auth import RestAuthError
from odoo.addons.ssi_rest_api_orm.controllers._helpers import (  # noqa: F401
    resolve_model,
)

#: Truthy query-string spellings accepted by every boolean-ish param
#: below (``download``, ``crop``, ...). A query string is always text, so
#: a bare Python ``bool()`` cast would treat ``"false"``/``"0"`` as truthy.
_TRUE_STRINGS = {"1", "true", "yes", "on"}


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE_STRINGS


def resolve_record(env, model_name, res_id):
    """Return ``env[model_name].browse(res_id)`` after confirming the
    record exists — never a phantom recordset silently streamed/written
    as if it were real.

    ACL/record-rule access itself is **not** checked here: the download
    endpoint checks read access explicitly (``record.check_access("read")``,
    a model-level/record-rule check ``ir.binary`` does not perform on its
    own for an arbitrary non-attachment field — see backlog issue #13's
    Keputusan Desain), while the upload endpoint relies on ``write()``'s
    own built-in access check. Never ``sudo()`` — see
    ``ssi_rest_api/models/ssi_rest_access_profile.py`` for the
    subtractive-only rationale this module family inherits from backlog
    issue #7.
    """
    target = resolve_model(env, model_name)
    record = target.browse(res_id)
    if not record.exists():
        raise RestAuthError(
            "missing_record",
            f"{model_name} record {res_id} does not exist.",
            status=404,
        )
    return record
