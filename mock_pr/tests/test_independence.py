"""The mock and the Cockpit app stay separate: neither imports the other (D-21)."""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COCKPIT_DIRS = ["cockpit", "config", "sap"]


def imported_modules(directory: Path) -> set[str]:
    """Top-level names of every module imported by the .py files under `directory`."""
    names = set()
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def test_the_mock_does_not_import_django_or_the_app() -> None:
    imports = imported_modules(REPO_ROOT / "mock_pr")

    assert not imports & {"django", "cockpit", "config", "sap"}


def test_the_app_does_not_import_the_mock() -> None:
    for directory in COCKPIT_DIRS:
        assert "mock_pr" not in imported_modules(REPO_ROOT / directory)
