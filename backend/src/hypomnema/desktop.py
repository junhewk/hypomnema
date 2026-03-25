"""Desktop sidecar entry point for PyInstaller-bundled backend."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def _resolve_paths() -> tuple[Path, Path | None, str]:
    """Resolve data dir, static dir, and sqlite-vec path from frozen or dev layout."""
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)  # noqa: SLF001
        import platformdirs

        data_dir = Path(platformdirs.user_data_dir("hypomnema"))
        static_dir = bundle_dir / "static"
        sqlite_vec_path = str(bundle_dir / "sqlite_vec")
    else:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        data_dir = repo_root / "backend" / "data"
        static_dir = repo_root / "frontend" / "out"
        sqlite_vec_path = ""

    return data_dir, static_dir if static_dir.exists() else None, sqlite_vec_path


def _resolve_sqlite_vec_library(sqlite_vec_path: str) -> Path:
    vec_path = Path(sqlite_vec_path)
    if vec_path.is_file():
        return vec_path

    for suffix in (".dylib", ".so", ".dll"):
        candidates = sorted(vec_path.glob(f"*{suffix}"))
        if candidates:
            return candidates[0]

    raise FileNotFoundError(f"sqlite-vec library not found under {vec_path}")


def _run_self_check(data_dir: Path, static_dir: Path | None, sqlite_vec_path: str) -> None:
    if static_dir is not None and not static_dir.exists():
        raise FileNotFoundError(f"Static export directory not found: {static_dir}")

    if sqlite_vec_path:
        ext_path = _resolve_sqlite_vec_library(sqlite_vec_path)
        conn = sqlite3.connect(":memory:")
        try:
            conn.enable_load_extension(True)
            conn.load_extension(str(ext_path.with_suffix("")))
            version = conn.execute("SELECT vec_version()").fetchone()[0]
        finally:
            conn.close()
        print(f"sqlite-vec OK ({version})")

    print(f"data_dir={data_dir}")
    if static_dir is not None:
        print(f"static_dir={static_dir}")
    print("self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hypomnema-server")
    parser.add_argument("--port", type=int, default=8073)
    parser.add_argument("--self-check", action="store_true", help="Validate bundled resources and exit")
    args = parser.parse_args()

    data_dir, static_dir, sqlite_vec_path = _resolve_paths()
    resolved_sqlite_vec_path = str(_resolve_sqlite_vec_library(sqlite_vec_path)) if sqlite_vec_path else ""

    if args.self_check:
        _run_self_check(data_dir, static_dir, sqlite_vec_path)
        return

    import os

    os.environ.setdefault("HYPOMNEMA_MODE", "desktop")
    os.environ.setdefault("HYPOMNEMA_HOST", "127.0.0.1")
    os.environ.setdefault("HYPOMNEMA_DB_PATH", str(data_dir / "hypomnema.db"))
    if resolved_sqlite_vec_path:
        os.environ.setdefault("HYPOMNEMA_SQLITE_VEC_PATH", resolved_sqlite_vec_path)
    if static_dir:
        os.environ.setdefault("HYPOMNEMA_STATIC_DIR", str(static_dir))

    import uvicorn

    uvicorn.run(
        "hypomnema.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
