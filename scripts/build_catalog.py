#!/usr/bin/env python3
"""Validate Playground manifests and build a deterministic catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
DIST = ROOT / "dist"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REQUIRED = {
    "id",
    "name",
    "version",
    "runtime",
    "entry",
    "category",
    "description",
    "author",
    "min_solaros",
    "tags",
    "requires",
}
MAX_CATEGORIES = 24
MAX_APPS = 64
MAX_PACKAGE_SIZE = 2 * 1024 * 1024
CAPABILITIES = {
    "psram",
    "display",
    "gfx",
    "cdc",
    "uart",
    "sd",
    "i2c",
    "spi",
    "rtc",
    "battery",
    "audio",
    "audio_input",
    "wifi",
    "ble",
    "gpio",
    "adc",
    "pwm",
    "expansion_gpio",
    "expansion_i2c",
    "expansion_spi",
    "expansion_uart",
    "expansion_adc",
    "expansion_pwm",
    "key",
    "buttons",
    "joystick",
    "adc_dpad",
    "status_led",
    "display_brightness",
    "temperature",
    "humidity",
    "simd",
}
TEXT_LIMITS = {
    "id": 31,
    "name": 47,
    "version": 15,
    "entry": 63,
    "category": 31,
    "description": 127,
    "author": 47,
    "min_solaros": 15,
}


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_relative(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        raise ValueError(f"{field} must be a safe relative path")
    return path.as_posix()


def validate_categories() -> list[dict[str, object]]:
    document = load_json(ROOT / "categories.json")
    if not isinstance(document, dict) or not isinstance(document.get("categories"), list):
        raise ValueError("categories.json must contain a categories array")
    categories: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in document["categories"]:
        if not isinstance(item, dict):
            raise ValueError("category entries must be objects")
        category_id = item.get("id")
        title = item.get("title")
        order = item.get("order")
        if not isinstance(category_id, str) or not ID_RE.fullmatch(category_id):
            raise ValueError(f"invalid category id: {category_id!r}")
        if category_id in seen:
            raise ValueError(f"duplicate category id: {category_id}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"category {category_id} has no title")
        if len(category_id) > TEXT_LIMITS["category"] or len(title.strip()) > 47:
            raise ValueError(f"category {category_id} exceeds SolarOS text limits")
        if not isinstance(order, int) or order < 0:
            raise ValueError(f"category {category_id} has invalid order")
        seen.add(category_id)
        categories.append({"id": category_id, "title": title.strip(), "order": order})
    if not categories or len(categories) > MAX_CATEGORIES:
        raise ValueError(f"catalog must contain 1 through {MAX_CATEGORIES} categories")
    categories.sort(key=lambda item: (int(item["order"]), str(item["title"]).casefold()))
    return categories


def application_files(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        ),
        key=lambda path: path.relative_to(directory).as_posix(),
    )


def validate_manifest(directory: Path, category_ids: set[str]) -> dict[str, object]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{directory.relative_to(ROOT)} has no manifest.json")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path.relative_to(ROOT)} must be an object")
    missing = REQUIRED - manifest.keys()
    unknown = manifest.keys() - REQUIRED
    if missing:
        raise ValueError(f"{manifest_path.relative_to(ROOT)} missing: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{manifest_path.relative_to(ROOT)} unknown fields: {sorted(unknown)}")
    for field, limit in TEXT_LIMITS.items():
        value = manifest[field]
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{directory.name}: {field} exceeds {limit} characters")

    app_id = manifest["id"]
    if not isinstance(app_id, str) or not ID_RE.fullmatch(app_id):
        raise ValueError(f"invalid application id: {app_id!r}")
    if app_id != directory.name:
        raise ValueError(f"application id {app_id!r} must match directory {directory.name!r}")
    if not isinstance(manifest["name"], str) or not manifest["name"].strip():
        raise ValueError(f"{app_id}: name must not be empty")
    if not isinstance(manifest["version"], str) or not VERSION_RE.fullmatch(manifest["version"]):
        raise ValueError(f"{app_id}: version must be MAJOR.MINOR.PATCH")
    if manifest["runtime"] not in {"python", "lua"}:
        raise ValueError(f"{app_id}: runtime must be python or lua")
    entry = safe_relative(str(manifest["entry"]), "entry")
    expected_suffix = ".py" if manifest["runtime"] == "python" else ".lua"
    if not entry.endswith(expected_suffix):
        raise ValueError(f"{app_id}: entry must end in {expected_suffix}")
    if not (directory / entry).is_file():
        raise ValueError(f"{app_id}: entry file does not exist: {entry}")
    if manifest["category"] not in category_ids:
        raise ValueError(f"{app_id}: unknown category {manifest['category']!r}")
    for field in ("description", "author"):
        if not isinstance(manifest[field], str) or not manifest[field].strip():
            raise ValueError(f"{app_id}: {field} must not be empty")
    if not isinstance(manifest["min_solaros"], str) or not VERSION_RE.fullmatch(
        manifest["min_solaros"]
    ):
        raise ValueError(f"{app_id}: min_solaros must be MAJOR.MINOR.PATCH")
    for field in ("tags", "requires"):
        values = manifest[field]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError(f"{app_id}: {field} must be an array of strings")
    if any(len(value) > 23 for value in manifest["tags"]):
        raise ValueError(f"{app_id}: tags are limited to 23 characters")
    if len(" ".join(sorted(set(manifest["tags"]), key=str.casefold))) > 95:
        raise ValueError(f"{app_id}: combined tags exceed 95 characters")
    if any(len(value) > 31 for value in manifest["requires"]):
        raise ValueError(f"{app_id}: requirements are limited to 31 characters")
    unknown_requirements = set(manifest["requires"]) - CAPABILITIES
    if unknown_requirements:
        raise ValueError(
            f"{app_id}: unknown requirements: {sorted(unknown_requirements)}"
        )

    normalized = dict(manifest)
    normalized["entry"] = entry
    normalized["name"] = manifest["name"].strip()
    normalized["description"] = manifest["description"].strip()
    normalized["author"] = manifest["author"].strip()
    normalized["tags"] = sorted(set(manifest["tags"]), key=str.casefold)
    normalized["requires"] = sorted(set(manifest["requires"]), key=str.casefold)
    return normalized


def write_package(directory: Path, manifest: dict[str, object], output: Path) -> None:
    files = application_files(directory)
    timestamp = (2020, 1, 1, 0, 0, 0)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        manifest_bytes = (
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        info = zipfile.ZipInfo("manifest.json", timestamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_bytes)
        for source in files:
            relative = source.relative_to(directory).as_posix()
            safe_relative(relative, "package file")
            info = zipfile.ZipInfo(relative, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def build(output_root: Path) -> dict[str, object]:
    categories = validate_categories()
    category_ids = {str(item["id"]) for item in categories}
    apps: list[dict[str, object]] = []
    seen: set[str] = set()
    if not APPS.is_dir():
        raise ValueError("apps directory does not exist")
    for directory in sorted(path for path in APPS.iterdir() if path.is_dir()):
        manifest = validate_manifest(directory, category_ids)
        app_id = str(manifest["id"])
        if app_id in seen:
            raise ValueError(f"duplicate application id: {app_id}")
        seen.add(app_id)
        version = str(manifest["version"])
        relative_archive = f"packages/{app_id}/{version}/{app_id}-{version}.sopkg"
        archive_path = output_root / relative_archive
        write_package(directory, manifest, archive_path)
        archive_bytes = archive_path.read_bytes()
        if len(archive_bytes) > MAX_PACKAGE_SIZE:
            raise ValueError(f"{app_id}: package exceeds {MAX_PACKAGE_SIZE} bytes")
        catalog_entry = dict(manifest)
        catalog_entry["archive"] = relative_archive
        catalog_entry["size"] = len(archive_bytes)
        catalog_entry["sha256"] = hashlib.sha256(archive_bytes).hexdigest()
        apps.append(catalog_entry)

    if len(apps) > MAX_APPS:
        raise ValueError(f"catalog contains more than {MAX_APPS} applications")
    apps.sort(key=lambda item: (str(item["category"]), str(item["name"]).casefold()))
    catalog = {
        "schema": "solaros.playground.catalog",
        "schema_version": 1,
        "repository": {
            "id": "solar-os-playground",
            "name": "SolarOS Playground",
        },
        "categories": categories,
        "apps": apps,
    }
    (output_root / "catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return catalog


def directories_equal(first: Path, second: Path) -> bool:
    first_files = sorted(
        path.relative_to(first)
        for path in first.rglob("*")
        if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second)
        for path in second.rglob("*")
        if path.is_file()
    )
    return first_files == second_files and all(
        (first / relative).read_bytes() == (second / relative).read_bytes()
        for relative in first_files
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when committed dist output is stale",
    )
    args = parser.parse_args()

    try:
        with tempfile.TemporaryDirectory(prefix="solaros-playground-") as temp:
            generated = Path(temp) / "dist"
            generated.mkdir()
            catalog = build(generated)
            if args.check:
                if not DIST.is_dir() or not directories_equal(generated, DIST):
                    print("dist output is stale; run scripts/build_catalog.py", file=sys.stderr)
                    return 1
            else:
                if DIST.exists():
                    shutil.rmtree(DIST)
                shutil.copytree(generated, DIST)
            print(
                f"validated {len(catalog['apps'])} apps in "
                f"{len(catalog['categories'])} categories"
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"catalog build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
