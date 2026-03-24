"""PyInstaller hook for sqlite_vec — include the loadable extension binary."""

from pathlib import Path

import sqlite_vec
from PyInstaller.utils.hooks import collect_dynamic_libs


def sqlite_vec_binary_path() -> str:
    loadable_path = Path(sqlite_vec.loadable_path())
    if loadable_path.exists():
        return str(loadable_path)

    for suffix in (".dylib", ".so", ".dll"):
        candidate = loadable_path.with_suffix(suffix)
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(f"sqlite-vec binary not found for {loadable_path}")


datas = [(sqlite_vec_binary_path(), "sqlite_vec")]
binaries = collect_dynamic_libs("sqlite_vec")
