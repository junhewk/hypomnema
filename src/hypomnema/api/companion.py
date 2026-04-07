"""Companion state endpoint: graph stats, mood, growth stage, milestones."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hypomnema.api.deps import DB
from hypomnema.db.transactions import immediate_transaction

router = APIRouter(prefix="/api/companion", tags=["companion"])

_MILESTONES = [
    ("first_engram", "engram", 1, "First engram — your knowledge graph has awakened."),
    ("first_10_engrams", "engram", 10, "10 engrams — the graph is taking shape."),
    ("first_50_engrams", "engram", 50, "50 engrams — a growing knowledge network."),
    ("first_100_engrams", "engram", 100, "100 engrams — substantial knowledge base."),
    ("first_200_engrams", "engram", 200, "200 engrams — flourishing knowledge ecosystem."),
    ("first_100_edges", "edge", 100, "100 connections — ideas are linking up."),
    ("clean_graph", "lint", 0, "Clean graph — no unresolved issues."),
]


def _compute_mood(engram_count: int, lint_errors: int, lint_warnings: int) -> str:
    if engram_count == 0:
        return "sleeping"
    if lint_errors > 0:
        return "distressed"
    if lint_warnings > 0:
        return "concerned"
    return "happy"


def _compute_growth_stage(engram_count: int) -> int:
    if engram_count == 0:
        return 0
    if engram_count <= 10:
        return 1
    if engram_count <= 50:
        return 2
    if engram_count <= 200:
        return 3
    return 4


@router.get("/state")
async def companion_state(db: DB) -> dict[str, Any]:
    # Counts
    async def _count(sql: str) -> int:
        cursor = await db.execute(sql)
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else 0

    engram_count = await _count("SELECT COUNT(*) FROM engrams")
    edge_count = await _count("SELECT COUNT(*) FROM edges")
    document_count = await _count("SELECT COUNT(*) FROM documents")

    # Lint counts by severity
    cursor = await db.execute(
        "SELECT severity, COUNT(*) FROM lint_issues WHERE resolved = 0 GROUP BY severity"
    )
    severity_counts = {row[0]: row[1] for row in await cursor.fetchall()}
    await cursor.close()
    lint_errors = severity_counts.get("error", 0)
    lint_warnings = severity_counts.get("warning", 0)
    lint_info = severity_counts.get("info", 0)

    mood = _compute_mood(engram_count, lint_errors, lint_warnings)
    growth_stage = _compute_growth_stage(engram_count)

    # Milestone check
    new_milestone = None
    for key, kind, threshold, message in _MILESTONES:
        setting_key = f"milestone_{key}"
        cursor = await db.execute(
            "SELECT value FROM settings WHERE key = ?", (setting_key,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            continue  # Already achieved

        achieved = False
        if kind == "engram":
            achieved = engram_count >= threshold
        elif kind == "edge":
            achieved = edge_count >= threshold
        elif kind == "lint" and threshold == 0:
            # Clean graph: only if previously had issues
            cursor2 = await db.execute(
                "SELECT value FROM settings WHERE key = 'milestone_had_lint_issues'"
            )
            had_issues = await cursor2.fetchone()
            await cursor2.close()
            total_lint = lint_errors + lint_warnings + lint_info
            if total_lint > 0:
                async with immediate_transaction(db):
                    await db.execute(
                        "INSERT OR REPLACE INTO settings (key, value) "
                        "VALUES ('milestone_had_lint_issues', '1')"
                    )
            elif had_issues is not None:
                achieved = True

        if achieved:
            from datetime import UTC, datetime

            now = datetime.now(UTC).replace(microsecond=0).isoformat()
            async with immediate_transaction(db):
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (setting_key, now),
                )
            new_milestone = {"key": key, "message": message}
            break  # Only one milestone per request

    return {
        "engram_count": engram_count,
        "edge_count": edge_count,
        "document_count": document_count,
        "lint_errors": lint_errors,
        "lint_warnings": lint_warnings,
        "lint_info": lint_info,
        "growth_stage": growth_stage,
        "mood": mood,
        "new_milestone": new_milestone,
    }
