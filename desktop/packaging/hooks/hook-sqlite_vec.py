"""PyInstaller hook for sqlite_vec — include the loadable extension binary."""

import sqlite_vec
from PyInstaller.utils.hooks import collect_dynamic_libs

datas = [(sqlite_vec.loadable_path(), "sqlite_vec")]
binaries = collect_dynamic_libs("sqlite_vec")
