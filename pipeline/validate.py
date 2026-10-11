"""Post-build validation. Raises on structural failure, warns on anomalies."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Pairs verified against the source boundaries. Note these deliberately avoid
# river-separated pairs: Geoscape models the Yarra as a ~144 m gap, so the
# Melbourne CBD and Fitzroy are correctly NOT adjacent.
KNOWN_ADJACENCIES = [
    ("NSW", "Parramatta", "Harris Park"),
    ("NSW", "Parramatta", "Westmead"),
    ("NSW", "Chatswood", "Willoughby"),
    ("NSW", "Sydney", "Millers Point"),
    ("VIC", "Melbourne", "Carlton"),
    ("VIC", "Melbourne", "East Melbourne"),
    ("VIC", "Fitzroy", "Collingwood"),
    ("TAS", "Hobart", "Sandy Bay"),
    ("QLD", "Brisbane City", "South Brisbane"),
    ("QLD", "Brisbane City", "Fortitude Valley"),
    ("WA", "Perth", "West Perth"),
    ("WA", "Perth", "North Perth"),
    ("SA", "Adelaide", "North Adelaide"),
    ("SA", "Adelaide", "Kent Town"),
]


def validate_graph(meta: pd.DataFrame, neighbours: dict, lengths: dict) -> list[str]:
    warnings = []
    ids = set(meta["id"])

    asym = [a for a, nbrs in neighbours.items() for b in nbrs if a not in neighbours.get(b, [])]
    if asym:
        raise AssertionError(f"graph is not symmetric ({len(asym)} asymmetric edges)")
    log.info("symmetry: ok (%d edges)", sum(len(v) for v in neighbours.values()) // 2)

    dangling = [b for nbrs in neighbours.values() for b in nbrs if b not in ids]
    if dangling:
        raise AssertionError(f"{len(dangling)} edges reference unknown ids")

    km_sym = [p for p in lengths if (p[1], p[0]) not in lengths]
    if km_sym:
        raise AssertionError(f"{len(km_sym)} shared-boundary lengths not symmetric")

    isolated = len(ids) - len(neighbours)
    if isolated:
        warnings.append(f"{isolated} localities have no neighbours (rural/remote)")

    no_pc = int(meta["primary_postcode"].isna().sum())
    if no_pc:
        warnings.append(f"{no_pc} localities have no postcode assignment")

    fallback = int((meta["centroid_kind"] == "fallback").sum())
    log.info("centroid fallback used for %d localities (%.1f%%)", fallback, 100.0 * fallback / max(len(meta), 1))

    return warnings


def validate_known(meta: pd.DataFrame, neighbours: dict) -> list[str]:
    warnings = []
    by_key = {(r["state"], r["name"]): int(r["id"]) for _, r in meta.iterrows()}
    for state, a, b in KNOWN_ADJACENCIES:
        ia, ib = by_key.get((state, a)), by_key.get((state, b))
        if ia is None or ib is None:
            warnings.append(f"spot-check skipped: {a}/{b} not in dataset")
            continue
        if ib not in neighbours.get(ia, []):
            warnings.append(f"SPOT CHECK FAILED: {a} ({state}) is not adjacent to {b}")
        else:
            log.info("spot check ok: %s (%s) ~ %s", a, state, b)
    return warnings


def validate_output(site_dir: Path, expected: int) -> list[str]:
    warnings = []
    api = site_dir / "api"
    files = sorted(api.glob("*.json"))
    if len(files) != expected:
        raise AssertionError(f"expected {expected} suburb files, found {len(files)}")

    for required in ("data/suburbs.json", "data/graph.json"):
        if not (site_dir / required).exists():
            raise AssertionError(f"missing artefact: {required}")

    top_keys = ("suburb", "postcode", "state", "centroid", "neighbours",
                "isolated", "truncated", "max_distance")
    nbr_keys = ("suburb", "postcode", "state", "hops", "km")
    # spot the schema across several files, not just one, so a change that only
    # affects part of the output cannot slip through.
    for sample in (files[i] for i in range(0, len(files), max(1, len(files) // 5))):
        payload = json.loads(sample.read_text(encoding="utf-8"))
        for key in top_keys:
            if key not in payload:
                raise AssertionError(f"{sample.name} missing key '{key}'")
        hops = []
        for entry in payload["neighbours"]:
            for key in nbr_keys:
                if key not in entry:
                    raise AssertionError(f"{sample.name} neighbour missing key '{key}'")
            if not 1 <= entry["hops"] <= payload["max_distance"]:
                raise AssertionError(
                    f"{sample.name} neighbour hops {entry['hops']} out of range"
                )
            hops.append((entry["hops"], entry["km"]))
        if hops != sorted(hops):
            raise AssertionError(f"{sample.name} neighbours are not sorted by hops then km")
    log.info("schema check ok (%d neighbours in %s)", len(payload["neighbours"]), sample.name)
    return warnings
