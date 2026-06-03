"""Meta-test that every backend app function is referenced by unit tests."""

import ast
import re
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_ROOT / "app"
TEST_DIR = BACKEND_ROOT / "tests"
EXCLUDED_MODULES = {"__init__", "providers", "schemas"}
EXCLUDED_FUNCTIONS = {"_state"}


def collect_app_functions():
    """Return qualified app function names keyed as module.function."""

    functions = {}

    for module_path in sorted(APP_DIR.glob("*.py")):
        module_name = module_path.stem

        if module_name in EXCLUDED_MODULES:
            continue

        module_tree = ast.parse(module_path.read_text(encoding="utf-8"))

        for node in module_tree.body:
            if isinstance(node, ast.FunctionDef):
                functions[f"{module_name}.{node.name}"] = node.name

    return functions


def load_test_source():
    """Return the concatenated source of every backend unit test module."""

    test_sources = []

    for test_path in sorted(TEST_DIR.glob("test_*.py")):
        if test_path.name == Path(__file__).name:
            continue
        test_sources.append(test_path.read_text(encoding="utf-8"))

    return "\n".join(test_sources)


def function_has_test_reference(qualified_name, function_name, test_source):
    """Report whether a function appears to be covered by the unit test suite."""

    module_name, _ = qualified_name.split(".", 1)
    direct_patterns = [
        qualified_name,
        f"app.{qualified_name}",
        f"def test_{function_name}",
        f"test_{function_name}(",
    ]

    if any(pattern in test_source for pattern in direct_patterns):
        return True

    if re.search(rf"\b{re.escape(function_name)}\b", test_source):
        return True

    if module_name.startswith("provider_") and re.search(
        rf"\bproviders\.{re.escape(function_name)}\b",
        test_source,
    ):
        return True

    if module_name == "state_catalog" and re.search(
        rf"\bstate\._{re.escape(function_name)}\b",
        test_source,
    ):
        return True

    return False


class BackendFunctionCoverageTests(unittest.TestCase):
    """Ensures every backend app function is referenced by at least one unit test."""

    @classmethod
    def setUpClass(cls):
        """Load the app function inventory and the combined unit test source once."""

        cls.app_functions = collect_app_functions()
        cls.test_source = load_test_source()

    def test_every_backend_function_has_a_unit_test_reference(self):
        """Fails when any app function is not referenced by the unit test suite."""

        missing_functions = []

        for qualified_name, function_name in sorted(self.app_functions.items()):
            if function_name in EXCLUDED_FUNCTIONS:
                continue

            if not function_has_test_reference(qualified_name, function_name, self.test_source):
                missing_functions.append(qualified_name)

        self.assertEqual(
            missing_functions,
            [],
            "Missing unit test references for: {}".format(", ".join(missing_functions)),
        )


if __name__ == "__main__":
    unittest.main()
