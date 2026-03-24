#!/usr/bin/env python3
"""Orchestrate: next export -> pyinstaller -> tauri build.

Auto-detects platform/arch and produces Tauri-compatible sidecar binaries.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = REPO_ROOT / "frontend"
BACKEND_DIR = REPO_ROOT / "backend"
DESKTOP_DIR = REPO_ROOT / "desktop"
PACKAGING_DIR = DESKTOP_DIR / "packaging"
RESOURCES_DIR = DESKTOP_DIR / "src-tauri" / "resources"
SIDECAR_RESOURCE_DIR = RESOURCES_DIR / "hypomnema-server"
BUNDLE_DIR = DESKTOP_DIR / "src-tauri" / "target" / "release" / "bundle"


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


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def stale_dmg_scratch_paths() -> list[Path]:
    scratch_paths: list[Path] = []
    for bundle_subdir in ("macos", "dmg"):
        bundle_path = BUNDLE_DIR / bundle_subdir
        if not bundle_path.exists():
            continue
        scratch_paths.extend(sorted(bundle_path.glob("rw.*.dmg")))
    return scratch_paths


def mounted_disk_images() -> dict[str, str]:
    if platform.system() != "Darwin":
        return {}

    result = subprocess.run(["hdiutil", "info", "-plist"], capture_output=True)
    if result.returncode != 0:
        print("  WARN: Unable to inspect mounted disk images; skipping cleanup")
        return {}

    try:
        payload = plistlib.loads(result.stdout)
    except Exception as exc:
        print(f"  WARN: Unable to parse mounted disk image list: {exc}")
        return {}

    mounted_images: dict[str, str] = {}
    for image in payload.get("images", []):
        image_path = image.get("image-path")
        if not image_path:
            continue

        dev_entries = [
            entity["dev-entry"]
            for entity in image.get("system-entities", [])
            if entity.get("dev-entry", "").startswith("/dev/")
        ]
        if not dev_entries:
            continue

        mounted_images[image_path] = min(dev_entries, key=len)

    return mounted_images


def detach_disk_image(device: str) -> None:
    for attempt in range(1, 4):
        result = subprocess.run(["hdiutil", "detach", device], capture_output=True, text=True)
        if result.returncode == 0:
            return
        if attempt == 3:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"failed to detach {device}: {detail}")


def clean_stale_dmg_scratch_artifacts() -> None:
    if platform.system() != "Darwin":
        return

    scratch_paths = stale_dmg_scratch_paths()
    if not scratch_paths:
        return

    print("\n[cleanup] Removing stale DMG scratch artifacts...")
    mounted_images = mounted_disk_images()
    for scratch_path in scratch_paths:
        resolved_path = str(scratch_path.resolve())
        device = mounted_images.get(resolved_path)
        if device:
            print(f"  Detaching mounted scratch image {scratch_path.name} ({device})")
            detach_disk_image(device)

        print(f"  Removing {scratch_path}")
        remove_path(scratch_path)


def find_pyinstaller_output(dist_dir: Path) -> Path:
    candidates = [dist_dir / "hypomnema-server", dist_dir / "hypomnema-server.exe"]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = sorted(dist_dir.glob("hypomnema-server*"))
    if len(matches) == 1:
        return matches[0]

    print(f"ERROR: Could not determine PyInstaller output under {dist_dir}", file=sys.stderr)
    sys.exit(1)


def build_frontend() -> None:
    print("\n[1/3] Building frontend static export...")
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
    src_path = find_pyinstaller_output(dist_dir)
    dst_path = dist_dir / f"hypomnema-server-{target_triple}"

    remove_path(dst_path)
    src_path.rename(dst_path)

    # Verify the frozen backend is runnable
    _verify_sidecar(dst_path)

    # Copy the full onedir bundle into Tauri resources.
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    remove_path(SIDECAR_RESOURCE_DIR)
    copy_path(dst_path, SIDECAR_RESOURCE_DIR)
    print(f"  Sidecar copied to {SIDECAR_RESOURCE_DIR}")


def _verify_sidecar(sidecar_path: Path) -> None:
    """Verify the bundled backend sidecar is runnable."""
    executable = sidecar_path
    if sidecar_path.is_dir():
        candidates = [sidecar_path / "hypomnema-server", sidecar_path / "hypomnema-server.exe"]
        executable = next((candidate for candidate in candidates if candidate.exists()), None)
        if executable is None:
            print(f"  ERROR: Sidecar executable not found in {sidecar_path}", file=sys.stderr)
            sys.exit(1)

    result = subprocess.run(
        [str(executable), "--self-check"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  ERROR: Sidecar self-check failed", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print("  Sidecar self-check OK")


def build_tauri(target_triple: str) -> None:
    print("\n[3/3] Building Tauri application...")
    clean_stale_dmg_scratch_artifacts()

    env = os.environ.copy()
    if platform.system() == "Darwin" and not env.get("APPLE_SIGNING_IDENTITY"):
        # Sign during `cargo tauri build` so the generated DMG contains the
        # signed application bundle instead of an unsigned pre-sign copy.
        env["APPLE_SIGNING_IDENTITY"] = "-"
        print("  Using ad-hoc Apple signing identity for Tauri bundling")

    run(["cargo", "tauri", "build"], cwd=DESKTOP_DIR / "src-tauri", env=env)

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
