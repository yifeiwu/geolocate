/**
 * neighbours.js - tiny client for the Australian suburb neighbourhood API.
 *
 * Works against the precomputed static JSON on GitHub Pages. No dependencies.
 *
 *   const api = createClient();
 *   const r = await api.query('Parramatta', '2150');
 *   // r.neighbours -> [{suburb, postcode, state, hops, km}, ...]
 *
 * Every file holds the same fixed neighbourhood, so there is no hop argument to
 * pass - filter the returned list yourself on `hops` or `km`.
 *
 * For hop counts beyond the precomputed maximum, load data/graph.json and call
 * bfs() instead - it runs client-side over the raw adjacency graph.
 */
(function (global) {
  'use strict';

  // Resolve the site root from this script's own URL so the client works
  // unchanged on a user site (/), a project site (/geolocate/) or a custom
  // domain. Set window.GEOLOCATE_BASE before loading to override explicitly.
  var BASE = '';
  if (global.GEOLOCATE_BASE != null) {
    BASE = String(global.GEOLOCATE_BASE);
  } else if (typeof document !== 'undefined' && document.currentScript) {
    BASE = (document.currentScript.src || '').replace(/\/assets\/neighbours\.js.*$/, '');
  }
  BASE = BASE.replace(/\/+$/, '');

  var ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyz'.split('');
  // id -> {name, postcode, state, cx, cy} populated by loadGraph().
  var metaCache = null;

  function json(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw httpError(r.status, url);
      return r.json();
    });
  }

  function httpError(status, url) {
    var e = new Error('HTTP ' + status + ' for ' + url);
    e.status = status;
    e.url = url;
    return e;
  }

  var shardCache = {};

  function loadShard(letter) {
    if (!shardCache[letter]) {
      shardCache[letter] = json(BASE + '/api/index/' + letter + '.json')
        .catch(function () { return []; });
    }
    return shardCache[letter];
  }

  function slugify(text) {
    return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  /** Fetch one locality's full record by its exact slug. */
  function getSuburbBySlug(slug) {
    return json(BASE + '/api/' + slug + '.json');
  }

  function notFound(suburb, postcode) {
    var e = new Error('no locality matching "' + suburb + ' ' + postcode + '"');
    e.code = 'NOT_FOUND';
    return e;
  }

  function ambiguous(name, postcode, hits) {
    var states = hits.map(function (h) { return h.state; });
    var e = new Error(
      '"' + name + ' ' + postcode + '" is in ' + states.join(' and ') +
      '; pass a state, or call getSuburbBySlug()'
    );
    e.code = 'AMBIGUOUS_SUBURB';
    e.slugs = hits.map(function (h) { return h.slug; });
    return e;
  }

  /**
   * Look the slug up in the search index. Needed because a handful of
   * localities share both name and postcode across a state border
   * (e.g. Texas 4385 is in both QLD and NSW), so their slugs carry a state
   * suffix that the name+postcode pair alone cannot reproduce.
   */
  function resolveSlug(suburb, postcode, state) {
    var want = slugify(suburb);
    return loadShard(want.charAt(0)).then(function (entries) {
      var hits = entries.filter(function (e) {
        return e.postcode === postcode &&
               slugify(e.name) === want &&
               (!state || e.state === state);
      });
      if (hits.length === 1) return hits[0].slug;
      if (hits.length === 0) return null;
      throw ambiguous(hits[0].name, postcode, hits);
    });
  }

  /**
   * Fetch one suburb's full record by name + postcode, with optional state.
   * Falls back to the search index when the name+postcode pair does not map
   * to a bare `<name>-<postcode>` slug.
   */
  function getSuburb(suburb, postcode, state) {
    if (!suburb || !postcode) {
      return Promise.reject(new Error('both suburb and postcode are required'));
    }
    postcode = String(postcode);
    var state_ = state ? String(state).toLowerCase() : '';
    var direct = slugify(suburb) + '-' + postcode + (state_ ? '-' + state_ : '');
    return getSuburbBySlug(direct).catch(function (err) {
      if (err && err.code === 'AMBIGUOUS_SUBURB') throw err;
      if (err && err.status && err.status !== 404) throw err;
      return resolveSlug(suburb, postcode, state).then(function (slug) {
        if (!slug) throw notFound(suburb, postcode);
        return getSuburbBySlug(slug);
      });
    });
  }

  /**
   * A locality's full neighbour list, nearest first.
   *
   * Every file holds the same fixed neighbourhood (however many hops the build
   * was configured with), so there is no hop filter to apply here — filter the
   * returned list yourself, on `km` or on whatever you care about. `state` is
   * only needed for the handful of cross-border name+postcode collisions.
   */
  function query(suburb, postcode, state) {
    return getSuburb(suburb, postcode, state).then(function (doc) {
      return {
        suburb: doc.suburb,
        postcode: doc.postcode,
        state: doc.state,
        centroid: doc.centroid,
        isolated: doc.isolated,
        truncated: doc.truncated,
        neighbours: doc.neighbours
      };
    });
  }

  /** Prefix search across the sharded index. */
  function search(term, limit) {
    term = String(term || '').toLowerCase().trim();
    if (!term) return Promise.resolve([]);
    var letter = slugify(term).charAt(0);
    var shards = letter ? [letter] : ALPHABET;
    return Promise.all(shards.map(function (l) {
      return json(BASE + '/api/index/' + l + '.json').catch(function () { return []; });
    })).then(function (lists) {
      var all = [].concat.apply([], lists);
      var starts = [], contains = [];
      all.forEach(function (e) {
        var n = e.name.toLowerCase();
        if (n.indexOf(term) === 0) starts.push(e);
        else if (n.indexOf(term) > -1) contains.push(e);
      });
      return starts.concat(contains).slice(0, limit || 25);
    });
  }

  /**
   * Breadth-first expansion over data/graph.json for hop counts beyond the
   * precomputed maximum.
   *
   * Note `km` here is measured from the START locality, not along the path.
   * Each edge in graph.json carries its own distance, so that value must not be
   * reused for deeper hops - it would report the distance of the last hop taken
   * instead of the distance to the suburb actually returned.
   */
  function bfs(graphDoc, startId, distance, meta) {
    var adj = graphDoc.adjacency;
    var metaMap = meta || null;
    var start = String(startId);
    var seen = {}, frontier = [start], result = [];

    seen[start] = true;
    for (var d = 1; d <= distance; d++) {
      var next = [];
      frontier.forEach(function (id) {
        (adj[id] || []).forEach(function (row) {
          var nid = String(row[0]);
          if (seen[nid]) return;
          seen[nid] = true;
          next.push(nid);

          var entry = { id: parseInt(nid, 10), hops: d, km: distanceFrom(start, nid, metaMap) };
          if (metaMap && metaMap[nid]) {
            entry.suburb = metaMap[nid].name;
            entry.postcode = metaMap[nid].postcode;
            entry.state = metaMap[nid].state;
            // Prefer the projected distance; fall back to the edge value only if
            // the dictionary is unavailable.
            if (entry.km == null) entry.km = row[1];
          } else {
            entry.km = row[1];
          }
          result.push(entry);
        });
      });
      frontier = next;
      if (!next.length) break;
    }
    // Same ordering as the precomputed api/ files: hops, then km, then name.
    result.sort(function (a, b) {
      return a.hops - b.hops || a.km - b.km ||
        String(a.suburb || '').localeCompare(String(b.suburb || ''));
    });
    return result;
  }

  /**
   * Centroid distance in km between two locality ids, matching the build's
   * EPSG:3577 (GDA2020 Australian Albers) measurement exactly. Returns null
   * when the dictionary lacks the projected coordinates.
   *
   * Prefers an explicitly supplied dictionary over the module-level one loaded
   * by loadGraph(), so bfs() measures against the meta it was actually handed.
   * Reading the cache unconditionally here would silently report the *edge*
   * distance (distance to the previous hop) whenever a caller passes its own
   * dictionary without going through loadGraph().
   */
  function distanceFrom(aId, bId, meta) {
    var m = meta && meta[aId] && meta[bId] ? meta : metaCache;
    var a = m && m[aId];
    var b = m && m[bId];
    if (!a || !b || a.cx == null || b.cx == null) return null;
    return round1(Math.sqrt(Math.pow(a.cx - b.cx, 2) + Math.pow(a.cy - b.cy, 2)) / 1000);
  }

  function round1(v) { return Math.round(v * 10) / 10; }

  /** Load the raw adjacency graph + dictionary for arbitrary-depth queries. */
  function loadGraph() {
    return Promise.all([
      json(BASE + '/data/graph.json'),
      json(BASE + '/data/suburbs.json')
    ]).then(function (r) {
      metaCache = r[1];
      return { graph: r[0], suburbs: r[1] };
    });
  }

  global.createClient = function (base) {
    if (base) BASE = base;
    return {
      query: query,
      getSuburb: getSuburb,
      getSuburbBySlug: getSuburbBySlug,
      search: search,
      bfs: bfs,
      loadGraph: loadGraph
    };
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      createClient: global.createClient,
      slugify: slugify,
      resolveSlug: resolveSlug,
      bfs: bfs
    };
  }
})(typeof window !== 'undefined' ? window : globalThis);
