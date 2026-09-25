from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_catalog


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

    def test_packages_have_platform_independent_metadata(self) -> None:
        catalog = json.loads((ROOT / "dist/catalog.json").read_text())
        for app in catalog["apps"]:
            archive = ROOT / "dist" / app["archive"]
            with zipfile.ZipFile(archive) as package:
                for info in package.infolist():
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.date_time, (2020, 1, 1, 0, 0, 0))

    def test_packages_contain_canonical_source_bytes(self) -> None:
        catalog = json.loads((ROOT / "dist/catalog.json").read_text())
        for app in catalog["apps"]:
            app_directory = ROOT / "apps" / app["id"]
            source_files = sorted(
                path
                for path in app_directory.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            )
            archive = ROOT / "dist" / app["archive"]
            with zipfile.ZipFile(archive) as package:
                packaged_files = set(package.namelist()) - {"manifest.json"}
                expected_files = {
                    path.relative_to(app_directory).as_posix()
                    for path in source_files
                }
                self.assertEqual(packaged_files, expected_files)
                for source in source_files:
                    relative = source.relative_to(app_directory).as_posix()
                    self.assertEqual(
                        package.read(relative),
                        build_catalog.package_file_bytes(source),
                    )

    def test_package_output_is_independent_of_text_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            app.mkdir()
            source = app / "main.py"
            lf_package = root / "lf.sopkg"
            crlf_package = root / "crlf.sopkg"

            source.write_bytes(b"print('one')\nprint('two')\n")
            build_catalog.write_package(app, {}, lf_package)
            source.write_bytes(b"print('one')\r\nprint('two')\r\n")
            build_catalog.write_package(app, {}, crlf_package)

            self.assertEqual(lf_package.read_bytes(), crlf_package.read_bytes())

    def test_package_output_preserves_binary_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "app"
            app.mkdir()
            payload = b"\x89PNG\r\n\x1a\nbinary\r\ndata"
            (app / "image.bin").write_bytes(payload)
            package_path = root / "binary.sopkg"

            build_catalog.write_package(app, {}, package_path)

            with zipfile.ZipFile(package_path) as package:
                self.assertEqual(package.read("image.bin"), payload)


if __name__ == "__main__":
    unittest.main()
