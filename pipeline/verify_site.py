"""Static consistency check between the site and the built data.

Verifies every asset/link the HTML and JS reference actually exists, that the
JSON paths the client builds match the emitted slugs, and that no element ID
targeted by app.js is missing from index.html.
"""
import json, re, pathlib, sys

site = pathlib.Path("site")
html = (site / "index.html").read_text(encoding="utf-8")
app = (site / "assets" / "app.js").read_text(encoding="utf-8")
lib = (site / "assets" / "neighbours.js").read_text(encoding="utf-8")

problems = []

# 1. local asset references in HTML
for m in re.finditer(r'(?:href|src)="([^"#:]+)"', html):
    ref = m.group(1)
    if ref.startswith(("http", "mailto")):
        continue
    if not (site / ref).exists():
        problems.append(f"missing asset referenced by index.html: {ref}")

# 2. fetch() paths used by the JS
for m in re.finditer(r"fetch\('([^']+)'\)", app + lib):
    p = m.group(1)
    if not (site / p).exists():
        problems.append(f"missing data file fetched by JS: {p}")

for m in re.finditer(r"BASE \+ '([^']+)'", lib):
    p = m.group(1)
    # /api/n/<slug>.json and /api/index/<letter>.json are parameterised
    if "<" in p or ".json" not in p:
        continue
    if not (site / p.lstrip("/")).exists():
        problems.append(f"missing data file referenced in neighbours.js: {p}")

# 3. every $('id') in app.js exists in the HTML
ids = set(re.findall(r'id="([^"]+)"', html))
for m in re.finditer(r"\$\('([^']+)'\)", app):
    if m.group(1) not in ids:
        problems.append(f"app.js targets missing element id: #{m.group(1)}")

# 4. the id the client library needs must be present too
for needed in ("suburb", "postcode", "distance", "form", "suggestions"):
    if needed not in ids:
        problems.append(f"index.html missing required id: #{needed}")

# 5. sample slugs resolve, and the documented example is real
subs = json.loads((site / "data" / "suburbs.json").read_text(encoding="utf-8"))
slugs = {v["slug"] for v in subs.values()}
for doc_slug in re.findall(r"/api/n/([a-z0-9-]+)\.json", html):
    if doc_slug not in slugs:
        problems.append(f"documented example slug does not exist: {doc_slug}")

# 6. every suburbs.json entry has a file on disk
api = site / "api" / "n"
files = {p.stem for p in api.glob("*.json")}
if files != slugs:
    problems.append(f"slug/file mismatch: {len(slugs - files)} missing, {len(files - slugs)} orphan")

# 7. index shards cover every locality
shard_names = set()
for p in (site / "api" / "index").glob("*.json"):
    shard_names.update(e["slug"] for e in json.loads(p.read_text(encoding="utf-8")))
if shard_names != slugs:
    problems.append(f"index shard mismatch: {len(slugs - shard_names)} missing, {len(shard_names - slugs)} extra")

# 8. the client must resolve its site root from the script URL, otherwise it
#    breaks on project sites served from a sub-path (e.g. /geolocate/).
if "document.currentScript" not in lib:
    problems.append("neighbours.js does not self-locate its base path "
                    "(will 404 on project sites served from a sub-path)")
if not re.search(r"replace\(/\\/\+\$/, ''\)", lib):
    problems.append("neighbours.js does not strip the trailing slash from BASE "
                    "(would produce double-slash URLs)")

print(f"assets checked      : {len(list(site.glob('assets/*')))}")
print(f"locality files      : {len(files)}")
print(f"index shard entries : {len(shard_names)}")
print(f"problems            : {len(problems)}")
for p in problems:
    print("  -", p)
sys.exit(1 if problems else 0)
