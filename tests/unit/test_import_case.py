"""Checks that first-party imports match file names exactly, including capitalisation.

Windows ignores capitalisation but the Raspberry Pi (Linux) does not, so an import such as
``from Arduino import x`` passes the tests here and fails there with ``ModuleNotFoundError``.
``os.listdir`` returns the real on-disk names, which is what this test compares against.
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKED_LOCATIONS = ("jarvis", "main.py", "tests")

# Imports of the pre-refactor code that are wrong on Linux and still exist. Phase 3 removed the
# last one (main.py no longer imports ``Arduino``); test_known_violations_are_still_real fails
# when an entry no longer applies, so this list cannot go stale.
KNOWN_LEGACY_VIOLATIONS: set[tuple[str, str]] = set()


def _first_party_names(root: Path) -> dict[str, str]:
    """Map lower-case top-level module names to their real on-disk name."""
    names: dict[str, str] = {}
    for entry in os.listdir(root):
        stem = entry[:-3] if entry.endswith(".py") else entry
        names[stem.lower()] = stem
    return names


def find_case_mismatches(source: str, root: Path) -> list[str]:
    """Return the imported modules in ``source`` whose capitalisation differs from disk."""
    first_party = _first_party_names(root)
    mismatches: list[str] = []

    def check(parts: list[str], imported_names: list[str]) -> bool:
        if parts[0].lower() not in first_party:
            return True
        current = root
        for part in parts:
            entries = os.listdir(current)
            if part in entries and (current / part).is_dir():
                current = current / part
            elif f"{part}.py" in entries:
                return True
            else:
                return False
        entries = os.listdir(current)
        for name in imported_names:
            if name in entries or f"{name}.py" in entries:
                continue
            lowered = {entry.lower() for entry in entries}
            if name.lower() in lowered or f"{name.lower()}.py" in lowered:
                return False
        return True

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not check(alias.name.split("."), []):
                    mismatches.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if not check(node.module.split("."), [alias.name for alias in node.names]):
                mismatches.append(node.module)
    return mismatches


def _checked_files() -> list[Path]:
    files: list[Path] = []
    for location in CHECKED_LOCATIONS:
        path = PROJECT_ROOT / location
        if path.is_file():
            files.append(path)
        else:
            files.extend(sorted(path.rglob("*.py")))
    return files


class FindCaseMismatchesTest(unittest.TestCase):
    def test_detects_the_arduino_folder_capitalisation(self) -> None:
        source = "from Arduino.arduino_mega_connection import ArduinoMegaConnection\n"

        self.assertEqual(
            find_case_mismatches(source, PROJECT_ROOT), ["Arduino.arduino_mega_connection"]
        )

    def test_detects_wrong_case_in_a_new_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "jarvis" / "domain").mkdir(parents=True)
            (root / "jarvis" / "domain" / "intents.py").write_text("", encoding="utf-8")

            self.assertEqual(find_case_mismatches("import jarvis.domain.intents\n", root), [])
            self.assertEqual(
                find_case_mismatches("from jarvis.Domain import intents\n", root),
                ["jarvis.Domain"],
            )
            self.assertEqual(
                find_case_mismatches("from jarvis.domain import Intents\n", root),
                ["jarvis.domain"],
            )
            self.assertEqual(
                find_case_mismatches("from jarvis.domain.intents import Intent\n", root), []
            )

    def test_ignores_third_party_and_relative_imports(self) -> None:
        source = "import os\nimport vosk\nfrom . import sibling\nfrom unittest.mock import patch\n"

        self.assertEqual(find_case_mismatches(source, PROJECT_ROOT), [])


class ImportCaseTest(unittest.TestCase):
    def violations(self) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()
        for path in _checked_files():
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            for module in find_case_mismatches(path.read_text(encoding="utf-8"), PROJECT_ROOT):
                found.add((relative, module))
        return found

    def test_imports_match_real_file_names(self) -> None:
        unexpected = self.violations() - KNOWN_LEGACY_VIOLATIONS

        self.assertEqual(sorted(unexpected), [], "Import capitalisation differs from the disk")

    def test_known_violations_are_still_real(self) -> None:
        stale = KNOWN_LEGACY_VIOLATIONS - self.violations()

        self.assertEqual(sorted(stale), [], "Remove these entries from KNOWN_LEGACY_VIOLATIONS")


if __name__ == "__main__":
    unittest.main()
