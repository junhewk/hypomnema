#!/usr/bin/env python3
"""Orchestrate: next export -> pyinstaller -> tauri build."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
DESKTOP_DIR = REPO_ROOT / "desktop"
PACKAGING_DIR = DESKTOP_DIR / "packaging"


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print(f"  > {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def build_frontend() -> None:
    print("\n[1/3] Building frontend static export...")
    import os

    env = {**os.environ, "NEXT_EXPORT": "1"}
    run(["npm", "run", "build"], cwd=FRONTEND_DIR, env=env)
    out_dir = FRONTEND_DIR / "out"
    if not out_dir.exists():
        print(f"ERROR: Expected {out_dir} to exist after static export", file=sys.stderr)
        sys.exit(1)
    print(f"  Frontend exported to {out_dir}")


def build_backend() -> None:
    print("\n[2/3] Building PyInstaller sidecar...")
    spec_file = PACKAGING_DIR / "hypomnema.spec"
    run(
        ["pyinstaller", "--noconfirm", str(spec_file)],
        cwd=PACKAGING_DIR,
    )
    print("  Sidecar built successfully")


def build_tauri() -> None:
    print("\n[3/3] Building Tauri application...")
    run(["cargo", "tauri", "build"], cwd=DESKTOP_DIR)
    print("  Tauri build complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Hypomnema desktop app")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-tauri", action="store_true")
    args = parser.parse_args()

    if not args.skip_frontend:
        build_frontend()
    if not args.skip_backend:
        build_backend()
    if not args.skip_tauri:
        build_tauri()

    print("\nDone!")


if __name__ == "__main__":
    main()
