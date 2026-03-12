"""Knowledge graph search: edge queries and BFS neighborhood traversal."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

from hypomnema.db.models import Edge, Engram


@dataclasses.dataclass(frozen=True)
class Neighborhood:
    """BFS neighborhood around a center engram."""

    center: Engram
    edges: list[Edge]
    engrams: dict[str, Engram]  # id → Engram for all nodes in neighborhood


async def get_edges_for_engram(
    db: aiosqlite.Connection,
    engram_id: str,
    *,
    predicate: str | None = None,
    limit: int = 100,
) -> list[Edge]:
    """Get all edges involving an engram (as source or target).

    Optionally filter by predicate.
    """
    query = (
        "SELECT * FROM edges "
        "WHERE (source_engram_id = ? OR target_engram_id = ?)"
    )
    params: list[str | int] = [engram_id, engram_id]
    if predicate is not None:
        query += " AND predicate = ?"
        params.append(predicate)
    query += " ORDER BY confidence DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    await cursor.close()
    return [Edge.from_row(r) for r in rows]


async def get_edges_between(
    db: aiosqlite.Connection,
    engram_id_a: str,
    engram_id_b: str,
) -> list[Edge]:
    """Get all edges directly connecting two engrams (either direction)."""
    cursor = await db.execute(
        "SELECT * FROM edges WHERE "
        "(source_engram_id = ? AND target_engram_id = ?) OR "
        "(source_engram_id = ? AND target_engram_id = ?) "
        "ORDER BY confidence DESC",
        (engram_id_a, engram_id_b, engram_id_b, engram_id_a),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [Edge.from_row(r) for r in rows]


async def get_edges_by_predicate(
    db: aiosqlite.Connection,
    predicate: str,
    *,
    limit: int = 100,
) -> list[Edge]:
    """Get all edges with a given predicate type."""
    cursor = await db.execute(
        "SELECT * FROM edges WHERE predicate = ? ORDER BY confidence DESC LIMIT ?",
        (predicate, limit),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [Edge.from_row(r) for r in rows]


async def get_neighborhood(
    db: aiosqlite.Connection,
    engram_id: str,
    *,
    max_hops: int = 2,
    predicate: str | None = None,
) -> Neighborhood | None:
    """BFS traversal of the engram graph, returning edges and engrams within n hops.

    Returns None if the center engram does not exist.
    """
    # Fetch center engram
    cursor = await db.execute(
        "SELECT * FROM engrams WHERE id = ?", (engram_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None

    center = Engram.from_row(row)

    edge_map: dict[str, Edge] = {}  # id → Edge, deduplicates during accumulation
    visited: set[str] = {engram_id}
    frontier: set[str] = {engram_id}

    for _hop in range(max_hops):
        if not frontier:
            break

        # Batch query edges for all frontier nodes
        placeholders = ",".join("?" for _ in frontier)
        frontier_list = list(frontier)

        query = (
            f"SELECT * FROM edges WHERE "
            f"(source_engram_id IN ({placeholders}) OR "
            f"target_engram_id IN ({placeholders}))"
        )
        params: list[str] = frontier_list + frontier_list
        if predicate is not None:
            query += " AND predicate = ?"
            params.append(predicate)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()

        next_frontier: set[str] = set()
        for r in rows:
            edge = Edge.from_row(r)
            edge_map[edge.id] = edge
            for eid in (edge.source_engram_id, edge.target_engram_id):
                if eid not in visited:
                    visited.add(eid)
                    next_frontier.add(eid)

        frontier = next_frontier

    # Batch fetch all engrams in neighborhood (excluding center, already have it)
    other_ids = visited - {engram_id}
    engram_map: dict[str, Engram] = {center.id: center}
    if other_ids:
        placeholders = ",".join("?" for _ in other_ids)
        cursor = await db.execute(
            f"SELECT * FROM engrams WHERE id IN ({placeholders})",  # noqa: S608
            list(other_ids),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            e = Engram.from_row(r)
            engram_map[e.id] = e

    return Neighborhood(center=center, edges=list(edge_map.values()), engrams=engram_map)
