"""Document heat scoring — graph-derived actionability signal.

Computes a heat_score (0–1) per document from temporal recency, concept
co-activity, revision count, and graph centrality.  Maps to a heat_tier:
active / reference / dormant.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

HeatTier = Literal["active", "reference", "dormant"]
ALL_HEAT_TIERS: tuple[HeatTier, ...] = ("active", "reference", "dormant")

# Scoring weights (sum to 1.0)
_W_RECENCY = 0.40
_W_ACTIVITY = 0.35
_W_REVISION = 0.10
_W_CENTRALITY = 0.15

# Temporal decay: lambda such that half-life ≈ 23 days
_DECAY_LAMBDA = 0.03

# Co-activity window in days
_ACTIVITY_WINDOW_DAYS = 30

# Normalization caps
_ACTIVITY_CAP = 5  # 5+ co-active docs → max signal
_REVISION_CAP = 3  # 3+ revisions → max signal
_CENTRALITY_CAP = 10  # 10+ edges → max signal

# Tier thresholds
_TIER_ACTIVE = 0.35
_TIER_REFERENCE = 0.12


def classify_tier(score: float) -> HeatTier:
    if score >= _TIER_ACTIVE:
        return "active"
    if score >= _TIER_REFERENCE:
        return "reference"
    return "dormant"


async def compute_all_heat(db: aiosqlite.Connection) -> int:
    """Recompute heat_score and heat_tier for all non-draft documents.

    Returns the number of documents updated.
    """
    # CTE-based query: compute co-activity and edge counts in bulk,
    # then join back to documents. Avoids per-document correlated subqueries.
    cursor = await db.execute(
        """
        WITH co_activity AS (
            SELECT de1.document_id, COUNT(DISTINCT d2.id) AS cnt
            FROM document_engrams de1
            JOIN document_engrams de2 ON de1.engram_id = de2.engram_id
            JOIN documents d2 ON de2.document_id = d2.id
            WHERE d2.id != de1.document_id
              AND d2.created_at >= datetime('now', ? || ' days')
            GROUP BY de1.document_id
        ),
        edge_counts AS (
            SELECT de.document_id, COUNT(DISTINCT e.id) AS cnt
            FROM document_engrams de
            JOIN edges e ON de.engram_id IN (e.source_engram_id, e.target_engram_id)
            GROUP BY de.document_id
        )
        SELECT
            d.id,
            julianday('now') - julianday(d.updated_at) AS days_since_update,
            d.revision,
            COALESCE(ca.cnt, 0) AS coactive_docs,
            COALESCE(ec.cnt, 0) AS edge_count
        FROM documents d
        LEFT JOIN co_activity ca ON d.id = ca.document_id
        LEFT JOIN edge_counts ec ON d.id = ec.document_id
        WHERE NOT (d.source_type = 'scribble' AND d.processed = 0 AND d.tidy_text IS NULL)
    """,
        (str(-_ACTIVITY_WINDOW_DAYS),),
    )

    rows = await cursor.fetchall()
    await cursor.close()

    if not rows:
        return 0

    updates: list[tuple[float, str, str]] = []
    for row in rows:
        doc_id = row[0]
        days_since = max(float(row[1] or 0), 0.0)
        revision = int(row[2] or 1)
        coactive = int(row[3] or 0)
        edges = int(row[4] or 0)

        recency = math.exp(-_DECAY_LAMBDA * days_since)
        activity = min(coactive / _ACTIVITY_CAP, 1.0)
        revision_boost = min((revision - 1) / _REVISION_CAP, 1.0)
        centrality = min(edges / _CENTRALITY_CAP, 1.0)

        score = (
            _W_RECENCY * recency + _W_ACTIVITY * activity + _W_REVISION * revision_boost + _W_CENTRALITY * centrality
        )
        score = min(score, 1.0)
        tier = classify_tier(score)
        updates.append((score, tier, doc_id))

    await db.executemany(
        "UPDATE documents SET heat_score = ?, heat_tier = ? WHERE id = ?",
        updates,
    )
    await db.commit()

    logger.info("Heat scores updated for %d documents", len(updates))
    return len(updates)
