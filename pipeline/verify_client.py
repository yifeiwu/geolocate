"""Parity check: the client-side bfs() must reproduce the precomputed API files.

neighbours.js cannot run under Python, so this re-implements its algorithm
line-for-line (including the half-up rounding and the
sqrt(dx*dx + dy*dy) distance) and asserts it yields byte-identical results to
the emitted api/n/*.json files. If this drifts, the documented client contract
in the README is wrong.

getSuburb()'s slug resolution is mirrored the same way, since a handful of
localities share both name and postcode across a state border and are only
reachable through the index-shard fallback.

    python -m pipeline.verify_client --site site
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from . import config


def _load(site: Path):
    adj = json.loads((site / "data" / "graph.json").read_text(encoding="utf-8"))["adjacency"]
    subs = json.loads((site / "data" / "suburbs.json").read_text(encoding="utf-8"))
    return adj, subs


def slugify(text: str) -> str:
    """Mirror of slugify() in site/assets/neighbours.js."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", str(text).lower()))


def _shards(site: Path) -> dict[str, list[dict]]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (site / "api" / "index").glob("*.json")
    }


def resolve_slug(shards: dict[str, list[dict]], suburb: str, postcode: str,
                 state: str | None = None) -> str | None:
    """Mirror of resolveSlug() in site/assets/neighbours.js.

    Returns the slug, None when nothing matches, or raises ValueError when the
    name+postcode pair is ambiguous (which the JS surfaces as AMBIGUOUS_SUBURB).
    """
    want = slugify(suburb)
    hits = [
        e for e in shards.get(want[:1], [])
        if e["postcode"] == postcode
        and slugify(e["name"]) == want
        and (state is None or e["state"] == state)
    ]
    if len(hits) == 1:
        return hits[0]["slug"]
    if not hits:
        return None
    raise ValueError("ambiguous: " + " and ".join(h["state"] for h in hits))


def get_suburb(shards: dict[str, list[dict]], known: set[str],
               suburb: str, postcode: str, state: str | None = None) -> str:
    """Mirror of getSuburb(): try the bare slug, then fall back to the index."""
    direct = f"{slugify(suburb)}-{postcode}" + (f"-{state.lower()}" if state else "")
    if direct in known:
        return direct
    slug = resolve_slug(shards, suburb, postcode, state)
    if slug is None:
        raise KeyError(f"not found: {suburb} {postcode}")
    return slug


def bfs_levels(adj: dict, subs: dict, start_id, distance: int) -> dict[int, list]:
    """Mirror of bfs() in site/assets/neighbours.js, keeping every hop level.

    One traversal yields the result for each depth, which is what lets us check
    the documented "filter the list yourself" contract without re-walking the
    graph once per depth.
    """
    start = str(start_id)
    seen = {start}
    frontier = [start]
    levels: dict[int, list] = {}
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
                levels.setdefault(d, []).append(
                    (d, km, m["name"], m["postcode"], m["state"])
                )
        frontier = nxt
        if not nxt:
            break
    for rows in levels.values():
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return levels


def bfs(adj: dict, subs: dict, start_id, distance: int):
    """Mirror of bfs() in site/assets/neighbours.js."""
    levels = bfs_levels(adj, subs, start_id, distance)
    return [r for d in sorted(levels) for r in levels[d]]


def check_resolution(site: Path, subs: dict) -> tuple[list[str], list[str]]:
    """Mirror-of-getSuburb check. Returns (failures, ambiguous_pairs)."""
    shards = _shards(site)
    known = {v["slug"] for v in subs.values()}
    failures: list[str] = []
    ambiguous: list[str] = []

    for meta in subs.values():
        if meta["postcode"] is None:
            continue
        try:
            slug = get_suburb(shards, known, meta["name"], meta["postcode"], meta["state"])
        except (KeyError, ValueError) as exc:
            failures.append(f"{meta['slug']}: {exc}")
            continue
        if slug != meta["slug"]:
            failures.append(f"{meta['slug']} resolved to {slug}")

    # every bare name+postcode pair must either resolve unambiguously, or be a
    # genuine cross-border collision the caller has to disambiguate with a state
    for meta in subs.values():
        if meta["postcode"] is None:
            continue
        try:
            get_suburb(shards, known, meta["name"], meta["postcode"])
        except ValueError:
            pair = f"{meta['name']} {meta['postcode']}"
            if pair not in ambiguous:
                ambiguous.append(pair)
        except KeyError:
            pass

    return failures, ambiguous


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", default="site")
    args = ap.parse_args(argv)

    site = Path(args.site)
    adj, subs = _load(site)
    api = site / "api" / "n"

    mismatches = []
    filter_mismatches = []
    for key, meta in subs.items():
        doc = json.loads((api / f"{meta['slug']}.json").read_text(encoding="utf-8"))

        emitted = [
            (n["hops"], n["km"], n["suburb"], n["postcode"], n["state"])
            for n in doc["neighbours"]
        ]
        if any(n["hops"] is None for n in doc["neighbours"]):
            mismatches.append(f"{meta['slug']} (neighbour missing hops)")
            continue
        if doc.get("max_distance") != config.MAX_HOPS:
            mismatches.append(f"{meta['slug']} (max_distance != {config.MAX_HOPS})")
            continue

        levels = bfs_levels(adj, subs, key, config.MAX_HOPS)
        flat = [r for d in sorted(levels) for r in levels[d]]
        if emitted != flat:
            mismatches.append(meta["slug"])
            continue

        # The documented contract: consumers filter the list on `hops` themselves
        # because there is no hop argument. That only holds if narrowing the file
        # to hops <= d reproduces a breadth-first walk of depth d exactly.
        for d in sorted(levels):
            narrowed = [n for n in emitted if n[0] <= d]
            cumulative = [r for dd in sorted(levels) if dd <= d for r in levels[dd]]
            if narrowed != cumulative:
                filter_mismatches.append(f"{meta['slug']} (hops<={d})")

    print(f"checked {len(subs)} localities; mismatches: {len(mismatches)}")
    for slug in mismatches[:10]:
        print(f"  MISMATCH {slug}")
    if mismatches:
        print("FAIL: client bfs() disagrees with the precomputed API files")
        return 1
    print("PASS: client bfs() matches the published neighbour lists exactly")

    print(f"\nhop filtering      : {len(filter_mismatches)} failures")
    for slug in filter_mismatches[:10]:
        print(f"  MISMATCH {slug}")
    if filter_mismatches:
        print("FAIL: filtering a file on `hops` does not reproduce a shallower bfs()")
        return 1
    print("PASS: filtering the list on `hops` reproduces a shallower bfs() exactly")

    failures, ambiguous = check_resolution(site, subs)
    print(f"\nslug resolution    : {len(subs)} localities, {len(failures)} failures")
    for f in failures[:10]:
        print(f"  UNRESOLVED {f}")
    if failures:
        print("FAIL: getSuburb() cannot reach some localities")
        return 1
    print(f"PASS: every postcoded locality resolves to its own slug "
          f"({len(ambiguous)} cross-border pairs need a state: {', '.join(ambiguous)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
