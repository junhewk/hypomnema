"""Health check endpoint."""

from fastapi import APIRouter, Request

from hypomnema.api.deps import DB

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request, db: DB) -> dict:
    cursor = await db.execute("SELECT value FROM settings WHERE key = 'setup_complete'")
    row = await cursor.fetchone()
    await cursor.close()
    settings = request.app.state.settings
    return {
        "status": "ok",
        "needs_setup": row is None,
        "mode": settings.mode,
    }
