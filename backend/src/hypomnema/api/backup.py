"""Database backup endpoint — produces a consistent SQLite snapshot."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from hypomnema.api.deps import DB

router = APIRouter(prefix="/api", tags=["backup"])


@router.get("/backup")
async def backup_database(request: Request, db: DB) -> FileResponse:
    """Stream a consistent .db snapshot as a download.

    The response header ``X-Hypomnema-Keyfile`` contains the path of the
    Fernet key file that must be preserved alongside the backup for encrypted
    settings (API keys) to remain recoverable.
    """
    settings = request.app.state.settings

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"hypomnema-backup-{timestamp}.db"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    backup_path = Path(tmp.name)

    # aiosqlite's backup() delegates to sqlite3.Connection.backup() in a thread
    dest_conn = sqlite3.connect(str(backup_path))
    try:
        await db.backup(dest_conn)
    finally:
        dest_conn.close()

    return FileResponse(
        path=str(backup_path),
        media_type="application/octet-stream",
        filename=filename,
        headers={
            "X-Hypomnema-Keyfile": str(settings.db_path.parent / ".hypomnema_key"),
        },
        background=BackgroundTask(backup_path.unlink, missing_ok=True),
    )
