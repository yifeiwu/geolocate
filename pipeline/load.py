"""Read source boundaries and normalise them into a working projection."""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd
from shapely import make_valid

from . import config

log = logging.getLogger(__name__)

# Field names vary slightly between Geoscape releases and state extracts.
NAME_FIELDS = ("LOC_NAME", "SUBURB", "LOCALITY", "SITE_NAME", "name")
PID_FIELDS = ("LOC_PID", "LC_PLY_PID", "SUBURB_PID", "OBJECTID", "objectid")
STATE_FIELDS = ("STATE", "STATE_ABBR", "STE", "state")
CLASS_FIELDS = ("LOC_CLASS", "CLASS", "TYPE", "CATEGORY")

# Classes that are not residential/administrative localities.
EXCLUDED_CLASS_TOKENS = ("island", "reef", "rock", "water", "offshore")

def _pick(columns, candidates: tuple[str, ...], fallback: str) -> str:
    upper = {c.upper(): c for c in columns}
    for cand in candidates:
        if cand in upper:
            return upper[cand]
    return fallback


def _fix_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    before = len(gdf)
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    after_invalid = (~gdf.geometry.is_valid).sum()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid]
    if after_invalid or len(gdf) != before:
        log.info("geometry repair: %d -> %d features (%d still invalid)", before, len(gdf), after_invalid)
    return gdf


def load_localities(state: str, extract_dir) -> gpd.GeoDataFrame:
    shp = next(iter(sorted(extract_dir.rglob("*.shp"))))
    gdf = gpd.read_file(shp)

    name_col = _pick(gdf.columns, NAME_FIELDS, gdf.columns[0])
    pid_col = _pick(gdf.columns, PID_FIELDS, name_col)
    state_col = _pick(gdf.columns, STATE_FIELDS, "")
    class_col = _pick(gdf.columns, CLASS_FIELDS, "")

    out = pd.DataFrame(
        {
            "loc_pid": gdf[pid_col].astype(str),
            "name": gdf[name_col].astype(str).str.strip(),
            "state": (gdf[state_col].astype(str).str.strip().str.upper() if state_col else state),
            "loc_class": (gdf[class_col].astype(str).str.strip() if class_col else ""),
        }
    )

    if class_col:
        lowered = out["loc_class"].str.lower()
        mask = lowered.isin(config.EXCLUDED_CLASSES) | lowered.apply(
            lambda c: any(tok in c for tok in EXCLUDED_CLASS_TOKENS)
        )
        if mask.any():
            dropped = sorted(out.loc[mask, "loc_class"].unique())
            log.info("%s: dropping %d non-locality features %s", state, int(mask.sum()), dropped)
            out = out[~mask]

    out = out[out["name"].str.len() > 0].reset_index(drop=True)

    geom = gdf.geometry.reset_index(drop=True)
    out["geometry"] = geom
    gdf = gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs)
    gdf = _fix_geometry(gdf)

    src = gdf.crs.to_string() if gdf.crs else "unknown"
    log.info("%s: %d locality features (crs=%s)", state, len(gdf), src)

    gdf = gdf.to_crs(config.ALBERS_CRS)

    # One locality can be stored as several polygon rows sharing a LOC_PID
    # (e.g. Budgewoi, Chatswood West). Dissolve so the graph gets one node per
    # locality while keeping every part.
    multi = int(gdf["loc_pid"].duplicated().sum())
    if multi:
        log.info("%s: dissolving %d duplicate LOC_PID rows", state, multi)
        gdf = gdf.dissolve(by="loc_pid", aggfunc="first").reset_index()
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=config.ALBERS_CRS)
        gdf = _fix_geometry(gdf)

    log.info("%s: %d unique localities in %s", state, len(gdf), config.ALBERS_CRS)
    return gdf


def load_all_localities(releases: dict) -> gpd.GeoDataFrame:
    from pathlib import Path

    frames = [load_localities(state, Path(rel["extract_dir"])) for state, rel in releases.items()]
    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=config.ALBERS_CRS
    )
    # A locality name can legitimately repeat within a state (Geoscape keys it by
    # LOC_PID), but a duplicated LOC_PID across states would corrupt the graph.
    dupes = combined["loc_pid"].duplicated().sum()
    if dupes:
        log.warning("dropping %d rows with duplicate LOC_PID", dupes)
        combined = combined.drop_duplicates(subset="loc_pid", keep="first")
    combined = combined.reset_index(drop=True)
    combined["id"] = range(len(combined))
    log.info("total localities: %d", len(combined))
    return combined


def load_poa(path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    code_col = _pick(gdf.columns, ("poa_code_2026", "poa_code_2021", "poa_code_2016"), gdf.columns[0])
    out = pd.DataFrame({"postcode": gdf[code_col].astype(str).str.strip()})
    out["geometry"] = gdf.geometry.reset_index(drop=True)
    gdf = gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs or "EPSG:4326")
    gdf = _fix_geometry(gdf)
    gdf = gdf.to_crs(config.ALBERS_CRS).reset_index(drop=True)
    log.info("POA: %d postal areas", len(gdf))
    return gdf
