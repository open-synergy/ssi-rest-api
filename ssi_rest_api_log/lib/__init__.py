# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

# Importing `dispatcher` re-registers `_dispatchers['ssi_rest']`
# (`Dispatcher.__init_subclass__`, core `odoo/http.py`) with this module's
# subclass -- see `dispatcher.py`'s module docstring.
from . import dispatcher  # noqa: F401
