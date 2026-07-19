# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Process-wide, TTL-bound cache of :class:`jwt.PyJWKClient` instances, one
per ``ssi_rest_jwt_issuer`` record (backlog issue #19's binding Keputusan
Desain: "Cache JWKS wajib ber-TTL agar verifikasi tidak menembak jwks_url
pada setiap request; TTL habis -> ambil ulang").

This is a clean-room implementation: no code, naming, or file structure is
copied from the proprietary REST framework this module is functionally
inspired by (see ``ssi_rest_api/lib/dispatcher.py``'s module docstring for
the full rationale).

Deliberately reuses ``PyJWKClient``'s own **Tier 1** cache (its ``lifespan``
constructor argument, verified against ``jwt/jwks_client.py`` in the
installed ``pyjwt`` package) instead of re-implementing a TTL scheme:
``get_signing_key`` only calls ``fetch_data()`` (the one network round-trip)
when the cached JWK Set is empty or older than ``lifespan`` seconds. What
this module adds on top is keeping *one* ``PyJWKClient`` alive per issuer
**across requests** -- a fresh instance every request would reset that
cache and defeat the TTL entirely.
"""

import threading

from jwt import PyJWKClient

#: How long a fetched JWK Set is trusted before ``PyJWKClient`` fetches it
#: again. Not a configurable field on ``ssi_rest_jwt_issuer`` (out of the
#: field list in backlog issue #19's Keputusan Desain) -- a fixed, generous
#: default balances "don't hammer the issuer's JWKS endpoint" against "pick
#: up a rotated signing key reasonably soon".
JWKS_CACHE_TTL_SECONDS = 300

_lock = threading.Lock()
#: ``issuer_id -> (jwks_url, PyJWKClient)``. Keyed by id so a rename of
#: ``jwks_url`` on the same record invalidates the entry (see
#: :func:`invalidate`/the ``(jwks_url, client)`` tuple check in
#: :func:`get_client`) rather than serving stale keys from the old URL.
_clients = {}


def get_client(issuer_id, jwks_url):
    """Return the cached :class:`jwt.PyJWKClient` for ``issuer_id``,
    creating one (bound to ``jwks_url``, TTL :data:`JWKS_CACHE_TTL_SECONDS`)
    the first time this issuer is seen or after its ``jwks_url`` changes.
    """
    with _lock:
        cached = _clients.get(issuer_id)
        if cached is not None and cached[0] == jwks_url:
            return cached[1]
        client = PyJWKClient(jwks_url, lifespan=JWKS_CACHE_TTL_SECONDS)
        _clients[issuer_id] = (jwks_url, client)
        return client


def invalidate(issuer_id):
    """Drop any cached client for ``issuer_id``.

    Called from ``ssi_rest_jwt_issuer.write()``/``unlink()`` so an edited
    or removed issuer never keeps serving keys fetched under its old
    configuration for the rest of :data:`JWKS_CACHE_TTL_SECONDS`.
    """
    with _lock:
        _clients.pop(issuer_id, None)
