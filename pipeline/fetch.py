"""Download and cache source data: Geoscape localities + ABS Postal Areas."""
from __future__ import annotations

import json
import logging
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_USER_AGENT = "geolocate-build/1.0 (+https://github.com/)"
_TIMEOUT = 180


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    log.info("downloading %s", url)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh, length=1 << 20)
    tmp.replace(dest)


# ---------------------------------------------------------------- Geoscape
def resolve_locality_release(state: str) -> dict:
    """Find the newest Geoscape localities shapefile resource for a state.

    Resolution is done at build time against the live CKAN catalogue so the
    quarterly release rename (e.g. AUG26 -> NOV26) needs no code change.
    """
    package = config.STATE_PACKAGES[state]
    data = _get_json(f"{config.CKAN_API}/package_show?id={package}")["result"]

    zip_resources = [r for r in data["resources"] if str(r.get("url", "")).endswith(".zip")]
    if not zip_resources:
        raise RuntimeError(f"{state}: no shapefile zip resources in {package}")

    def rank(resource: dict) -> tuple:
        url = str(resource["url"]).lower()
        name = str(resource.get("name", "")).lower()
        for i, marker in enumerate(config.PREFERRED_DATUM_MARKERS):
            if url.endswith(f"_{marker}.zip") or marker in name:
                return (i,)
        return (len(config.PREFERRED_DATUM_MARKERS),)

    best = min(zip_resources, key=rank)
    return {
        "state": state,
        "package": package,
        "resource_name": best.get("name"),
        "url": best["url"],
        "metadata_modified": data.get("metadata_modified"),
        "dataset_title": data.get("title"),
    }


def fetch_localities(states: list[str]) -> dict:
    """Download (and cache) the locality shapefiles. Returns release metadata."""
    releases = {}
    for state in states:
        rel = resolve_locality_release(state)
        cache_name = rel["url"].rsplit("/", 1)[-1]
        rel["cached_zip"] = str(config.CACHE_DIR / state / cache_name)
        rel["extract_dir"] = str(config.CACHE_DIR / state / "shapefile")

        if not Path(rel["cached_zip"]).exists():
            _download(rel["url"], Path(rel["cached_zip"]))

        extract_dir = Path(rel["extract_dir"])
        if not extract_dir.exists() or not any(extract_dir.glob("*.shp")):
            extract_dir.mkdir(parents=True, exist_ok=True)
            log.info("extracting %s", rel["cached_zip"])
            with zipfile.ZipFile(rel["cached_zip"]) as zf:
                zf.extractall(extract_dir)

        releases[state] = rel
    return releases


# ---------------------------------------------------------------- ABS POA
def _poa_service_available(edition: dict) -> bool:
    url = (
        f"https://geo.abs.gov.au/arcgis/rest/services/{edition['key']}/POA/MapServer"
        "/0/query?where=1%3D1&returnCountOnly=true&f=json"
    )
    try:
        payload = _get_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False
    return "count" in payload


def resolve_poa_edition() -> dict:
    """Pick the newest published ASGS Postal Areas edition.

    ASGS Edition 4 Non-ABS structures (POA/SAL) roll out through October 2026,
    so newer services may 404 until then. Falls back cleanly.
    """
    for edition in config.POA_EDITIONS:
        if _poa_service_available(edition):
            log.info("using POA edition %s (%s)", edition["key"], edition["label"])
            return edition
    raise RuntimeError("no ASGS Postal Areas edition available")


def fetch_poa(edition: dict) -> Path:
    """Download all POA polygons as a single GeoJSON file (cached)."""
    dest = config.CACHE_DIR / "poa" / f"{edition['key']}.geojson"
    if dest.exists():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    base = f"https://geo.abs.gov.au/arcgis/rest/services/{edition['key']}/POA/MapServer/0/query"

    features: list[dict] = []
    offset = 0
    while True:
        params = (
            f"?where=1%3D1&outFields={edition['code_field']}&returnGeometry=true"
            f"&outSR=4326&f=geojson&resultOffset={offset}&resultRecordCount={config.POA_PAGE_SIZE}"
        )
        page = _get_json(base + params)
        batch = page.get("features", [])
        features.extend(batch)
        log.info("POA %s: fetched %d features", edition["key"], len(features))
        if len(batch) < config.POA_PAGE_SIZE:
            break
        offset += config.POA_PAGE_SIZE

    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    log.info("wrote %s (%d features)", dest, len(features))
    return dest
