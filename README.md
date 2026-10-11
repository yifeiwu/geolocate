# Australian Suburb Neighbourhood API

Given a **suburb** and **postcode**, returns every Australian suburb within *N* hops of connectivity —
where connectivity counts **shared boundaries**, not kilometres. Each neighbour reports both its hop count
and its straight-line distance, so you can filter on either.

- Hop 1 = the suburb shares a boundary with the input suburb
- Hop 2 = reachable via one intermediate suburb
- Hop 3 = reachable via two intermediate suburbs

There is no hop argument: every locality file holds the same fixed neighbourhood (depth 3 by default), so
the filtering is yours to do.

Covers **15,648 localities** across all eight states and territories plus external territories, built from
official gazetted boundaries.

---

## Why not just use straight-line distance?

Because "nearby" and "connected" are different questions. Parramatta is 1.9 km from Holroyd but two boundaries
away, while Constitution Hill is 3.7 km away and *three* boundaries away. A radius search cannot tell you that.
This API is built on boundary adjacency instead.

## Quick start

```bash
curl https://<user>.github.io/geolocate/api/parramatta-2150.json
```

```json
{
  "suburb": "Parramatta",
  "postcode": "2150",
  "state": "NSW",
  "locality_id": "loc581d5d75cd4f",
  "postcodes": ["2150", "2116"],
  "centroid": { "lat": -33.81397, "lon": 151.00688, "kind": "geometric" },
  "area_sqkm": 5.48,
  "max_distance": 3,
  "isolated": false,
  "truncated": false,
  "neighbours": [
    { "suburb": "Harris Park", "postcode": "2150", "state": "NSW", "hops": 1, "km": 1.0 },
    { "suburb": "Mays Hill",   "postcode": "2145", "state": "NSW", "hops": 1, "km": 1.8 }
  ]
}
```

Each file is self-contained — every neighbour carries its own name, postcode, state, hop count and
centroid distance. There is no hop parameter: every file holds the same fixed neighbourhood, so filter the
list yourself on `hops` or on `km`.

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/<name>-<postcode>.json` | The full precomputed neighbourhood, hops 1–3 |
| `GET /api/<name>-<postcode>-<state>.json` | Same, for the 5 cross-border localities (see below) |
| `GET /api/index/<letter>.json` | Search index sharded by first letter |
| `GET /data/suburbs.json` | Dictionary: `id → name, state, postcodes, centroid, cx, cy` |
| `GET /data/graph.json` | Raw adjacency: `id → [neighbour_id, km, shared_boundary_km]` |
| `GET /_meta.json` | Build timestamp, source releases, counts, attribution |

### Client library

`site/assets/neighbours.js` — no dependencies.

```html
<script src="assets/neighbours.js"></script>
<script>
  const api = createClient();
  const r = await api.query('Parramatta', '2150');
  console.log(r.neighbours);

  // every record carries both hops and km, so filter client-side
  const near = r.neighbours.filter(n => n.km <= 5);
  const direct = r.neighbours.filter(n => n.hops === 1);

  console.log(await api.search('parra', 10));
</script>
```

### Cross-border localities

Five localities share **both** a name and a postcode across a state border, so that pair is not unique and
their slugs carry a state suffix:

| Name | Postcode | States |
|---|---|---|
| Cottonvale | 4375 | NSW, QLD |
| Jervis Bay | 2540 | NSW, OT |
| Mingoola | 4380 | NSW, QLD |
| Mungindi | 2406 | NSW, QLD |
| Texas | 4385 | NSW, QLD |

Pass the state as the third argument, or fetch by slug:

```js
await api.query('Texas', '4385', 'QLD');   // texas-4385-qld
await api.getSuburbBySlug('texas-4385-nsw');

await api.query('Texas', '4385');
// throws err.code === 'AMBIGUOUS_SUBURB'
// err.slugs === ['texas-4385-nsw', 'texas-4385-qld']
```

`getSuburb()` tries the plain `<name>-<postcode>` slug first and only falls back to the search index when
that 404s, so ordinary lookups still cost exactly one request.

### Arbitrary hop counts

`graph.json` (43,373 edges) plus `suburbs.json` together are **smaller than the whole set of per-suburb
files** and carry the entire dataset, so this path is the cheaper way to load everything:

```js
const { graph, suburbs } = await api.loadGraph();
const id = Object.keys(suburbs).find(k => suburbs[k].slug === 'parramatta-2150');
api.bfs(graph, id, 6, suburbs);   // any depth
```

The dictionary must be the full one from `data/suburbs.json` — `bfs()` needs its `cx`/`cy` to measure
centroid-to-centroid distance. Without them it falls back to the per-edge distance, which is the distance to
the *previous* hop and is badly wrong past hop 1 (off by up to ~350 km on rural chains).

---

## How the graph is built

| Stage | What happens |
|---|---|
| **Fetch** | Geoscape PSMA Administrative Boundaries localities per jurisdiction (AUG26), resolved live from the data.gov.au CKAN catalogue so quarterly release renames need no code change. ABS Postal Areas via the newest published ASGS edition. |
| **Load** | `make_valid`, dissolve multi-part localities sharing a `LOC_PID`, reproject to **EPSG:3577** (GDA2020 Australian Albers). |
| **Adjacency** | `STRtree` bbox candidates → GEOS `intersection` → **adjacent iff shared boundary ≥ 1 m**. A `Point` result (corner touch) never counts. |
| **Centroids** | Geometric centroid; if it falls outside the polygon, fall back to a representative point of the largest part and flag `centroid.kind`. |
| **Postcodes** | Spatial join against Postal Areas; every postcode covering ≥ 0.5% is listed, the largest becomes `postcode`. |
| **Hops** | Breadth-first to depth 3, bucketed per node, capped at 2,000 entries per hop. |

Current build: **43,373 connections**, mean degree 5.54, **1,047 corner-only contacts rejected**.

## Behaviour worth knowing

**Corner contact is not adjacency.** Four suburbs meeting at a single point are all 2 hops apart, never 1.

**River-separated suburbs are not adjacent.** Geoscape models waterways as gaps, so the Melbourne CBD and
Fitzroy sit ~144 m apart across the Yarra and are *not* connected. Fitzroy borders Carlton, East Melbourne and
Collingwood instead. This is faithful to the source, but surprises people.

**`km` and `hops` are independent.** A suburb 2 hops away can be closer in kilometres than one 1 hop away —
long thin corridor suburbs are the usual case. Never infer one from the other. `km` is straight-line
centroid-to-centroid in Albers, rounded to 100 m.

**Centroids can fall outside a suburb.** For concave or multi-part polygons the geometric centroid may lie in
the sea or the desert. 116 localities (0.7%) hit this and fall back to a representative point, flagged as
`"kind": "fallback"`. These are overwhelmingly remote pastoral areas.

**Isolated localities are real.** Islands and remote stations return `"isolated": true` and an empty list —
Lord Howe Island, French Island, the Wellesley Islands, and 25 others.

**Eight localities have no postcode.** They are marine areas — Arafura Sea, Coral Sea, Beagle Gulf, Darwin
Harbour, and others — which fall outside Postal Areas coverage.

**Names collide across borders.** Five ABS postcodes straddle a state line (2406, 4375, 4380, 4385, 2540), so
the same locality name and postcode legitimately exists on both sides. Those slugs gain a state suffix:
`cottonvale-4375-nsw` and `cottonvale-4375-qld`.

**Postcodes come from ABS Postal Areas**, a mesh-block approximation — not Australia Post. Boundary changes
after the current ASGS edition are not reflected.

---

## Build it yourself

```bash
pip install -r requirements.txt

python -m pipeline.run --states NSW,VIC --max-hops 3 --out site   # fast iteration
python -m pipeline.run                                              # full national build

python -m pipeline.verify_client --site site    # client bfs() == precomputed files
python -m pipeline.verify_site                  # site links/assets == emitted data
python -m pipeline.cache_key                    # CI source-cache fingerprint
```

A full build takes ~4.5 minutes and downloads ~400 MB of source data (cached in `data/cache/`).

Useful flags: `--min-shared-boundary 100` (require 100 m of shared border for distance 1),
`--max-hops N`, `--min-shared-boundary M`, `--out DIR`.

### Layout

```
pipeline/
  config.py          sources, CRS, tunables, attribution
  fetch.py           CKAN resolution + cached downloads; ABS edition probing
  load.py            read, repair, dissolve, reproject
  centroids.py       centroid with in-polygon test and fallback
  adjacency.py       shared-boundary graph
  postcodes.py       locality x postal area join
  hops.py            BFS expansion
  emit.py             JSON artefacts (per-suburb, dictionary, graph, index)
  validate.py         symmetry, known adjacencies, output schema
  verify_client.py    parity check: client bfs() vs precomputed files
  verify_site.py      site links/assets vs emitted data
  cache_key.py        upstream-release fingerprint for the CI cache
  run.py              CLI entry point
site/                the published static site
```

### Why GitHub Pages can host an API

GitHub Pages is static-only, so the graph is **precomputed at build time** and served as JSON. Each suburb is
one file holding its whole neighbourhood; narrowing to fewer hops or a kilometre radius is a client-side
filter on the `hops` and `km` fields. A GitHub Actions workflow rebuilds quarterly
(after each Geoscape release) and on manual dispatch, and fails the build if the site exceeds the 1 GB cap.

The source cache is keyed on an **upstream-release fingerprint** (`pipeline/cache_key.py` hashes Geoscape's
`metadata_modified` plus the POA edition counts) rather than the run id. A push therefore reuses the ~400 MB
of cached source data, while a new quarterly release or a newly published ASGS edition invalidates it exactly
once. Both verifiers run in CI before deploy.

## Validation

Every build asserts graph symmetry, shared-boundary symmetry, no dangling edges, and the output schema, and
spot-checks 14 known adjacencies across all capitals (Sydney–Millers Point, Melbourne–Carlton,
Brisbane City–South Brisbane, Perth–West Perth, Adelaide–Kent Town, Hobart–Sandy Bay, and others).

```bash
python -m pipeline.verify_client --site site   # client bfs() vs precomputed files
python -m pipeline.verify_site                 # site links/assets vs emitted data
```

`verify_client` re-implements the client `bfs()` in Python and asserts it reproduces every precomputed
`api/*.json` byte-for-byte across all 15,648 localities — so the documented client contract cannot silently
drift from the data. (It shares the exact distance expression and rounding rule, which is why
`suburbs.json` publishes full-precision projected coordinates.)

It also mirrors `getSuburb()`'s slug resolution and asserts every postcoded locality is reachable, that each
one resolves to its *own* slug, and that exactly the 5 cross-border pairs raise as ambiguous without a state.

> There is no JS runtime in the build environment, so `neighbours.js` is verified this way rather than by
> executing it. Both mirrors are line-for-line transcriptions; if you change the client, change them too.

`verify_site` checks that every asset, `fetch()` path and element ID the HTML and JS reference actually exists,
that the documented example slugs are real, and that the 15,648 emitted files and 26 index shards cover every
locality with no orphans.

Distances were independently cross-checked against OzDataHub's figures derived from the same source; results
agree to within ~50 m (e.g. Parramatta → Harris Park 1.00 km vs 1.03 km).

## Attribution

- Suburb boundaries: Administrative Boundaries (Geoscape Localities) © Geoscape Australia, licensed by the
  Commonwealth of Australia under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Postcodes: Postal Areas © Commonwealth of Australia (Australian Bureau of Statistics),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

This project is not affiliated with or endorsed by Geoscape Australia or the ABS.
