"""Lint endpoints: list issues, resolve, tidy actions, trigger scan."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hypomnema.api.deps import DB
from hypomnema.db.transactions import immediate_transaction

router = APIRouter(prefix="/api/lint", tags=["lint"])


@router.get("/issues")
async def list_issues(
    db: DB,
    resolved: bool = False,
    issue_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    from hypomnema.ontology.lint import get_lint_issues

    return await get_lint_issues(db, resolved=resolved, issue_type=issue_type, limit=limit)


@router.get("/count")
async def issue_count(db: DB) -> dict[str, int]:
    from hypomnema.ontology.lint import get_unresolved_count

    return {"count": await get_unresolved_count(db)}


@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(issue_id: str, db: DB) -> dict[str, str]:
    from hypomnema.ontology.lint import resolve_lint_issue

    ok = await resolve_lint_issue(db, issue_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Issue not found or already resolved")
    return {"status": "resolved"}


@router.post("/run")
async def trigger_lint(db: DB) -> dict[str, Any]:
    from hypomnema.ontology.lint import run_lint

    issues = await run_lint(db)
    return {"new_issues": len(issues), "issues": [
        {"type": i.issue_type, "description": i.description, "severity": i.severity}
        for i in issues
    ]}


# --- Tidy actions ---


class CreateEdgeBody(BaseModel):
    predicate: str = "related_to"
    confidence: float = 0.8


class MergeBody(BaseModel):
    survivor_id: str | None = None


async def _get_issue(db: DB, issue_id: str) -> dict[str, Any]:
    """Fetch a lint issue by ID, raise 404 if not found or resolved."""
    cursor = await db.execute(
        "SELECT * FROM lint_issues WHERE id = ? AND resolved = 0", (issue_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Issue not found or already resolved")
    issue = dict(row)
    issue["engram_ids"] = json.loads(issue["engram_ids"])
    return issue


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(edge_id: str, db: DB) -> None:
    """Delete an edge (e.g., to resolve a contradiction)."""
    cursor = await db.execute("SELECT id FROM edges WHERE id = ?", (edge_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Edge not found")

    async with immediate_transaction(db):
        await db.execute("DELETE FROM edges WHERE id = ?", (edge_id,))


@router.post("/issues/{issue_id}/create-edge")
async def create_edge_from_issue(
    issue_id: str, body: CreateEdgeBody, db: DB,
) -> dict[str, str]:
    """Create an edge between engrams in a missing_link lint issue."""
    from hypomnema.ontology.lint import resolve_lint_issue

    issue = await _get_issue(db, issue_id)
    if issue["issue_type"] != "missing_link":
        raise HTTPException(status_code=400, detail="Action only valid for missing_link issues")

    ids = issue["engram_ids"]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Issue must reference at least 2 engrams")

    async with immediate_transaction(db):
        await db.execute(
            "INSERT OR IGNORE INTO edges (id, source_engram_id, target_engram_id, predicate, confidence) "
            "VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?)",
            (ids[0], ids[1], body.predicate, body.confidence),
        )

    await resolve_lint_issue(db, issue_id)
    return {"status": "edge_created"}


@router.post("/issues/{issue_id}/merge")
async def merge_engrams_from_issue(
    issue_id: str, body: MergeBody, db: DB,
) -> dict[str, Any]:
    """Merge duplicate engrams referenced in a lint issue."""
    from hypomnema.ontology.lint import resolve_lint_issue

    issue = await _get_issue(db, issue_id)
    if issue["issue_type"] != "duplicate_candidate":
        raise HTTPException(status_code=400, detail="Action only valid for duplicate_candidate issues")

    ids = issue["engram_ids"]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Issue must reference at least 2 engrams")

    # Determine survivor
    survivor_id = body.survivor_id or ids[0]
    if survivor_id not in ids:
        raise HTTPException(status_code=400, detail="survivor_id must be one of the issue engrams")
    merged_ids = [eid for eid in ids if eid != survivor_id]

    async with immediate_transaction(db):
        for mid in merged_ids:
            # Re-assign document links
            await db.execute(
                "UPDATE OR IGNORE document_engrams SET engram_id = ? WHERE engram_id = ?",
                (survivor_id, mid),
            )
            await db.execute("DELETE FROM document_engrams WHERE engram_id = ?", (mid,))

            # Re-wire edges
            await db.execute(
                "UPDATE OR IGNORE edges SET source_engram_id = ? WHERE source_engram_id = ?",
                (survivor_id, mid),
            )
            await db.execute(
                "UPDATE OR IGNORE edges SET target_engram_id = ? WHERE target_engram_id = ?",
                (survivor_id, mid),
            )
            # Delete self-loops and leftover edges referencing merged ID
            await db.execute(
                "DELETE FROM edges WHERE source_engram_id = target_engram_id",
            )
            await db.execute(
                "DELETE FROM edges WHERE source_engram_id = ? OR target_engram_id = ?",
                (mid, mid),
            )

            # Transfer aliases
            await db.execute(
                "UPDATE OR IGNORE engram_aliases SET engram_id = ? WHERE engram_id = ?",
                (survivor_id, mid),
            )
            await db.execute("DELETE FROM engram_aliases WHERE engram_id = ?", (mid,))

            # Clean up merged engram
            for table in ("projections", "engram_embeddings"):
                await db.execute(f"DELETE FROM {table} WHERE engram_id = ?", (mid,))  # noqa: S608
            await db.execute("DELETE FROM engrams WHERE id = ?", (mid,))

        # Auto-resolve lint issues referencing merged IDs
        for mid in merged_ids:
            await db.execute(
                "UPDATE lint_issues SET resolved = 1 WHERE resolved = 0 AND engram_ids LIKE ?",
                (f"%{mid}%",),
            )

    await resolve_lint_issue(db, issue_id)
    return {"status": "merged", "survivor_id": survivor_id, "merged_count": len(merged_ids)}
