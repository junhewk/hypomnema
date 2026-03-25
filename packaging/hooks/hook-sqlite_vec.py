"""PyInstaller hook for sqlite-vec extension."""
from __future__ import annotations

from pathlib import Path

datas = []
binaries = []

try:
    import sqlite_vec
    vec_dir = Path(sqlite_vec.__file__).parent
    for ext in (".dylib", ".so", ".dll"):
        for f in vec_dir.glob(f"*{ext}"):
            binaries.append((str(f), "sqlite_vec"))
except ImportError:
    pass
