/* Demo UI logic for the suburb neighbourhood API. */
(function () {
  'use strict';

  var api = createClient();
  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------ metadata
  fetch('_meta.json')
    .then(function (r) { return r.json(); })
    .then(function (m) {
      var pc = m.postcode_edition ? m.postcode_edition.label : 'unknown';
      $('stats').textContent =
        m.locality_count.toLocaleString() + ' localities  ·  ' +
        m.edge_count.toLocaleString() + ' connections  ·  ' +
        'max distance ' + m.max_distance + '  ·  ' +
        'postcodes: ' + pc + '  ·  built ' + (m.generated_at || '').slice(0, 10);
      $('attribution').textContent = m.attribution.suburbs + '. ' + m.attribution.postcodes + '.';
      if (m.centroid_fallback_count != null) {
        $('fallbackcount').textContent = m.centroid_fallback_count.toLocaleString();
      }
      if (m.isolated_count != null) {
        $('isolatedcount').textContent = m.isolated_count.toLocaleString();
      }
      document.querySelectorAll('#distance option').forEach(function (o) {
        if (Number(o.value) > m.max_distance) o.disabled = true;
      });
    })
    .catch(function () {
      $('stats').textContent = 'metadata unavailable';
      $('attribution').textContent =
        'Administrative Boundaries (Geoscape Localities) © Geoscape Australia, CC BY 4.0. ' +
        'Postal Areas © Commonwealth of Australia (ABS), CC BY 4.0.';
    });

  // ------------------------------------------------------------ search
  var t;
  $('suburb').addEventListener('input', function () {
    clearTimeout(t);
    var v = this.value.trim();
    if (v.length < 2) return;
    t = setTimeout(function () {
      api.search(v, 12).then(function (rows) {
        $('suggestions').innerHTML = rows.map(function (r) {
          return '<option value="' + r.name + '">' +
            (r.postcode || '—') + ' ' + r.state + '</option>';
        }).join('');
      }).catch(function () { /* index shard may not exist yet */ });
    }, 180);
  });

  // Auto-fill the postcode when a suggestion is picked.
  $('suburb').addEventListener('change', function () {
    var name = this.value.trim();
    if (!name) return;
    api.search(name, 12).then(function (rows) {
      var exact = rows.filter(function (r) {
        return r.name.toLowerCase() === name.toLowerCase();
      });
      if (exact.length && !$('postcode').value) {
        $('postcode').value = exact[0].postcode || '';
      }
    }).catch(function () {});
  });

  // ------------------------------------------------------------ query
  function fail(msg) {
    $('error').textContent = msg;
    $('error').hidden = false;
    $('result').hidden = true;
  }

  $('form').addEventListener('submit', function (e) {
    e.preventDefault();
    $('error').hidden = true;

    var suburb = $('suburb').value.trim();
    var postcode = $('postcode').value.trim();
    var distance = Number($('distance').value);

    api.query(suburb, postcode, distance).then(function (r) {
      $('result').hidden = false;
      $('result-title').textContent = r.suburb + ' ' + (r.postcode || '');
      $('result-sub').textContent =
        r.state + '  ·  centroid ' + r.centroid.lat.toFixed(4) + ', ' + r.centroid.lon.toFixed(4) +
        ' (' + r.centroid.kind + ')  ·  within ' + distance + ' hop' + (distance > 1 ? 's' : '');

      var counts = {};
      r.neighbours.forEach(function (n) { counts[n.hops] = (counts[n.hops] || 0) + 1; });
      var pills = Object.keys(counts).sort().map(function (h) {
        return '<span class="pill">distance ' + h + ': ' + counts[h] + '</span>';
      }).join('');
      $('result-stats').innerHTML = pills +
        (r.truncated ? '<span class="pill warn">truncated</span>' : '');

      var body = $('result-table').querySelector('tbody');
      if (!r.neighbours.length) {
        body.innerHTML = '<tr><td colspan="5" class="muted">No connected suburbs found. ' +
          'This locality may be isolated (an island or remote area).</td></tr>';
        return;
      }
      body.innerHTML = r.neighbours.map(function (n) {
        return '<tr>' +
          '<td>' + esc(n.suburb) + '</td>' +
          '<td>' + esc(n.postcode || '—') + '</td>' +
          '<td>' + esc(n.state) + '</td>' +
          '<td class="num">' + n.hops + '</td>' +
          '<td class="num">' + n.km.toFixed(1) + '</td>' +
          '</tr>';
      }).join('');
    }).catch(function (err) {
      fail(/HTTP 404/.test(err.message)
        ? 'No suburb found matching "' + suburb + ' ' + postcode +
          '". Check the spelling, and note that both suburb and postcode must match exactly."
        : err.message);
    });
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
})();
