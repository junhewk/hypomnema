#!/usr/bin/env python3
"""Orchestrate: next export -> pyinstaller -> tauri build.

Auto-detects platform/arch and produces Tauri-compatible sidecar binaries.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_DIR = REPO_ROOT / "backend"
DESKTOP_DIR = REPO_ROOT / "desktop"
PACKAGING_DIR = DESKTOP_DIR / "packaging"
BINARIES_DIR = DESKTOP_DIR / "src-tauri" / "binaries"


def get_target_triple() -> str:
    """Derive the Rust/Tauri target triple for the current platform."""
    machine = platform.machine().lower()
    system = platform.system().lower()

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    arch = arch_map.get(machine)
    if not arch:
        print(f"ERROR: Unsupported architecture: {machine}", file=sys.stderr)
        sys.exit(1)

    if system == "darwin":
        return f"{arch}-apple-darwin"
    elif system == "linux":
        return f"{arch}-unknown-linux-gnu"
    elif system == "windows":
        return f"{arch}-pc-windows-msvc"
    else:
        print(f"ERROR: Unsupported platform: {system}", file=sys.stderr)
        sys.exit(1)


def check_prerequisites(skip_backend: bool, skip_tauri: bool) -> None:
    """Validate required tools are installed."""
    if not skip_backend:
        if not shutil.which("pyinstaller"):
            print("ERROR: pyinstaller not found. Install with: uv sync --group desktop", file=sys.stderr)
            sys.exit(1)

    if not skip_tauri:
        if not shutil.which("cargo"):
            print("ERROR: cargo not found. Install Rust: https://rustup.rs", file=sys.stderr)
            sys.exit(1)
        result = subprocess.run(["cargo", "tauri", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print("ERROR: tauri-cli not found. Install with: cargo install tauri-cli", file=sys.stderr)
            sys.exit(1)


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


def build_backend(target_triple: str) -> None:
    print(f"\n[2/3] Building PyInstaller sidecar for {target_triple}...")
    spec_file = PACKAGING_DIR / "hypomnema.spec"
    run(
        ["pyinstaller", "--noconfirm", str(spec_file)],
        cwd=PACKAGING_DIR,
    )

    # Rename output to include target triple (Tauri sidecar convention)
    dist_dir = PACKAGING_DIR / "dist"
    src_name = dist_dir / "hypomnema-server"
    dst_name = dist_dir / f"hypomnema-server-{target_triple}"

    if dst_name.exists():
        shutil.rmtree(dst_name)
    if src_name.exists():
        src_name.rename(dst_name)
    else:
        print(f"ERROR: Expected {src_name} to exist after PyInstaller build", file=sys.stderr)
        sys.exit(1)

    # Copy to Tauri binaries directory
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    target_bin = BINARIES_DIR / f"hypomnema-server-{target_triple}"
    if target_bin.exists():
        shutil.rmtree(target_bin)
    shutil.copytree(str(dst_name), str(target_bin))
    print(f"  Sidecar copied to {target_bin}")


def build_tauri(target_triple: str) -> None:
    print("\n[3/3] Building Tauri application...")
    run(["cargo", "tauri", "build"], cwd=DESKTOP_DIR / "src-tauri")

    system = platform.system().lower()
    if system == "darwin":
        bundle_type = "dmg"
    elif system == "windows":
        bundle_type = "msi"
    else:
        bundle_type = "appimage"

    bundle_dir = DESKTOP_DIR / "src-tauri" / "target" / "release" / "bundle" / bundle_type
    print(f"  Tauri build complete. Look for artifacts in: {bundle_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Hypomnema desktop app")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend static export")
    parser.add_argument("--skip-backend", action="store_true", help="Skip PyInstaller sidecar build")
    parser.add_argument("--skip-tauri", action="store_true", help="Skip Tauri application build")
    args = parser.parse_args()

    target_triple = get_target_triple()
    print(f"Target: {target_triple}")

    check_prerequisites(args.skip_backend, args.skip_tauri)

    if not args.skip_frontend:
        build_frontend()
    if not args.skip_backend:
        build_backend(target_triple)
    if not args.skip_tauri:
        build_tauri(target_triple)

    print("\nDone!")


if __name__ == "__main__":
    main()
