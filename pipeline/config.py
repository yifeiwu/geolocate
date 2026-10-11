"""Central configuration for the suburb neighbourhood build."""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("GEOLOCATE_CACHE", ROOT / "data" / "cache"))
SITE_DIR = Path(os.environ.get("GEOLOCATE_SITE", ROOT / "site"))

# ---------------------------------------------------------------- sources
CKAN_API = "https://data.gov.au/data/api/3/action"

# State/territory code -> data.gov.au package name for Geoscape localities.
STATE_PACKAGES = {
    "NSW": "nsw-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "VIC": "vic-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "QLD": "qld-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "WA": "wa-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "SA": "sa-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "TAS": "tas-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "ACT": "act-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "NT": "nt-suburb-locality-boundaries-geoscape-administrative-boundaries",
    "OT": "other-suburb-locality-boundaries-geoscape-administrative-boundaries",
}

# Prefer the GDA2020 datum; fall back to GDA94 if a release omits it.
PREFERRED_DATUM_MARKERS = ("gda2020", "gda94")

# ABS Postal Areas. Newest first: ASGS Edition 4 (2026) Non-ABS structures are
# released progressively through October 2026, so the 2026 services may not
# exist yet. The builder probes each in order and uses the first that answers.
POA_EDITIONS = [
    {"key": "ASGS2026", "label": "ASGS Edition 4 (2026)", "code_field": "poa_code_2026"},
    {"key": "ASGS2021", "label": "ASGS Edition 3 (2021)", "code_field": "poa_code_2021"},
    {"key": "ASGS2016", "label": "ASGS Edition 2 (2016)", "code_field": "poa_code_2016"},
]
POA_PAGE_SIZE = 500

# ---------------------------------------------------------------- geometry
GEOGRAPHIC_CRS = "EPSG:4283"  # GDA2020 geographic
ALBERS_CRS = "EPSG:3577"  # GDA2020 Australian Albers

# Two localities are "directly connected" when they share a boundary of at
# least this length. Point contact (a single shared corner) never counts.
MIN_SHARED_BOUNDARY_M = 1.0

# Structural classes that are groupings rather than localities. The ACT is the
# only jurisdiction that publishes these: its layer carries 121 "Gazetted
# Locality" rows (matching the official ACT division count) alongside 19 larger
# "District" rows that *contain* those suburbs. Keeping districts creates
# duplicate nodes for the same place and spurious adjacency.
EXCLUDED_CLASSES = {"district"}

# ---------------------------------------------------------------- graph
MAX_HOPS = 3
# Safety valve: a few metro suburbs explode at 3 hops. Cap per-bucket output
# and flag truncation in the payload rather than emitting unbounded files.
MAX_ENTRIES_PER_HOP = 2000

# ---------------------------------------------------------------- postcodes
# A secondary postcode is only listed if it covers at least this share of the
# locality's area. Keeps sliver overlaps out of the payload.
POSTCODE_MIN_OVERLAP_PCT = 0.5

# ---------------------------------------------------------------- output
KM_PRECISION = 1
COORD_PRECISION = 5

ATTRIBUTION = {
    "suburbs": (
        "Administrative Boundaries (Geoscape Localities) © Geoscape Australia, "
        "licensed by the Commonwealth of Australia under CC BY 4.0"
    ),
    "postcodes": (
        "Postal Areas © Commonwealth of Australia (Australian Bureau of Statistics), "
        "CC BY 4.0"
    ),
}
