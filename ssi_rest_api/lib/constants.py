# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Routing constants shared by the (future) dispatcher and controllers.

These values are deliberately plain Python constants, not
``ir.config_parameter`` entries: the routing map that will consume them is
built once per registry, so a value changed at runtime through
``ir.config_parameter`` would never take effect.
"""

#: URL prefix under which every ssi_rest_api endpoint is exposed.
PATH_PREFIX = "/api"

#: API versions currently supported by the dispatcher, oldest first.
SUPPORTED_VERSIONS = (1,)
