#!/usr/bin/env python3
"""Bump version across all project manifest files."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = {
    "backend/pyproject.toml": (
        re.compile(r'^(version\s*=\s*")([^"]+)(")', re.MULTILINE),
        r"\g<1>{version}\3",
    ),
    "frontend/package.json": None,  # handled via json
    "desktop/src-tauri/Cargo.toml": (
        re.compile(r'^(version\s*=\s*")([^"]+)(")', re.MULTILINE),
        r"\g<1>{version}\3",
    ),
    "desktop/src-tauri/tauri.conf.json": None,  # handled via json
}

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z\-.]+))?(?:\+(?P<build>[0-9A-Za-z\-.]+))?$"
)


def validate_semver(version: str) -> str:
    if not SEMVER_RE.match(version):
        print(f"Error: '{version}' is not a valid semver string.", file=sys.stderr)
        sys.exit(1)
    return version


def update_toml(path: Path, version: str, pattern: re.Pattern[str], template: str) -> None:
    text = path.read_text()
    new_text = pattern.sub(template.format(version=version), text, count=1)
    if new_text == text:
        print(f"  Warning: no version match in {path.relative_to(ROOT)}")
        return
    path.write_text(new_text)
    print(f"  Updated {path.relative_to(ROOT)}")


def update_json(path: Path, version: str) -> None:
    data = json.loads(path.read_text())
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Updated {path.relative_to(ROOT)}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} 0.2.0", file=sys.stderr)
        sys.exit(1)

    version = validate_semver(sys.argv[1])
    print(f"Bumping to {version}:")

    for rel_path, spec in VERSION_FILES.items():
        path = ROOT / rel_path
        if not path.exists():
            print(f"  Skipped {rel_path} (not found)")
            continue
        if spec is None:
            update_json(path, version)
        else:
            pattern, template = spec
            update_toml(path, version, pattern, template)

    print("Done.")


if __name__ == "__main__":
    main()
