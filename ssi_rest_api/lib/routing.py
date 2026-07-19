# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""``rest_route``: version-aware routing decorator for ssi_rest_api.

Wraps :func:`odoo.http.route` so controller authors declare a bare path
(``"/ping"``) instead of repeating ``/api/v1`` (and every other supported
version) on every endpoint, and never forget the invariants every
``ssi_rest`` endpoint must share (``type``, ``save_session``, ``csrf``).
"""

from odoo.http import route

from .constants import PATH_PREFIX, SUPPORTED_VERSIONS


def rest_route(
    paths,
    versions=SUPPORTED_VERSIONS,
    schemes=None,
    operation=None,
    model=None,
    **routing,
):
    """Expose a controller method under ``/api/v<n><path>`` for every
    version in ``versions``, dispatched by :class:`.dispatcher.SsiRestDispatcher`.

    :param paths: a single path or an iterable of paths, each relative to
        ``/api/v<n>`` (e.g. ``"/ping"`` or ``["/ping", "/ping/"]``).
    :param versions: API versions the method serves, oldest first. An
        endpoint whose contract is unchanged in a newer version is simply
        listed under both, e.g. ``versions=(1, 2)``. Must be non-empty:
        registering a route under no version at all is a configuration
        mistake, not a valid "unversioned" endpoint, so it raises instead of
        silently registering nothing.
    :param schemes: opaque payload describing the endpoint's input/output
        schema, forwarded as-is to ``routing['rest_schemes']`` for a later
        backlog item (serializer/schema validation) to consume. Not
        interpreted here.
    :param operation: operation identifier forwarded as-is to
        ``routing['rest_operation']``. Consumed by access-profile rule
        matching (``ssi_rest_access_profile.rule.operation``) when it is
        one of ``read``/``write``/``create``/``unlink``/``call``; any
        other value (including ``None``) simply never equals a rule's
        specific operation, only its ``any`` wildcard.
    :param model: target Odoo model technical name this endpoint operates
        on, forwarded as-is to ``routing['rest_model']``. ``None`` for
        endpoints with no single target model (e.g. ``/ping``); consumed
        by access-profile rule matching (``model_pattern``) the same way
        an empty pattern matches every model.
    :param routing: any other kwarg accepted by :func:`odoo.http.route`
        (``auth``, ``methods``, ...). ``type``, ``save_session`` and
        ``csrf`` are always overridden below and must not be passed in.
    :raises ValueError: if ``versions`` is empty.
    """
    if isinstance(paths, str):
        paths = [paths]
    versions = tuple(versions)
    if not versions:
        raise ValueError("rest_route() requires at least one API version")

    expanded_routes = [
        f"{PATH_PREFIX}/v{version}{path}" for version in versions for path in paths
    ]

    routing["type"] = "ssi_rest"
    routing["save_session"] = False
    routing["csrf"] = False
    routing["rest_version"] = versions
    routing["rest_schemes"] = schemes
    routing["rest_operation"] = operation
    routing["rest_model"] = model

    return route(expanded_routes, **routing)
