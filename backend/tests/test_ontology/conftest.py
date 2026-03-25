"""Fixtures for ontology tests."""

import aiosqlite


async def insert_test_doc(
    db: aiosqlite.Connection,
    text: str,
    doc_id: str = "testdoc",
    *,
    source_type: str = "scribble",
    mime_type: str | None = None,
    metadata: str | None = None,
) -> str:
    """Insert a test document and return its id."""
    cursor = await db.execute(
        "INSERT INTO documents (id, source_type, text, mime_type, metadata) VALUES (?, ?, ?, ?, ?) RETURNING *",
        (doc_id, source_type, text, mime_type, metadata),
    )
    row = await cursor.fetchone()
    assert row is not None
    await db.commit()
    return row["id"]
