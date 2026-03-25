"""Shared helpers for local evaluation harnesses."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from hypomnema.config import Settings
from hypomnema.crypto import decrypt, get_or_create_key

if TYPE_CHECKING:
    from os import PathLike


async def load_effective_settings(base_settings: Settings | None = None) -> Settings:
    """Merge DB-backed runtime settings into a base Settings instance when available."""
    settings = base_settings or Settings()
    if not settings.db_path.exists():
        return settings

    key = get_or_create_key(settings.db_path.parent)
    db_settings = _load_db_settings(settings.db_path, key)
    if db_settings.get("setup_complete"):
        return Settings.with_db_overrides(settings, db_settings)
    return settings


def _load_db_settings(db_path: str | PathLike[str], fernet_key: bytes) -> dict[str, str]:
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute("SELECT key, value, encrypted FROM settings")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        connection.close()

    result: dict[str, str] = {}
    for key, value, is_encrypted in rows:
        if is_encrypted:
            result[str(key)] = decrypt(str(value), fernet_key)
        else:
            result[str(key)] = str(value)
    return result
