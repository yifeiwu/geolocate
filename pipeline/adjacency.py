"""Shared-boundary adjacency between localities.

Two localities are directly connected (distance 1) when their polygons share a
boundary of at least MIN_SHARED_BOUNDARY_M. Contact at a single point - four
suburbs meeting at one corner - does not count as connected.
"""
from __future__ import annotations

import logging

import numpy as np
import shapely
from shapely import STRtree

from . import config

log = logging.getLogger(__name__)

LINEAR_TYPES = ("LineString", "MultiLineString", "GeometryCollection")

# shapely geometry type ids: 1 = LineString, 5 = MultiLineString. These are the
# overwhelming majority of results and can be measured vectorised.
_LINEAR_TIDS = (1, 5)


def shared_boundary_length(geom) -> float:
    """Total linear contact between two intersecting polygons.

    A Point result (corner touch) and a Polygon result (true area overlap,
    which should not occur between distinct localities) contribute nothing.
    """
    if geom is None or geom.is_empty:
        return 0.0
    if geom.geom_type == "LineString":
        return float(geom.length)
    if geom.geom_type in LINEAR_TYPES:
        return float(sum(shared_boundary_length(part) for part in geom.geoms))
    return 0.0


def build_adjacency(gdf) -> tuple[dict[int, list[int]], dict[tuple[int, int], float]]:
    """Return (neighbour lists, shared boundary length per ordered pair)."""
    geoms = np.asarray(gdf.geometry.to_numpy(), dtype=object)
    ids = gdf["id"].to_numpy()
    n = len(geoms)

    tree = STRtree(geoms)
    pairs = tree.query(geoms, predicate="intersects")  # shape (2, m)

    left, right = pairs[0], pairs[1]
    # keep i < j so each unordered pair is evaluated once, drop self-pairs
    mask = left < right
    left, right = left[mask], right[mask]
    log.info("evaluating %d candidate pairs (from %d nodes)", len(left), n)

    if len(left) == 0:
        return {}, {}

    inter = shapely.intersection(geoms[left], geoms[right])

    # Vectorised length where possible; fall back to the per-geometry helper for
    # the rare Point / GeometryCollection / area-overlap cases.
    tids = shapely.get_type_id(inter)
    linear_mask = np.isin(tids, _LINEAR_TIDS)
    shared = np.zeros(len(inter), dtype=float)
    if linear_mask.any():
        shared[linear_mask] = shapely.length(inter[linear_mask])
    for i in np.nonzero(~linear_mask)[0]:
        shared[i] = shared_boundary_length(inter[i])

    neighbours: dict[int, list[int]] = {}
    lengths: dict[tuple[int, int], float] = {}

    keep = np.nonzero(shared >= config.MIN_SHARED_BOUNDARY_M)[0]
    a_ids = ids[left]
    b_ids = ids[right]
    for i in keep:
        a, b, length = int(a_ids[i]), int(b_ids[i]), float(shared[i])
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
        lengths[(a, b)] = length
        lengths[(b, a)] = length

    corner_only = int(np.count_nonzero((shared < config.MIN_SHARED_BOUNDARY_M) & (tids == 0)))

    for key in neighbours:
        neighbours[key] = sorted(set(neighbours[key]))

    edges = sum(len(v) for v in neighbours.values()) // 2
    log.info(
        "graph: %d nodes, %d edges (%.2f mean degree); %d corner-only contacts rejected",
        n, edges, 2 * edges / max(n, 1), corner_only,
    )
    return neighbours, lengths
