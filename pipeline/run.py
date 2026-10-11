"""Build entry point.

    python -m pipeline.run --states NSW --max-hops 3
    python -m pipeline.run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from . import adjacency, centroids, config, emit, fetch, hops, load, postcodes, validate

log = logging.getLogger("pipeline")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the suburb neighbourhood API")
    ap.add_argument("--states", default="ALL",
                    help="comma-separated states, or ALL (default)")
    ap.add_argument("--max-hops", type=int, default=config.MAX_HOPS)
    ap.add_argument("--min-shared-boundary", type=float, default=config.MIN_SHARED_BOUNDARY_M,
                    help="metres of shared boundary required for distance 1")
    ap.add_argument("--out", default=str(config.SITE_DIR))
    ap.add_argument("--skip-sqlite", action="store_true")
    ap.add_argument("--cache-only", action="store_true",
                    help="use cached downloads; fail if anything is missing")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)

    config.MAX_HOPS = args.max_hops
    config.MIN_SHARED_BOUNDARY_M = args.min_shared_boundary

    states = list(config.STATE_PACKAGES) if args.states.upper() == "ALL" else [
        s.strip().upper() for s in args.states.split(",") if s.strip()
    ]
    unknown = [s for s in states if s not in config.STATE_PACKAGES]
    if unknown:
        ap.error(f"unknown states: {unknown}")

    started = dt.datetime.now(dt.timezone.utc)
    log.info("building %d state(s): %s", len(states), ",".join(states))

    # ---------------------------------------------------------- 1. fetch
    releases = fetch.fetch_localities(states)
    poa_edition = fetch.resolve_poa_edition()
    poa_path = fetch.fetch_poa(poa_edition)

    # ---------------------------------------------------------- 2. load
    localities = load.load_all_localities(releases)
    poa = load.load_poa(poa_path)

    # ---------------------------------------------------------- 3. enrich
    log.info("--- computing centroids ---")
    cen = centroids.compute_centroids(localities)

    log.info("--- assigning postcodes ---")
    pc = postcodes.assign_postcodes(localities, poa)
    meta = (
        localities[["id", "loc_pid", "name", "state"]]
        .merge(pc, on="id", how="left")
        .merge(cen[["id", "centroid_kind"]], on="id", how="left")
    )

    # ---------------------------------------------------------- 4. graph
    log.info("--- building adjacency graph ---")
    neighbours, lengths = adjacency.build_adjacency(localities)
    log.info("--- expanding to %d hops ---", config.MAX_HOPS)
    hop_map = hops.expand(neighbours, config.MAX_HOPS, nodes=meta["id"].tolist())

    # ---------------------------------------------------------- 5. validate
    log.info("--- validating ---")
    warn = validate.validate_graph(meta, neighbours, lengths)
    warn += validate.validate_known(meta, neighbours)

    # ---------------------------------------------------------- 6. emit
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = emit.emit_all(meta, cen, neighbours, lengths, hop_map,
                          releases, out_dir=out_dir, write_sqlite=not args.skip_sqlite)

    warn += validate.validate_output(out_dir, len(meta))

    # ---------------------------------------------------------- 7. metadata
    meta_payload = {
        "generated_at": started.isoformat(),
        "duration_seconds": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
        "locality_count": int(len(meta)),
        "edge_count": int(sum(len(v) for v in neighbours.values()) // 2),
        "isolated_count": int(sum(1 for b in hop_map.values() if not any(b.values()))),
        "centroid_fallback_count": int((meta["centroid_kind"] == "fallback").sum()),
        "no_postcode_count": int(meta["primary_postcode"].isna().sum()),
        "max_distance": config.MAX_HOPS,
        "min_shared_boundary_m": config.MIN_SHARED_BOUNDARY_M,
        "postcode_edition": poa_edition,
        "states": {
            s: {"release": r["resource_name"], "url": r["url"],
                "metadata_modified": r["metadata_modified"]}
            for s, r in releases.items()
        },
        "attribution": config.ATTRIBUTION,
        "output_bytes": stats["bytes"],
    }
    (out_dir / "_meta.json").write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")

    for w in warn:
        log.warning("VALIDATION: %s", w)
    log.info("done in %.1fs -> %s", meta_payload["duration_seconds"], out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
