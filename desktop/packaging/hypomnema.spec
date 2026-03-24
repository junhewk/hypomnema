# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Hypomnema backend sidecar (cloud-only profile)."""

import os
import sys
import sqlite_vec
import trafilatura
from pathlib import Path

trafilatura_dir = os.path.dirname(trafilatura.__file__)

block_cipher = None
repo_root = Path(SPECPATH).parent.parent


def sqlite_vec_binary_path() -> str:
    """Resolve sqlite-vec shared library path (duplicated in hook-sqlite_vec.py)."""
    loadable_path = Path(sqlite_vec.loadable_path())
    if loadable_path.exists():
        return str(loadable_path)

    for suffix in (".dylib", ".so", ".dll"):
        candidate = loadable_path.with_suffix(suffix)
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(f"sqlite-vec binary not found for {loadable_path}")

# Frontend static export — bundled as static/ inside the frozen app
frontend_out = repo_root / "frontend" / "out"
frontend_datas = [(str(frontend_out), "static")] if frontend_out.exists() else []

# Platform-specific excludes
platform_excludes = []
if sys.platform == "linux":
    platform_excludes += ["AppKit", "CoreFoundation"]
elif sys.platform == "darwin":
    platform_excludes += ["gi", "dbus"]

a = Analysis(
    [str(repo_root / "backend" / "src" / "hypomnema" / "desktop.py")],
    pathex=[str(repo_root / "backend" / "src")],
    binaries=[],
    datas=[
        (sqlite_vec_binary_path(), "sqlite_vec"),
        (os.path.join(trafilatura_dir, "settings.cfg"), "trafilatura"),
        (os.path.join(trafilatura_dir, "data"), os.path.join("trafilatura", "data")),
    ] + frontend_datas,
    hiddenimports=[
        "hypomnema",
        "hypomnema.main",
        "hypomnema.api",
        "hypomnema.api.documents",
        "hypomnema.api.engrams",
        "hypomnema.api.feeds",
        "hypomnema.api.search",
        "hypomnema.api.settings",
        "hypomnema.api.viz",
        "hypomnema.api.health",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[str(Path(SPECPATH))],
    runtime_hooks=[],
    excludes=[
        "torch",
        "transformers",
        "sentence_transformers",
        "numpy.core._multiarray_tests",
        "tkinter",
        "matplotlib",
    ] + platform_excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hypomnema-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="hypomnema-server",
)
