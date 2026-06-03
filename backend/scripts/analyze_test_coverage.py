"""Analyze which backend app functions appear referenced in tests."""

import ast
import re
from pathlib import Path
from typing import Dict, List


def collect_functions(app_dir: Path) -> Dict[str, List[str]]:
    """Return module name -> function names for every app/*.py module."""
    funcs_by_module = {}  # type: Dict[str, List[str]]
    for py in sorted(app_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        funcs_by_module[py.stem] = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
    return funcs_by_module


def main() -> None:
    """Print functions that do not appear referenced in any test file."""
    root = Path(__file__).resolve().parents[1]
    app_dir = root / "app"
    test_dir = root / "tests"

    funcs_by_module = collect_functions(app_dir)
    test_source = "\n".join(path.read_text(encoding="utf-8") for path in test_dir.glob("test_*.py"))

    missing = []  # type: List[str]
    covered = []  # type: List[str]
    for mod, funcs in sorted(funcs_by_module.items()):
        for fn in funcs:
            patterns = [
                f"{mod}.{fn}",
                f"app.{mod}.{fn}",
                f"def test_{fn}",
                f'test_{fn}(',
            ]
            found = any(pattern in test_source for pattern in patterns)
            if not found and re.search(rf"\b{re.escape(fn)}\b", test_source):
                found = True
            if found:
                covered.append(f"{mod}.{fn}")
            else:
                missing.append(f"{mod}.{fn}")

    print(f"Covered (heuristic): {len(covered)}")
    print(f"Missing (heuristic): {len(missing)}")
    print("\n=== MISSING ===")
    for item in missing:
        print(item)


if __name__ == "__main__":
    main()
