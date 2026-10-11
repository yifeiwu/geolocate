/**
 * neighbours.js - tiny client for the Australian suburb neighbourhood API.
 *
 * Works against the precomputed static JSON on GitHub Pages. No dependencies.
 *
 *   const api = createClient();
 *   const r = await api.query('Parramatta', '2150', 2);
 *   // r.neighbours -> [{suburb, postcode, state, hops, km}, ...]
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
      if (!r.ok) throw new Error('HTTP ' + r.status + ' for ' + url);
      return r.json();
    });
  }

  function slugify(text) {
    return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  /** Fetch one suburb's full record by name + postcode. */
  function getSuburb(suburb, postcode) {
    if (!suburb || !postcode) {
      return Promise.reject(new Error('both suburb and postcode are required'));
    }
    return json(BASE + '/api/n/' + slugify(suburb) + '-' + postcode + '.json');
  }

  /**
   * Neighbours within `distance` hops. Results are sorted by hops then km.
   * `distance` defaults to the maximum the file was built with.
   */
  function query(suburb, postcode, distance) {
    return getSuburb(suburb, postcode).then(function (doc) {
      var max = distance == null ? doc.max_distance : distance;
      if (max > doc.max_distance) {
        throw new Error(
          'this build supports distance 1-' + doc.max_distance +
          '; load data/graph.json and use bfs() for deeper queries'
        );
      }
      return {
        suburb: doc.suburb,
        postcode: doc.postcode,
        state: doc.state,
        centroid: doc.centroid,
        truncated: doc.truncated,
        maxDistance: doc.max_distance,
        neighbours: doc.neighbours.filter(function (n) { return n.hops <= max; })
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

          var entry = { id: parseInt(nid, 10), hops: d, km: distanceFrom(start, nid) };
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
    // Same ordering as the precomputed api/n files: hops, then km, then name.
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
   */
  function distanceFrom(aId, bId) {
    var a = metaCache && metaCache[aId];
    var b = metaCache && metaCache[bId];
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
      search: search,
      bfs: bfs,
      loadGraph: loadGraph
    };
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { createClient: global.createClient, slugify: slugify, bfs: bfs };
  }
})(typeof window !== 'undefined' ? window : globalThis);
