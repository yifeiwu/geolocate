"""Write the published API artefacts."""
from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", str(text).lower()).strip("-")


def build_slugs(meta: pd.DataFrame) -> pd.DataFrame:
    """URL-safe unique key per locality: <name>-<postcode>.

    Collisions are expected and mostly legitimate: several ABS postcodes straddle
    a state border (2406 NSW/QLD, 4375, 4380, 4385, 2540 NSW/OT), so the same
    locality name and postcode legitimately exist on both sides. Those are
    disambiguated with a state suffix. A final loc_pid-derived suffix is a
    safety net so an unexpected duplicate can never break the build.
    """
    meta = meta.copy()
    # Merges can turn a missing postcode back into NaN, and pandas' inferred
    # `str` dtype converts None to NaN on assignment. json.dumps would then emit
    # a bare `NaN` token, which is invalid JSON. Force object dtype so a missing
    # postcode stays a real None all the way to the payload.
    meta["primary_postcode"] = pd.Series(
        [None if pd.isna(v) else str(v) for v in meta["primary_postcode"]],
        index=meta.index, dtype=object,
    )
    meta["postcodes"] = pd.Series(
        [None if v is None or (isinstance(v, float) and pd.isna(v)) else list(v)
         for v in meta["postcodes"]],
        index=meta.index, dtype=object,
    )
    meta["slug_base"] = [
        f"{slugify(n)}-{p}" if p else slugify(n)
        for n, p in zip(meta["name"], meta["primary_postcode"].fillna(""))
    ]

    # Pass 1: a state suffix resolves name+postcode collisions, which are mostly
    # legitimate border postcodes (2406 NSW/QLD, 4375, 4380, 4385, 2540 NSW/OT).
    counts = meta["slug_base"].value_counts()
    dupes = set(counts[counts > 1].index)
    if dupes:
        log.info("disambiguating %d colliding slugs with a state suffix", len(dupes))
        meta["slug"] = [
            f"{b}-{slugify(s)}" if b in dupes else b
            for b, s in zip(meta["slug_base"], meta["state"])
        ]
    else:
        meta["slug"] = meta["slug_base"]

    # Pass 2: safety net so an unexpected duplicate can never break the build.
    counts = meta["slug"].value_counts()
    dupes = set(counts[counts > 1].index)
    if dupes:
        log.warning("resolving %d remaining slug collisions with a loc_pid suffix", len(dupes))
        meta["slug"] = [
            f"{s}-{pid[-6:]}" if s in dupes else s
            for s, pid in zip(meta["slug"], meta["loc_pid"])
        ]

    assert meta["slug"].is_unique, "slug collision survived disambiguation"
    return meta


def _km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    # sqrt(dx*dx + dy*dy) rather than math.hypot so the client-side bfs() in
    # neighbours.js, which computes Math.sqrt the same way, is bit-identical.
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return math.sqrt(dx * dx + dy * dy) / 1000.0


def round_km(value: float) -> float:
    """Half-up rounding to KM_PRECISION places.

    Python's round() is banker's rounding, while the JS client's Math.round
    rounds half away from zero. Distances landing exactly on a .x5 boundary would
    therefore differ by 0.1 km between the precomputed files and the client-side
    bfs(). Matching the client's rule keeps both paths byte-identical.
    """
    factor = 10 ** config.KM_PRECISION
    return math.floor(value * factor + 0.5) / factor


def _write_json(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def emit_all(
    meta: pd.DataFrame,
    centroids: pd.DataFrame,
    neighbours: dict[int, list[int]],
    lengths: dict[tuple[int, int], float],
    hops: dict[int, dict[int, list[int]]],
    sources: dict,
    out_dir: Path | None = None,
) -> dict:
    out_dir = Path(out_dir or config.SITE_DIR)
    api_dir = out_dir / "api" / "n"
    data_dir = out_dir / "data"

    meta = build_slugs(meta)
    # meta already carries centroid_kind (used by validation); avoid a duplicate
    # column from the merge.
    df = meta.merge(centroids.drop(columns=["centroid_kind"]), on="id", how="left")

    # Use plain dicts, not iterrows()/.loc: those upcast mixed str/None rows to
    # float64, turning a missing postcode into NaN and corrupting the JSON.
    rows = df.to_dict("records")
    by_id = {int(r["id"]): r for r in rows}

    xy = {int(r["id"]): (r["cx"], r["cy"]) for r in rows}
    names = {int(r["id"]): r["name"] for r in rows}
    states = {int(r["id"]): r["state"] for r in rows}
    pcodes = {int(r["id"]): r["primary_postcode"] for r in rows}

    stats = {"files": 0, "bytes": 0, "neighbour_entries": 0}

    # ------------------------------------------------ per-suburb API files
    for node_id, buckets in hops.items():
        row = by_id.get(node_id)
        if row is None:
            continue

        entries = []
        for hop in sorted(buckets):
            for other in buckets[hop]:
                km = _km_between(xy[node_id], xy[other])
                entries.append(
                    {
                        "suburb": names[other],
                        "postcode": pcodes[other],
                        "state": states[other],
                        "hops": hop,
                        "km": round_km(km),
                    }
                )
        entries.sort(key=lambda e: (e["hops"], e["km"], e["suburb"]))

        payload = {
            "suburb": row["name"],
            "postcode": row["primary_postcode"],
            "state": row["state"],
            "locality_id": row["loc_pid"],
            "postcodes": row["postcodes"],
            "centroid": {
                "lat": round(float(row["lat"]), config.COORD_PRECISION),
                "lon": round(float(row["lon"]), config.COORD_PRECISION),
                "kind": row["centroid_kind"],
            },
            "area_sqkm": round(float(row["area_sqkm"]), 2),
            "max_distance": config.MAX_HOPS,
            "neighbours": entries,
            "isolated": not entries,
            "truncated": any(
                len(buckets.get(h, ())) >= config.MAX_ENTRIES_PER_HOP for h in buckets
            ),
        }
        size = _write_json(api_dir / f"{row['slug']}.json", payload)
        stats["files"] += 1
        stats["bytes"] += size
        stats["neighbour_entries"] += len(entries)

    # ------------------------------------------------ dictionary
    # cx/cy are EPSG:3577 metres. Shipping them lets the client reproduce the
    # exact same centroid distance the build used, instead of approximating
    # from lat/lon and drifting by a few tens of metres.
    dictionary = {
        int(r["id"]): {
            "slug": r["slug"],
            "name": r["name"],
            "state": r["state"],
            "postcode": r["primary_postcode"],
            "postcodes": r["postcodes"],
            "lat": round(float(r["lat"]), config.COORD_PRECISION),
            "lon": round(float(r["lon"]), config.COORD_PRECISION),
            # Full precision, deliberately unrounded: the client reproduces km
            # from these, and a few centimetres of drift is enough to flip a
            # value sitting on a .x5 rounding boundary.
            "cx": float(r["cx"]),
            "cy": float(r["cy"]),
        }
        for r in rows
    }
    stats["bytes"] += _write_json(data_dir / "suburbs.json", dictionary)

    # ------------------------------------------------ graph (arbitrary depth)
    graph = {}
    for node_id, nbrs in neighbours.items():
        graph[str(node_id)] = [
            [int(n), round_km(_km_between(xy[node_id], xy[n])),
             round(lengths.get((node_id, n), 0.0) / 1000.0, 3)]
            for n in nbrs
        ]
    stats["bytes"] += _write_json(
        data_dir / "graph.json",
        {"note": "[neighbour_id, centroid_km, shared_boundary_km]", "adjacency": graph},
    )

    # ------------------------------------------------ search index shards
    shards: dict[str, list] = defaultdict(list)
    for r in rows:
        letter = slugify(r["name"])[:1] or "#"
        shards[letter].append(
            {
                "slug": r["slug"],
                "name": r["name"],
                "postcode": r["primary_postcode"],
                "state": r["state"],
            }
        )
    for letter, shard in shards.items():
        shard.sort(key=lambda e: (e["name"], e["postcode"] or ""))
        stats["bytes"] += _write_json(out_dir / "api" / "index" / f"{letter}.json", shard)

    log.info(
        "emitted %d suburb files (%d neighbour entries), %.1f MB total JSON",
        stats["files"], stats["neighbour_entries"], stats["bytes"] / 1e6,
    )
    return stats
