# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from . import constants  # noqa: F401

# `dispatcher` MUST be imported before any `controllers/` module: importing
# it registers `SsiRestDispatcher` under `_dispatchers['ssi_rest']`
# (`Dispatcher.__init_subclass__`), and `@rest_route(...)` asserts that
# key already exists at controller *decoration* time (`odoo.http.route`).
from . import dispatcher  # noqa: F401
from . import routing  # noqa: F401
