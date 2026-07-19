# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# Import order is binding: `lib` (dispatcher & routing constants) MUST be
# imported before `models`, and `models` MUST be imported before
# `controllers`. Route registration (`@route` decoration) asserts the
# dispatcher type is already known, so the dispatcher registry has to exist
# before any controller module is imported.
from . import lib  # noqa: F401
from . import models  # noqa: F401
from . import controllers  # noqa: F401
