"""Build Hypomnema desktop app — single-stage PyInstaller build."""

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = REPO_ROOT / "packaging"


def _detect_target_triple() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine, machine)
    system = platform.system().lower()
    if system == "darwin":
        return f"{arch}-apple-darwin"
    elif system == "windows":
        return f"{arch}-pc-windows-msvc"
    else:
        return f"{arch}-unknown-linux-gnu"


def build() -> None:
    target = _detect_target_triple()
    print(f"Building for {target}...")

    spec_file = PACKAGING_DIR / "hypomnema.spec"
    if not spec_file.exists():
        print(f"Error: {spec_file} not found", file=sys.stderr)
        sys.exit(1)

    # Run PyInstaller
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(spec_file)],
        cwd=str(REPO_ROOT),
        check=True,
    )

    dist_dir = PACKAGING_DIR / "dist" / "hypomnema"
    if dist_dir.exists():
        print(f"Build complete: {dist_dir}")
    else:
        print("Warning: dist directory not found after build", file=sys.stderr)


if __name__ == "__main__":
    build()
