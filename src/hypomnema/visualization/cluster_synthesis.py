"""Cluster overview synthesis — auto-generate labels and summaries for HDBSCAN clusters."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.llm.base import LLMClient

from hypomnema.db.transactions import immediate_transaction

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a knowledge clustering engine. Given a list of concepts in a thematic \
cluster, generate:
1. A concise label (2-4 words) for the cluster theme
2. A paragraph summary (50-150 words) describing the theme, key concepts, and \
how they relate

Respond in JSON: {"label": "...", "summary": "..."}"""


async def synthesize_cluster_overviews(
    db: aiosqlite.Connection,
    llm: LLMClient,
) -> int:
    """Generate labels and summaries for changed clusters. Returns count synthesized.

    Detects composition changes by comparing engram counts, cleans up stale
    overviews for cluster IDs that no longer exist, and only calls the LLM
    for clusters whose membership actually changed.
    """
    # Get current cluster IDs and their engram counts
    cursor = await db.execute(
        "SELECT cluster_id, COUNT(*) AS cnt FROM projections "
        "WHERE cluster_id IS NOT NULL GROUP BY cluster_id ORDER BY cluster_id"
    )
    current = {row["cluster_id"]: row["cnt"] for row in await cursor.fetchall()}
    await cursor.close()

    # Fetch existing overviews to diff
    cursor = await db.execute("SELECT cluster_id, engram_count FROM cluster_overviews")
    existing = {row["cluster_id"]: row["engram_count"] for row in await cursor.fetchall()}
    await cursor.close()

    # Remove stale overviews whose cluster IDs are gone
    stale_ids = set(existing) - set(current)
    if stale_ids:
        placeholders = ",".join("?" * len(stale_ids))
        async with immediate_transaction(db):
            await db.execute(
                f"DELETE FROM cluster_overviews WHERE cluster_id IN ({placeholders})",  # noqa: S608
                tuple(stale_ids),
            )

    if not current:
        return 0

    # Only re-synthesize clusters whose engram count changed (new/removed members)
    to_synthesize = [
        cid for cid, cnt in current.items()
        if existing.get(cid) != cnt
    ]

    if not to_synthesize:
        logger.info("All %d cluster overviews up-to-date", len(current))
        return 0

    count = 0
    for cid in to_synthesize:
        try:
            await _synthesize_one(db, llm, cid)
            count += 1
        except Exception:
            logger.exception("Failed to synthesize cluster %d", cid)

    logger.info(
        "Synthesized %d cluster overviews (%d unchanged, %d stale removed)",
        count, len(current) - len(to_synthesize), len(stale_ids),
    )
    return count


async def _synthesize_one(
    db: aiosqlite.Connection,
    llm: LLMClient,
    cluster_id: int,
) -> None:
    """Generate label and summary for a single cluster."""
    cursor = await db.execute(
        "SELECT e.canonical_name, e.description "
        "FROM engrams e JOIN projections p ON e.id = p.engram_id "
        "WHERE p.cluster_id = ? LIMIT 50",
        (cluster_id,),
    )
    rows = list(await cursor.fetchall())
    await cursor.close()

    if not rows:
        return

    concepts = []
    for row in rows:
        name = row["canonical_name"]
        desc = row["description"] or ""
        concepts.append(f"- {name}: {desc}" if desc else f"- {name}")

    prompt = f"Cluster of {len(rows)} concepts:\n" + "\n".join(concepts)

    response = await llm.complete_json(prompt, system=_SYSTEM_PROMPT)
    label = str(response.get("label", f"Cluster {cluster_id}"))
    summary = str(response.get("summary", ""))

    if not summary:
        return

    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    async with immediate_transaction(db):
        await db.execute(
            "INSERT OR REPLACE INTO cluster_overviews (cluster_id, label, summary, engram_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cluster_id, label, summary, len(rows), now),
        )


async def get_cluster_overviews(db: aiosqlite.Connection) -> list[dict[str, object]]:
    """Fetch all cluster overviews."""
    cursor = await db.execute(
        "SELECT cluster_id, label, summary, engram_count, updated_at "
        "FROM cluster_overviews ORDER BY cluster_id"
    )
    rows = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()
    return rows
