"""Desktop sidecar entry point for PyInstaller-bundled backend."""

from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="hypomnema-server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    data_dir, static_dir, sqlite_vec_path = _resolve_paths()

    import os

    os.environ.setdefault("HYPOMNEMA_MODE", "desktop")
    os.environ.setdefault("HYPOMNEMA_HOST", "127.0.0.1")
    os.environ.setdefault("HYPOMNEMA_DB_PATH", str(data_dir / "hypomnema.db"))
    if sqlite_vec_path:
        os.environ.setdefault("HYPOMNEMA_SQLITE_VEC_PATH", sqlite_vec_path)
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
