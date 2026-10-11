"""Assign postcodes to localities.

Geoscape localities carry no postcode, so we spatially join them against ABS
Postal Areas and record every postcode covering a meaningful share of the
locality, plus the dominant one.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

from . import config

log = logging.getLogger(__name__)


def assign_postcodes(localities: gpd.GeoDataFrame, poa: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return one row per locality with its postcodes and primary postcode."""
    geoms = np.asarray(localities.geometry.to_numpy(), dtype=object)
    poa_geoms = np.asarray(poa.geometry.to_numpy(), dtype=object)

    tree = STRtree(poa_geoms)
    pairs = tree.query(geoms, predicate="intersects")
    left, right = pairs[0], pairs[1]

    log.info("postcode join: %d locality/POA candidate pairs", len(left))

    suburb_area = shapely.area(geoms)
    inter_area = shapely.area(shapely.intersection(geoms[left], poa_geoms[right]))

    ids = localities["id"].to_numpy()
    codes = poa["postcode"].to_numpy()

    buckets: dict[int, list[tuple[str, float]]] = {}
    for sid, code, area in zip(ids[left], codes[right], inter_area):
        pct = 100.0 * area / suburb_area[sid] if suburb_area[sid] > 0 else 0.0
        if pct >= config.POSTCODE_MIN_OVERLAP_PCT:
            buckets.setdefault(int(sid), []).append((str(code), float(pct)))

    records = []
    for sid in ids:
        entries = buckets.get(int(sid), [])
        # Merge duplicate postcode codes across separate parts of one locality.
        merged: dict[str, float] = {}
        for code, pct in entries:
            merged[code] = merged.get(code, 0.0) + pct
        ordered = sorted(merged.items(), key=lambda kv: -kv[1])
        records.append(
            {
                "id": int(sid),
                "postcodes": [c for c, _ in ordered],
                "primary_postcode": ordered[0][0] if ordered else None,
                "postcode_coverage_pct": round(ordered[0][1], 1) if ordered else 0.0,
            }
        )

    out = pd.DataFrame(records)
    # Keep None (not NaN) for unassigned localities so downstream JSON emits a
    # clean null and string sorting stays well-defined. object dtype is required:
    # pandas' inferred `str` dtype silently converts None back to NaN.
    out["primary_postcode"] = pd.Series(
        [None if pd.isna(v) else str(v) for v in out["primary_postcode"]],
        index=out.index, dtype=object,
    )
    assigned = out["primary_postcode"].notna().sum()
    multi = (out["postcodes"].apply(len) > 1).sum()
    log.info(
        "postcodes: %d/%d localities assigned, %d span multiple postcodes",
        assigned, len(out), multi,
    )
    if assigned < len(out):
        log.warning("%d localities have no postcode coverage", len(out) - assigned)
    return out
