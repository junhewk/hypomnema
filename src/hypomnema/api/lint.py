"""Lint endpoints: list issues, resolve, trigger scan."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from hypomnema.api.deps import DB

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
