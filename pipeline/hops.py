"""Breadth-first hop expansion over the adjacency graph."""
from __future__ import annotations

import logging
from collections import deque

from . import config

log = logging.getLogger(__name__)


def expand(
    neighbours: dict[int, list[int]],
    max_hops: int | None = None,
    nodes=None,
) -> dict[int, dict[int, list[int]]]:
    """For every node, bucket reachable nodes by hop distance (1..max_hops).

    ``nodes`` must include every locality, not just those with neighbours, so
    isolated rural localities still get an (empty) entry in the output.

    Neighbour lists are truncated at MAX_ENTRIES_PER_HOP to keep the published
    payload bounded in very dense metropolitan areas.
    """
    max_hops = max_hops or config.MAX_HOPS
    all_nodes = list(nodes) if nodes is not None else list(neighbours.keys())
    out: dict[int, dict[int, list[int]]] = {}
    truncated_nodes = 0
    total_entries = 0

    for start in all_nodes:
        seen = {start}
        frontier = deque([(start, 0)])
        buckets: dict[int, list[int]] = {h: [] for h in range(1, max_hops + 1)}

        while frontier:
            node, depth = frontier.popleft()
            if depth >= max_hops:
                continue
            for nxt in neighbours.get(node, ()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                buckets[depth + 1].append(nxt)
                frontier.append((nxt, depth + 1))

        node_total = 0
        node_truncated = False
        for hop, ids in buckets.items():
            if len(ids) > config.MAX_ENTRIES_PER_HOP:
                ids = sorted(ids)[: config.MAX_ENTRIES_PER_HOP]
                node_truncated = True
            buckets[hop] = sorted(ids)
            node_total += len(ids)

        total_entries += node_total
        if node_truncated:
            truncated_nodes += 1
        out[start] = buckets

    log.info(
        "hops: expanded %d nodes (%d isolated) to depth %d -> %d entries (%.1f avg); %d nodes truncated",
        len(out), sum(1 for b in out.values() if not any(b.values())), max_hops,
        total_entries, total_entries / max(len(out), 1), truncated_nodes,
    )
    return out
