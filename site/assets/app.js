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
        'precomputed to ' + m.max_distance + ' hops  ·  ' +
        'postcodes: ' + pc + '  ·  built ' + (m.generated_at || '').slice(0, 10);
      $('attribution').textContent = m.attribution.suburbs + '. ' + m.attribution.postcodes + '.';
      if (m.centroid_fallback_count != null) {
        $('fallbackcount').textContent = m.centroid_fallback_count.toLocaleString();
      }
      if (m.isolated_count != null) {
        $('isolatedcount').textContent = m.isolated_count.toLocaleString();
      }
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
    var state = $('state').value.trim();
    var within = $('within').value.trim();

    api.query(suburb, postcode, state || undefined).then(function (r) {
      var all = r.neighbours;
      var shown = within === '' ? all : all.filter(function (n) { return n.km <= Number(within); });

      $('result').hidden = false;
      $('result-title').textContent = r.suburb + ' ' + (r.postcode || '');
      $('result-sub').textContent =
        r.state + '  ·  centroid ' + r.centroid.lat.toFixed(4) + ', ' + r.centroid.lon.toFixed(4) +
        ' (' + r.centroid.kind + ')';

      var pills = '<span class="pill">' + shown.length +
        (within === '' ? ' neighbours' : ' within ' + within + ' km') + '</span>';
      if (within !== '' && shown.length !== all.length) {
        pills += '<span class="pill">' + (all.length - shown.length) + ' beyond</span>';
      }
      if (r.truncated) pills += '<span class="pill warn">truncated</span>';
      $('result-stats').innerHTML = pills;

      var body = $('result-table').querySelector('tbody');
      if (!shown.length) {
        body.innerHTML = '<tr><td colspan="4" class="muted">' +
          (all.length ? 'No neighbours within ' + within + ' km.' :
           'No connected suburbs found. This locality may be isolated (an island or remote area).') +
          '</td></tr>';
        return;
      }
      body.innerHTML = shown.map(function (n) {
        return '<tr>' +
          '<td>' + esc(n.suburb) + '</td>' +
          '<td>' + esc(n.postcode || '—') + '</td>' +
          '<td>' + esc(n.state) + '</td>' +
          '<td class="num">' + n.km.toFixed(1) + '</td>' +
          '</tr>';
      }).join('');
    }).catch(function (err) {
      if (err.code === 'AMBIGUOUS_SUBURB') {
        fail('"' + suburb + ' ' + postcode + '" exists in more than one state (' +
          (err.slugs || []).join(' and ') + '). Enter the state to pick one.');
        return;
      }
      if (err.code === 'NOT_FOUND') {
        fail('No suburb found matching "' + suburb + ' ' + postcode +
          '". Both suburb and postcode must match exactly.');
        return;
      }
      fail(/HTTP 404/.test(err.message)
        ? 'No suburb found matching "' + suburb + ' ' + postcode +
          '". Check the spelling, and note that both suburb and postcode must match exactly.'
        : err.message);
    });
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
})();
