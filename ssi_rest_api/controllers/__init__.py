# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# Hard rule: nothing under `models/` may ever import from this package
# (`controllers/`) — see the static test in `tests/test_module_structure.py`.
from . import main  # noqa: F401
