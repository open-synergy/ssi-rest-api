# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# `lib` replaces the `ssi_rest_api` dispatcher registered under
# `_dispatchers['ssi_rest']` (`Dispatcher.__init_subclass__`, core) with a
# subclass that also persists a `ssi_rest_request_log` row per request --
# see `lib/dispatcher.py`'s module docstring. `ssi_rest_api` is a hard
# `depends`, so its own `lib/dispatcher` import has already registered the
# base class by the time this package is imported.
from . import lib  # noqa: F401
from . import models  # noqa: F401
