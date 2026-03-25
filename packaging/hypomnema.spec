# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Hypomnema NiceGUI desktop app."""

import importlib
import platform
from pathlib import Path

block_cipher = None
repo_root = Path(SPECPATH).parent

# Find sqlite-vec binary
def _find_sqlite_vec():
    try:
        import sqlite_vec
        vec_dir = Path(sqlite_vec.__file__).parent
        for ext in (".dylib", ".so", ".dll"):
            for f in vec_dir.glob(f"*{ext}"):
                return str(f)
    except ImportError:
        pass
    return None

sqlite_vec_binary = _find_sqlite_vec()
extra_binaries = [(sqlite_vec_binary, "sqlite_vec")] if sqlite_vec_binary else []

# Trafilatura data
try:
    import trafilatura
    traf_dir = Path(trafilatura.__file__).parent
    traf_data = [(str(traf_dir / "settings.cfg"), "trafilatura")]
    if (traf_dir / "data").is_dir():
        traf_data.append((str(traf_dir / "data"), "trafilatura/data"))
except ImportError:
    traf_data = []

# Static assets (icon, etc.)
static_dir = repo_root / "static"
static_data = [(str(static_dir), "static")] if static_dir.is_dir() else []

a = Analysis(
    [str(repo_root / "src" / "hypomnema" / "cli.py")],
    pathex=[str(repo_root / "src")],
    binaries=extra_binaries,
    datas=traf_data + static_data,
    hiddenimports=[
        "hypomnema",
        "hypomnema.cli",
        "hypomnema.ui",
        "hypomnema.ui.app",
        "hypomnema.ui.pages.stream",
        "hypomnema.ui.pages.document",
        "hypomnema.ui.pages.engram",
        "hypomnema.ui.pages.search",
        "hypomnema.ui.pages.settings",
        "hypomnema.ui.pages.setup",
        "hypomnema.ui.pages.viz",
        "hypomnema.ui.viz.graph",
        "hypomnema.ui.viz.minimap",
        "hypomnema.ui.viz.transforms",
        "nicegui",
        "uvicorn.logging",
        "uvicorn.lifespan.on",
    ],
    hookspath=[str(repo_root / "packaging" / "hooks")],
    excludes=[
        "torch", "transformers", "sentence_transformers",
        "matplotlib", "tkinter", "scipy", "sklearn", "umap",
        "test", "tests", "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="hypomnema",
    debug=False,
    strip=True,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=True,
    name="hypomnema",
)
