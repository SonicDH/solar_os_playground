from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class CatalogTest(unittest.TestCase):
    def test_generated_catalog_is_current(self) -> None:
        subprocess.run(
            [sys.executable, "scripts/build_catalog.py", "--check"],
            cwd=ROOT,
            check=True,
        )

    def test_packages_contain_declared_entries(self) -> None:
        catalog = json.loads((ROOT / "dist/catalog.json").read_text())
        for app in catalog["apps"]:
            archive = ROOT / "dist" / app["archive"]
            with zipfile.ZipFile(archive) as package:
                self.assertIn("manifest.json", package.namelist())
                self.assertIn(app["entry"], package.namelist())


if __name__ == "__main__":
    unittest.main()
