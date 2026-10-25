"""The application layer may only depend on the domain, the ports and itself."""

import ast
import unittest
from pathlib import Path

_APPLICATION_DIR = Path(__file__).resolve().parents[3] / "jarvis" / "application"
_ALLOWED_PREFIXES = ("jarvis.application", "jarvis.domain", "jarvis.ports")


def _imported_jarvis_modules(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return [name for name in modules if name == "jarvis" or name.startswith("jarvis.")]


class ApplicationLayeringTest(unittest.TestCase):
    def test_application_only_imports_domain_ports_and_application(self) -> None:
        files = sorted(_APPLICATION_DIR.rglob("*.py"))
        self.assertTrue(files)
        for path in files:
            for module in _imported_jarvis_modules(path.read_text(encoding="utf-8")):
                with self.subTest(file=path.name, module=module):
                    self.assertTrue(module.startswith(_ALLOWED_PREFIXES), module)


if __name__ == "__main__":
    unittest.main()
