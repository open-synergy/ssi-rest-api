# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""``auth='ssi_rest'`` Odoo auth method: selects a REST authentication
provider from the ``ssi_rest_auth_scheme`` registry.

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by. That framework's approach (monkey-patching ``http.Root`` to
try every registered provider in turn, silently swallowing a failed
provider's exception before trying the next one) is not applicable to Odoo
19 anyway (``Root`` no longer exists there) and is not reproduced here even
in spirit: this implementation resolves *at most one* provider per request
(see :meth:`IrHttp._auth_method_ssi_rest`), so a provider whose credential
verification fails can never be silently retried against another provider's
verification logic.
"""

import logging

from werkzeug.exceptions import InternalServerError

from odoo import models
from odoo.http import request

from ..lib.auth import RestAuthError

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _authenticate(cls, endpoint):
        # Stashed *before* `super()._authenticate` resolves and calls
        # `_auth_method_ssi_rest` below, so that method can restrict which
        # schemes it accepts for this specific route (`rest_route(...,
        # schemes=(...))`, see `lib/routing.py`). `None` means "no
        # restriction: every active scheme is a candidate".
        request.rest_routing = endpoint.routing.get("rest_schemes")
        return super()._authenticate(endpoint)

    @classmethod
    def _auth_method_ssi_rest(cls):
        """Resolve the request's credential against the active
        ``ssi_rest_auth_scheme`` registry and authenticate it.

        Algorithm (binding, see backlog issue #4's Keputusan Desain):

        1. Read active schemes ordered by ``sequence`` (cached).
        2. Call ``_rest_auth_extract()`` on every candidate scheme's
           provider; ``None`` means "this request carries no credential for
           this scheme" and is the *only* silently-skipped case.
        3. More than one provider extracting a credential is rejected as
           ``400 multiple_credentials`` — accepting it would mean guessing
           which credential the client actually intended.
        4. No provider extracting anything is rejected as ``401`` with a
           combined ``WWW-Authenticate`` challenge.
        5. Exactly one provider extracted a credential: its
           ``_rest_auth_verify()`` is called, and *only* that provider's.
           A verification failure is a ``401`` immediately — there is no
           second provider left to fall through to by construction, which
           is the explicit fix for the proprietary framework's behaviour
           described in the module docstring above.
        6. A provider raising anything other than
           :class:`~odoo.addons.ssi_rest_api.lib.auth.RestAuthError` (a
           contract violation) is logged and surfaced as ``500``, never as
           ``401``/``403``.
        7. On success, the environment's user is switched, the session is
           marked non-persistent, and the result is stashed on
           ``request.rest_auth`` for the endpoint to read.
        """
        env = request.env
        schemes = env["ssi_rest_auth_scheme"]._get_active_schemes()
        allowed_schemes = request.rest_routing
        if allowed_schemes:
            schemes = tuple(
                (code, provider_model)
                for code, provider_model in schemes
                if code in allowed_schemes
            )

        extracted = []
        for code, provider_model in schemes:
            provider = env[provider_model]
            try:
                credential = provider._rest_auth_extract()
            except RestAuthError:
                raise
            except Exception:
                _logger.exception(
                    "ssi_rest auth: unexpected error extracting credential "
                    "for scheme %s (provider %s)",
                    code,
                    provider_model,
                )
                raise InternalServerError() from None
            if credential is not None:
                extracted.append((code, provider, credential))

        if len(extracted) > 1:
            raise RestAuthError(
                "multiple_credentials",
                "More than one authentication scheme provided credentials "
                "for this request.",
                status=400,
            )

        if not extracted:
            raise RestAuthError(
                "authentication_required",
                "Authentication is required to access this resource.",
                status=401,
                headers=cls._ssi_rest_challenge_headers(schemes),
            )

        code, provider, credential = extracted[0]
        try:
            result = provider._rest_auth_verify(credential)
        except RestAuthError:
            raise
        except Exception:
            _logger.exception(
                "ssi_rest auth: unexpected error verifying credential for "
                "scheme %s",
                code,
            )
            raise InternalServerError() from None

        request.update_env(user=result.uid)
        request.session.can_save = False
        request.rest_auth = result

    @classmethod
    def _ssi_rest_challenge_headers(cls, schemes):
        """Build the combined ``WWW-Authenticate`` header for ``schemes``
        (an iterable of ``(code, provider_model)``), skipping any provider
        whose challenge is empty."""
        env = request.env
        challenges = [
            challenge
            for challenge in (
                env[provider_model]._rest_auth_challenge()
                for _code, provider_model in schemes
            )
            if challenge
        ]
        if not challenges:
            return []
        return [("WWW-Authenticate", ", ".join(challenges))]
