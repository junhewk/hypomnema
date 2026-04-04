"""Knowledge graph linter — automated quality checks.

Detects orphan engrams, contradictory edges, missing links, and
duplicate candidates. All checks are pure SQL except missing_link
which uses sqlite-vec KNN.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

from hypomnema.db.transactions import immediate_transaction

logger = logging.getLogger(__name__)

# Issue type constants
ORPHAN = "orphan"
CONTRADICTION = "contradiction"
MISSING_LINK = "missing_link"
DUPLICATE_CANDIDATE = "duplicate_candidate"


@dataclass(frozen=True)
class LintIssue:
    issue_type: str  # orphan, contradiction, missing_link, duplicate_candidate
    engram_ids: list[str]
    description: str
    severity: str = "warning"  # warning, error, info


async def run_lint(db: aiosqlite.Connection) -> list[LintIssue]:
    """Run all SQL-based lint checks and persist new issues. Returns new issues found."""
    issues: list[LintIssue] = []
    issues.extend(await _check_orphans(db))
    issues.extend(await _check_contradictions(db))
    issues.extend(await _check_missing_links(db))

    if not issues:
        return []

    # Persist new issues (skip duplicates by checking existing unresolved)
    cursor = await db.execute(
        "SELECT engram_ids, issue_type FROM lint_issues WHERE resolved = 0"
    )
    existing = {(row["engram_ids"], row["issue_type"]) for row in await cursor.fetchall()}
    await cursor.close()

    new_issues = []
    async with immediate_transaction(db):
        for issue in issues:
            key = (json.dumps(sorted(issue.engram_ids)), issue.issue_type)
            if key in existing:
                continue
            await db.execute(
                "INSERT INTO lint_issues (id, issue_type, engram_ids, description, severity) "
                "VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?)",
                (issue.issue_type, json.dumps(sorted(issue.engram_ids)),
                 issue.description, issue.severity),
            )
            new_issues.append(issue)

    if new_issues:
        logger.info("Lint: found %d new issues", len(new_issues))
    return new_issues


async def _check_orphans(db: aiosqlite.Connection) -> list[LintIssue]:
    """Find engrams with no edges at all."""
    cursor = await db.execute("""
        SELECT e.id, e.canonical_name
        FROM engrams e
        LEFT JOIN edges ed_s ON ed_s.source_engram_id = e.id
        LEFT JOIN edges ed_t ON ed_t.target_engram_id = e.id
        WHERE ed_s.id IS NULL AND ed_t.id IS NULL
        LIMIT 50
    """)
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        LintIssue(
            issue_type=ORPHAN,
            engram_ids=[row["id"]],
            description=f"Engram '{row['canonical_name']}' has no edges",
            severity="info",
        )
        for row in rows
    ]


async def _check_contradictions(db: aiosqlite.Connection) -> list[LintIssue]:
    """Find engram pairs connected by both 'supports' and 'contradicts'."""
    cursor = await db.execute("""
        SELECT e1.source_engram_id, e1.target_engram_id,
               s.canonical_name AS source_name, t.canonical_name AS target_name
        FROM edges e1
        JOIN edges e2 ON e1.source_engram_id = e2.source_engram_id
                     AND e1.target_engram_id = e2.target_engram_id
        JOIN engrams s ON s.id = e1.source_engram_id
        JOIN engrams t ON t.id = e1.target_engram_id
        WHERE e1.predicate = 'supports' AND e2.predicate = 'contradicts'
        LIMIT 20
    """)
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        LintIssue(
            issue_type=CONTRADICTION,
            engram_ids=[row["source_engram_id"], row["target_engram_id"]],
            description=f"'{row['source_name']}' both supports and contradicts '{row['target_name']}'",
            severity="error",
        )
        for row in rows
    ]


async def _check_missing_links(db: aiosqlite.Connection) -> list[LintIssue]:
    """Find engram pairs with high embedding similarity but no edge.

    Uses sqlite-vec KNN. Silently returns empty if vec tables don't exist.
    """
    issues: list[LintIssue] = []
    try:
        # Get engrams that have embeddings
        cursor = await db.execute("""
            SELECT e.id, e.canonical_name, ee.embedding
            FROM engrams e
            JOIN engram_embeddings ee ON ee.engram_id = e.id
            LIMIT 200
        """)
        rows = list(await cursor.fetchall())
        await cursor.close()
    except Exception:
        return []  # vec tables may not exist

    if len(rows) < 2:
        return []

    # For each engram, check if its nearest neighbor has an edge
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows[:50]:
        engram_id = row["id"]
        try:
            cursor = await db.execute("""
                SELECT engram_id, distance
                FROM engram_embeddings
                WHERE embedding MATCH ? AND k = 3 AND engram_id != ?
            """, (row["embedding"], engram_id))
            neighbors = await cursor.fetchall()
            await cursor.close()
        except Exception:
            continue

        for neighbor in neighbors:
            nid = neighbor["engram_id"]
            dist = neighbor["distance"]
            # L2 distance < 0.3 ≈ cosine similarity > 0.95
            if dist > 0.3:
                continue

            pair = tuple(sorted([engram_id, nid]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Check if edge exists
            cursor = await db.execute("""
                SELECT 1 FROM edges
                WHERE (source_engram_id = ? AND target_engram_id = ?)
                   OR (source_engram_id = ? AND target_engram_id = ?)
                LIMIT 1
            """, (engram_id, nid, nid, engram_id))
            has_edge = await cursor.fetchone()
            await cursor.close()

            if not has_edge:
                # Fetch names
                cursor = await db.execute(
                    "SELECT canonical_name FROM engrams WHERE id IN (?, ?)",
                    (engram_id, nid),
                )
                names = [r["canonical_name"] for r in await cursor.fetchall()]
                await cursor.close()
                issues.append(LintIssue(
                    issue_type=MISSING_LINK,
                    engram_ids=list(pair),
                    description=f"High similarity but no edge: '{names[0]}' ↔ '{names[1] if len(names) > 1 else nid}'",
                    severity="warning",
                ))

    return issues[:20]  # cap results


async def get_lint_issues(
    db: aiosqlite.Connection,
    *,
    resolved: bool = False,
    issue_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Fetch lint issues from the database."""
    where = ["resolved = ?"]
    params: list[object] = [1 if resolved else 0]
    if issue_type:
        where.append("issue_type = ?")
        params.append(issue_type)

    cursor = await db.execute(
        f"SELECT * FROM lint_issues WHERE {' AND '.join(where)} "  # noqa: S608
        "ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    )
    rows = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()

    # Parse engram_ids JSON
    for row in rows:
        if isinstance(row.get("engram_ids"), str):
            row["engram_ids"] = json.loads(row["engram_ids"])
    return rows


async def resolve_lint_issue(db: aiosqlite.Connection, issue_id: str) -> bool:
    """Mark a lint issue as resolved."""
    async with immediate_transaction(db):
        cursor = await db.execute(
            "UPDATE lint_issues SET resolved = 1 WHERE id = ? AND resolved = 0",
            (issue_id,),
        )
    return cursor.rowcount > 0


async def get_unresolved_count(db: aiosqlite.Connection) -> int:
    """Return count of unresolved lint issues."""
    cursor = await db.execute("SELECT COUNT(*) FROM lint_issues WHERE resolved = 0")
    row = await cursor.fetchone()
    await cursor.close()
    return row[0] if row else 0
