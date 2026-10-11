"""Centroid computation with a guaranteed-inside fallback.

The geometric centroid of a concave or multi-part polygon can fall outside the
polygon entirely. Australian localities are full of such shapes: coastal strips,
river corridors, peninsulas, and rural NT/QLD/WA localities made of hundreds of
disjoint parcels whose area-weighted centroid lands out in the desert or the
ocean. Distances measured from those points are misleading, so we detect the
case and fall back to a representative point of the largest part.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import contains_properly

from . import config

log = logging.getLogger(__name__)


def _largest_part(geom):
    parts = getattr(geom, "geoms", None)
    if parts is None:
        return geom
    return max(parts, key=lambda p: p.area)


def compute_centroids(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return lat/lon centroids plus a flag for where the fallback was used."""
    geoms = gdf.geometry
    projected = geoms.centroid

    # contains_properly excludes the boundary itself; a centroid sitting exactly
    # on an edge is not a meaningful anchor.
    inside = contains_properly(geoms, projected)

    lat = projected.x.to_numpy().copy()
    lon = projected.y.to_numpy().copy()
    kind = np.where(inside, "geometric", "fallback")

    fallback_idx = (~inside).to_numpy().nonzero()[0]
    if fallback_idx.size:
        log.info(
            "%d of %d localities (%.1f%%) needed the centroid fallback",
            fallback_idx.size, len(gdf), 100.0 * fallback_idx.size / len(gdf),
        )
        reps = [ _largest_part(geoms.iloc[i]).representative_point() for i in fallback_idx ]
        lat[fallback_idx] = [r.x for r in reps]
        lon[fallback_idx] = [r.y for r in reps]

    out = pd.DataFrame(
        {
            "id": gdf["id"].to_numpy(),
            "cx": lat,
            "cy": lon,
            "centroid_kind": kind,
            "area_sqkm": (geoms.area / 1e6).to_numpy(),
        }
    )
    geo = gpd.GeoSeries(gpd.points_from_xy(lat, lon), crs=config.ALBERS_CRS)
    wgs = geo.to_crs(config.GEOGRAPHIC_CRS)
    out["lat"] = wgs.y.to_numpy()
    out["lon"] = wgs.x.to_numpy()
    return out
