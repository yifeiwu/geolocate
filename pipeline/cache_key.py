"""Print a cache key derived from the actual source-data release.

Used by CI so the downloaded source cache is invalidated exactly when Geoscape
or the ABS publishes, rather than on every single build. Stdlib only, so it runs
before the geospatial dependencies are installed.

    python -m pipeline.cache_key
"""
from __future__ import annotations

import hashlib
import json
import urllib.request

from .config import CKAN_API, POA_EDITIONS, STATE_PACKAGES

_TIMEOUT = 60


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "geolocate-build/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.load(resp)


def source_fingerprint() -> tuple[str, dict]:
    """Fingerprint every source release the build depends on."""
    parts: dict[str, str] = {}

    package = STATE_PACKAGES["NSW"]
    try:
        data = _get_json(f"{CKAN_API}/package_show?id={package}")["result"]
        # metadata_modified moves on every quarterly re-publication.
        parts["geoscape"] = str(data.get("metadata_modified", "unknown"))
    except Exception:
        parts["geoscape"] = "unavailable"

    for edition in POA_EDITIONS:
        url = (
            f"https://geo.abs.gov.au/arcgis/rest/services/{edition['key']}/POA/MapServer"
            "/0/query?where=1%3D1&returnCountOnly=true&f=json"
        )
        try:
            payload = _get_json(url)
            # A not-yet-released service answers HTTP 200 with an error object.
            parts[f"poa_{edition['key']}"] = (
                "absent" if "error" in payload else str(payload.get("count", "unknown"))
            )
        except Exception:
            parts[f"poa_{edition['key']}"] = "absent"

    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]
    return digest, parts


def main() -> int:
    digest, parts = source_fingerprint()
    print(f"geolocate-sources-{digest}")
    for key, value in parts.items():
        print(f"::debug::{key} = {value}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
