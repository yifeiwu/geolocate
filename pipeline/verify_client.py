"""Parity check: the client-side bfs() must reproduce the precomputed API files.

neighbours.js cannot run under Python, so this re-implements its algorithm
line-for-line (including the half-up rounding and the
sqrt(dx*dx + dy*dy) distance) and asserts it yields byte-identical results to
the emitted api/n/*.json files. If this drifts, the documented client contract
in the README is wrong.

    python -m pipeline.verify_client --site site
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _load(site: Path):
    adj = json.loads((site / "data" / "graph.json").read_text(encoding="utf-8"))["adjacency"]
    subs = json.loads((site / "data" / "suburbs.json").read_text(encoding="utf-8"))
    return adj, subs


def bfs(adj: dict, subs: dict, start_id, distance: int):
    """Mirror of bfs() in site/assets/neighbours.js."""
    start = str(start_id)
    seen = {start}
    frontier = [start]
    result = []
    for d in range(1, distance + 1):
        nxt = []
        for node in frontier:
            for row in adj.get(node, []):
                nid = str(row[0])
                if nid in seen:
                    continue
                seen.add(nid)
                nxt.append(nid)
                m = subs[nid]
                dx = subs[start]["cx"] - m["cx"]
                dy = subs[start]["cy"] - m["cy"]
                km = math.floor(math.sqrt(dx * dx + dy * dy) / 1000.0 * 10 + 0.5) / 10
                result.append((d, km, m["name"], m["postcode"], m["state"]))
        frontier = nxt
        if not nxt:
            break
    result.sort(key=lambda r: (r[0], r[1], r[2]))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="site")
    args = ap.parse_args(argv)

    site = Path(args.site)
    adj, subs = _load(site)
    api = site / "api" / "n"

    mismatches = []
    for key, meta in subs.items():
        doc = json.loads((api / f"{meta['slug']}.json").read_text(encoding="utf-8"))
        precomputed = [
            (n["hops"], n["km"], n["suburb"], n["postcode"], n["state"])
            for n in doc["neighbours"]
        ]
        if precomputed != bfs(adj, subs, key, doc["max_distance"]):
            mismatches.append(meta["slug"])

    print(f"checked {len(subs)} localities; mismatches: {len(mismatches)}")
    for slug in mismatches[:10]:
        print(f"  MISMATCH {slug}")
    if mismatches:
        print("FAIL: client bfs() disagrees with the precomputed API files")
        return 1
    print("PASS: client bfs() matches the precomputed API files exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
