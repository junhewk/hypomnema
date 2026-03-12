"""Fixtures for ontology tests."""

import aiosqlite


async def insert_test_doc(
    db: aiosqlite.Connection, text: str, doc_id: str = "testdoc"
) -> str:
    """Insert a test document and return its id."""
    cursor = await db.execute(
        "INSERT INTO documents (id, source_type, text) "
        "VALUES (?, 'scribble', ?) RETURNING *",
        (doc_id, text),
    )
    row = await cursor.fetchone()
    assert row is not None
    await db.commit()
    return row["id"]
