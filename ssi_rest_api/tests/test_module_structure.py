# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""Static source-layout checks for the ssi_rest_api package skeleton.

These are not Odoo model/behavior tests, so they are deliberately written in
plain Python instead of an `odoo-yaml-test` YAML scenario: the YAML DSL only
asserts on record fields, it has no action that can read raw file content or
parse an import statement, so scanning the module's own source tree is
outside what the DSL can express at all (not merely less convenient there).

They still subclass an Odoo ``BaseCase`` (via ``TransactionCase``, not bare
``unittest.TestCase``) purely so ``test_tags`` gets set by
``BaseCase.__init_subclass__`` — untagged tests are silently skipped by
Odoo's own test runner (``odoo/tests/tag_selector.py``:
``TagsSelector.check``).
"""

import ast
import os
import re

from odoo.tests import TransactionCase, tagged

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Child/detail models are intentionally allowed to use dot notation
# (`<parent_model>.<child_label>`, e.g. "ssi_rest_access_profile.rule").
# Extend this allowlist when a future backlog item adds a legitimate child
# model; every other dotted, non-"mixin."-prefixed `_name` fails this test.
ALLOWED_DOTTED_MODEL_NAMES = set()

# Substrings that must never appear in this module's own source: the
# license of `muk_rest` (the functional reference for this framework)
# requires a clean-room implementation, forbidding copied code, model/field
# naming, or file structure from it.
FORBIDDEN_STRINGS = ("muk_rest",)

# This test file itself legitimately discusses the forbidden strings above
# (as documentation of what must NOT appear elsewhere), so it is excluded
# from the scan.
SELF_FILE = os.path.abspath(__file__)


def _iter_python_files(*subdirs):
    for subdir in subdirs:
        directory = os.path.join(MODULE_ROOT, subdir)
        if not os.path.isdir(directory):
            continue
        for root, _dirs, files in os.walk(directory):
            for filename in files:
                if filename.endswith(".py"):
                    yield os.path.join(root, filename)


def _iter_all_source_files():
    skip_dirs = {".git", "static"}
    for root, dirs, files in os.walk(MODULE_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for filename in files:
            path = os.path.join(root, filename)
            if os.path.abspath(path) == SELF_FILE:
                continue
            if filename.endswith((".py", ".xml", ".rst", ".md")):
                yield path


def _model_name_assignments(tree):
    """Yield ``(class_name, base_names, model_name)`` for every class in
    ``tree`` that defines a `models.Model` / `models.AbstractModel` style
    ``_name = "..."`` class attribute."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = set()
        for base in node.bases:
            if isinstance(base, ast.Attribute):
                base_names.add(base.attr)
            elif isinstance(base, ast.Name):
                base_names.add(base.id)
        model_name = None
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if "_name" not in targets:
                continue
            if isinstance(stmt.value, ast.Constant) and isinstance(
                stmt.value.value, str
            ):
                model_name = stmt.value.value
        if model_name:
            yield node.name, base_names, model_name


@tagged("post_install", "-at_install")
class TestModuleStructure(TransactionCase):
    """Guard rails on the module skeleton that no single Odoo record can
    express: import direction between packages, model naming convention,
    and the clean-room requirement against `muk_rest`.
    """

    def test_models_do_not_import_controllers(self):
        """`models/` must never import from `controllers/` (binding design
        decision: the dispatcher registry has to exist before controllers
        are imported, so the dependency only ever flows the other way)."""
        import_re = re.compile(
            r"^\s*(from\s+\.{1,2}controllers|import\s+\.{0,2}controllers)\b",
            re.MULTILINE,
        )
        offenders = []
        for path in _iter_python_files("models"):
            with open(path, encoding="utf-8") as fobj:
                content = fobj.read()
            if import_re.search(content) or "controllers" in content:
                # Narrow down to genuine import statements only, to avoid
                # false positives on unrelated words containing the
                # substring "controllers".
                if re.search(
                    r"^\s*(from|import)\s+.*\bcontrollers\b",
                    content,
                    re.MULTILINE,
                ):
                    offenders.append(path)
        self.assertFalse(
            offenders,
            f"models/ must not import controllers/: {offenders}",
        )

    def test_main_model_names_use_underscore(self):
        """Main model `_name` must use underscores, never dot notation,
        except for `mixin.*` AbstractModel contracts and explicitly
        allow-listed child/detail models."""
        violations = []
        for path in _iter_python_files("models"):
            with open(path, encoding="utf-8") as fobj:
                tree = ast.parse(fobj.read(), filename=path)
            for class_name, base_names, model_name in _model_name_assignments(tree):
                if "." not in model_name:
                    continue
                if model_name.startswith("mixin."):
                    is_abstract = "AbstractModel" in base_names
                    if not is_abstract:
                        violations.append(
                            f"{path}:{class_name} uses 'mixin.' prefix "
                            f"({model_name!r}) but does not inherit "
                            "models.AbstractModel"
                        )
                    continue
                if model_name in ALLOWED_DOTTED_MODEL_NAMES:
                    continue
                violations.append(
                    f"{path}:{class_name} defines dotted model name "
                    f"{model_name!r} without being allow-listed as a "
                    "child/detail model"
                )
        self.assertFalse(violations, "\n".join(violations))

    def test_no_muk_rest_references(self):
        """Clean-room requirement: no reference to `muk_rest` anywhere in
        this module's own source (code, XML, docs)."""
        offenders = []
        for path in _iter_all_source_files():
            try:
                with open(path, encoding="utf-8") as fobj:
                    content = fobj.read()
            except (UnicodeDecodeError, OSError):
                continue
            lowered = content.lower()
            for forbidden in FORBIDDEN_STRINGS:
                if forbidden.lower() in lowered:
                    offenders.append((path, forbidden))
        self.assertFalse(
            offenders,
            f"Forbidden muk_rest reference(s) found: {offenders}",
        )
