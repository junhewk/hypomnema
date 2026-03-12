"""Key-value settings store with optional Fernet encryption."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypomnema.crypto import decrypt, encrypt, mask_key

if TYPE_CHECKING:
    import aiosqlite


async def get_setting(db: aiosqlite.Connection, key: str, *, fernet_key: bytes) -> str | None:
    """Get a single setting, decrypting if needed."""
    cursor = await db.execute("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if row is None:
        return None
    value, is_encrypted = row[0], row[1]
    if is_encrypted:
        return decrypt(value, fernet_key)
    return str(value)


async def set_setting(
    db: aiosqlite.Connection,
    key: str,
    value: str,
    *,
    fernet_key: bytes,
    encrypt_value: bool = False,
) -> None:
    """Upsert a setting, optionally encrypting the value."""
    stored = encrypt(value, fernet_key) if encrypt_value else value
    await db.execute(
        "INSERT INTO settings (key, value, encrypted) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "encrypted = excluded.encrypted, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
        (key, stored, int(encrypt_value)),
    )
    await db.commit()


async def get_all_settings(db: aiosqlite.Connection, *, fernet_key: bytes) -> dict[str, str]:
    """Get all settings, decrypting encrypted values."""
    cursor = await db.execute("SELECT key, value, encrypted FROM settings")
    rows = await cursor.fetchall()
    result: dict[str, str] = {}
    for key, value, is_encrypted in rows:
        if is_encrypted:
            result[key] = decrypt(value, fernet_key)
        else:
            result[key] = str(value)
    return result


async def get_all_settings_masked(db: aiosqlite.Connection) -> dict[str, str]:
    """Get all settings; encrypted values are masked (last 4 chars only)."""
    cursor = await db.execute("SELECT key, value, encrypted FROM settings")
    rows = await cursor.fetchall()
    result: dict[str, str] = {}
    for key, value, is_encrypted in rows:
        if is_encrypted:
            result[key] = mask_key(value)
        else:
            result[key] = str(value)
    return result
