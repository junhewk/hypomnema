"""Scribble creation: store text input as a document."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

from hypomnema.db.models import Document
from hypomnema.db.transactions import immediate_transaction


async def create_scribble(
    db: aiosqlite.Connection,
    text: str,
    title: str | None = None,
) -> Document:
    """Create a scribble document from raw text.

    Raises:
        ValueError: If text is empty or whitespace-only.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("Scribble text must not be empty")

    async with immediate_transaction(db):
        cursor = await db.execute(
            "INSERT INTO documents (source_type, title, text) VALUES ('scribble', ?, ?) RETURNING *",
            (title, stripped),
        )
        row = await cursor.fetchone()
        await cursor.close()
    assert row is not None
    return Document.from_row(row)
