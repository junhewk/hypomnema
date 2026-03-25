"""Visualization transform utilities — cluster colors, PageRank, data bounds.

Ported from the original TypeScript vizTransforms.ts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[float, float, float]:
    """Convert HSL to RGB (0-1 range).

    :param h: hue in degrees (0-360)
    :param s: saturation (0-1)
    :param lightness: lightness (0-1)
    :returns: (r, g, b) tuple with values in 0-1 range
    """
    c = (1 - abs(2 * lightness - 1)) * s
    x = c * (1 - abs(((h / 60) % 2) - 1))
    m = lightness - c / 2

    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x

    return (r + m, g + m, b + m)


def cluster_color(cluster_id: int | None) -> str:
    """Golden-angle HSL hue generation for deterministic cluster colors.

    Returns hex color string like '#ff9900'.
    cluster_id None or -1 (noise) returns neutral gray.
    """
    if not isinstance(cluster_id, int) or cluster_id < 0:
        return "#787068"  # warm neutral gray matching TS [0.47, 0.44, 0.42]

    hue = (cluster_id * 137.508) % 360
    r, g, b = hsl_to_rgb(hue, 0.7, 0.6)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def cluster_color_rgb(cluster_id: int | None) -> tuple[float, float, float]:
    """Golden-angle HSL hue generation returning (r, g, b) floats in 0-1 range.

    cluster_id None or -1 (noise) returns warm neutral gray.
    """
    if not isinstance(cluster_id, int) or cluster_id < 0:
        return (0.47, 0.44, 0.42)

    hue = (cluster_id * 137.508) % 360
    return hsl_to_rgb(hue, 0.7, 0.6)


def compute_page_rank(
    edges: list[dict[str, Any]],
    damping: float = 0.85,
    iterations: int = 20,
) -> dict[str, float]:
    """Power iteration PageRank using edge confidence as weights.

    :param edges: list of dicts with source_engram_id, target_engram_id, confidence
    :param damping: damping factor (default 0.85)
    :param iterations: number of power iterations (default 20)
    :returns: {engram_id: rank} normalized so max=1.0
    """
    # Collect all node IDs
    nodes: set[str] = set()
    for e in edges:
        nodes.add(e["source_engram_id"])
        nodes.add(e["target_engram_id"])

    if not nodes:
        return {}

    n = len(nodes)
    node_list = sorted(nodes)
    node_idx = {nid: i for i, nid in enumerate(node_list)}

    # Build weighted out-adjacency: source -> [(target_idx, weight)]
    out_edges: dict[int, list[tuple[int, float]]] = defaultdict(list)
    out_weight: dict[int, float] = defaultdict(float)

    for e in edges:
        si = node_idx[e["source_engram_id"]]
        ti = node_idx[e["target_engram_id"]]
        w = float(e.get("confidence", 1.0))
        out_edges[si].append((ti, w))
        out_weight[si] += w
        # Treat as undirected for PageRank
        out_edges[ti].append((si, w))
        out_weight[ti] += w

    # Initialize ranks uniformly
    rank = [1.0 / n] * n

    for _ in range(iterations):
        new_rank = [(1.0 - damping) / n] * n
        for src in range(n):
            if out_weight[src] == 0:
                # Dangling node: distribute evenly
                share = damping * rank[src] / n
                for j in range(n):
                    new_rank[j] += share
            else:
                for tgt, w in out_edges[src]:
                    new_rank[tgt] += damping * rank[src] * w / out_weight[src]
        rank = new_rank

    # Normalize so max = 1.0
    max_rank = max(rank) if rank else 1.0
    if max_rank > 0:
        rank = [r / max_rank for r in rank]

    return {node_list[i]: rank[i] for i in range(n)}


def compute_data_bounds(
    positions: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], float]:
    """Compute centroid and bounding radius of 3D positions.

    :returns: (centroid, radius) where centroid is (cx, cy, cz)
    """
    if not positions:
        return (0.0, 0.0, 0.0), 15.0

    n = len(positions)
    cx = sum(p[0] for p in positions) / n
    cy = sum(p[1] for p in positions) / n
    cz = sum(p[2] for p in positions) / n

    max_dist_sq = 0.0
    for p in positions:
        dx, dy, dz = p[0] - cx, p[1] - cy, p[2] - cz
        max_dist_sq = max(max_dist_sq, dx * dx + dy * dy + dz * dz)

    radius = max_dist_sq**0.5 if max_dist_sq > 0 else 15.0
    return (cx, cy, cz), radius
