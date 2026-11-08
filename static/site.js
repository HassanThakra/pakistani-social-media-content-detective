/* Data Detective website: landing search + shareable result pages.
   Everything data-derived goes in with textContent / DOM calls, never innerHTML. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var fmt = Charts.fmt;

  /* ---------------------------------------------------------------- helpers */
  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) { for (var k in attrs) { if (k === 'class') { e.className = attrs[k]; } else if (attrs[k] != null) { e.setAttribute(k, attrs[k]); } } }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) { continue; }
      e.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function clear(n) { n.replaceChildren(); }
  function show(n, on) { n.hidden = !on; }
  function pct(v, d) { return (v * 100).toFixed(d == null ? 0 : d) + '%'; }
  function fmtSec(v) { if (v >= 1) { return (+v.toFixed(2)) + ' s'; } var ms = v * 1000; return (+ms.toFixed(ms < 10 ? 1 : 0)) + ' ms'; }
  function fmtRows(v) { if (v >= 1e6) { return (+(v / 1e6).toFixed(2)) + 'M'; } if (v >= 1e3) { return (+(v / 1e3).toFixed(1)) + 'k'; } return String(v); }
  function callout(cls, text) { return h('div', { 'class': 'callout ' + cls }, text); }
  function tile(v, l) { return h('div', { 'class': 'tile' }, h('div', { 'class': 'v' }, v), h('div', { 'class': 'l' }, l)); }
  function table(cols, rows, caption) {
    var head = h('tr', null);
    cols.forEach(function (c) { head.appendChild(h('th', { 'class': c.num ? 'num' : '', scope: 'col' }, c.label)); });
    var body = h('tbody', null);
    rows.forEach(function (r) {
      var tr = h('tr', null);
      cols.forEach(function (c) {
        var v = c.cell ? c.cell(r) : r[c.key];
        var td = h('td', { 'class': c.num ? 'num' : '' });
        if (v && v.nodeType) { td.appendChild(v); } else if (v != null) { td.textContent = c.fmt ? c.fmt(v) : String(v); }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    return h('div', { 'class': 'table-wrap', tabindex: '0', role: 'region', 'aria-label': caption || 'Table' },
      h('table', null, h('thead', null, head), body));
  }
  var N = function (v) { return fmt(v); };

  function api(path, opts) {
    return fetch(path, opts || {}).then(function (resp) {
      return resp.json().catch(function () { return null; }).then(function (data) {
        if (!resp.ok) {
          var e = new Error((data && data.error) || ('The server returned an error (' + resp.status + ').'));
          e.status = resp.status; e.quota = !!(data && data.quota);
          throw e;
        }
        return data;
      });
    }, function () { var e = new Error('Could not reach the server. Check your connection and try again.'); e.status = 0; throw e; });
  }
  function postJSON(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  /* ---------------------------------------------------------------- theme + tooltip */
  var THEMES = ['auto', 'light', 'dark'], theme = 'auto';
  function applyTheme(t) {
    if (t === 'light' || t === 'dark') { document.documentElement.setAttribute('data-theme', t); } else { document.documentElement.removeAttribute('data-theme'); }
    $('#theme-btn').textContent = 'Theme: ' + t;
  }
  try { theme = localStorage.getItem('dd_theme') || 'auto'; } catch (e) { /* ignore */ }
  if (THEMES.indexOf(theme) < 0) { theme = 'auto'; }
  applyTheme(theme);
  $('#theme-btn').addEventListener('click', function () {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]; applyTheme(theme);
    try { localStorage.setItem('dd_theme', theme); } catch (e) { /* ignore */ }
  });

  var tipEl = $('#tip');
  function placeTip(x, y) {
    var w = tipEl.offsetWidth, hh = tipEl.offsetHeight, left = Math.min(x + 14, window.innerWidth - w - 8), top = y + 16;
    if (top + hh > window.innerHeight - 8) { top = y - hh - 12; }
    tipEl.style.left = Math.max(8, left) + 'px'; tipEl.style.top = Math.max(8, top) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) { return; }
    tipEl.textContent = t.getAttribute('data-tip'); tipEl.hidden = false; placeTip(e.clientX, e.clientY);
  });
  document.addEventListener('mousemove', function (e) { if (!tipEl.hidden) { placeTip(e.clientX, e.clientY); } });
  document.addEventListener('mouseout', function (e) { if (e.target.closest && e.target.closest('[data-tip]')) { tipEl.hidden = true; } });
  document.addEventListener('focusin', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) { return; }
    tipEl.textContent = t.getAttribute('data-tip'); tipEl.hidden = false;
    var r = t.getBoundingClientRect(); placeTip(r.left + r.width / 2, r.top);
  });
  document.addEventListener('focusout', function () { tipEl.hidden = true; });

  /* ================================================================ LANDING */
  function initLanding() {
    var form = $('#search-form'), q = $('#q'), go = $('#go'), status = $('#status'), err = $('#search-error'), cand = $('#candidates');
    var nsel = $('#nvideos');
    function busy(on, msg) { go.disabled = on; q.readOnly = on; status.textContent = on ? msg : (msg || ''); }
    function fail(e) {
      busy(false, '');
      err.textContent = e.message; show(err, true);
    }
    api('/api/config').then(function (c) {
      if (!c.youtube_enabled) { show($('#disabled-note'), true); go.disabled = true; q.disabled = true; }
      $$('option', nsel).forEach(function (o) { if (parseInt(o.value, 10) > c.max_videos) { o.remove(); } });
    }).catch(function () { /* defaults are fine */ });

    function analyze(query) {
      var n = parseInt(nsel.value, 10) || 200;
      busy(true, 'Fetching up to ' + n + ' videos from YouTube. This usually takes 5 to 20 seconds…');
      return postJSON('/api/youtube/analyze', { kind: query.kind, value: query.value, max_videos: n }).then(function (r) {
        status.textContent = 'Done. Opening your analysis of ' + r.channel + '…';
        window.location.href = r.url;
      }).catch(fail);
    }
    function showCandidates(list, note) {
      clear(cand);
      cand.appendChild(h('p', { 'class': 'muted' }, note));
      list.forEach(function (c) {
        var b = h('button', { type: 'button', 'class': 'candidate' }, h('strong', null, c.title || c.channel_id), h('span', null, c.description || 'No description'));
        b.addEventListener('click', function () { show(cand, false); analyze({ kind: 'id', value: c.channel_id }); });
        cand.appendChild(b);
      });
      show(cand, true);
    }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      show(err, false); show(cand, false);
      var text = q.value.trim();
      if (!text) { fail(new Error('Type a YouTube channel (link, @handle or ID) or a brand name.')); return; }
      busy(true, 'Checking what you typed…');
      postJSON('/api/youtube/resolve', { query: text }).then(function (r) {
        if (r.mode === 'direct') { return analyze(r.query); }
        busy(false, 'Choose the channel that belongs to the brand.');
        showCandidates(r.candidates, r.note);
        var first = $('.candidate', cand); if (first) { first.focus(); }
      }).catch(fail);
    });
  }

  /* ================================================================ RESULTS */
  function initResults() {
    var root = $('#results-root'), aid = root.getAttribute('data-aid');
    var view = $('#view'), main = $('#main');
    var overview = null, current = null, seq = 0;
    var LABELS = { overview: 'Overview', cleaned: 'Cleaned data', explore: 'Explore', sentiment: 'Sentiment', meaning: 'What it means', scaling: 'Scaling', models: 'Models', report: 'Report' };
    var ORDER = ['overview', 'cleaned', 'explore', 'sentiment', 'meaning', 'scaling', 'models', 'report'];

    function base() { return '/api/analysis/' + aid + '/'; }
    function sectionFromPath() {
      var m = location.pathname.match(/\/analysis\/[^/]+\/?([a-z]*)/);
      return m && LABELS[m[1]] ? m[1] : 'overview';
    }
    function expired(e) {
      clear(view);
      view.appendChild(h('h2', null, e.status === 410 ? 'This result has expired' : 'Something went wrong'));
      view.appendChild(callout(e.status === 410 ? 'warn' : 'bad', e.message));
      view.appendChild(h('p', null, h('a', { 'class': 'btn primary', href: '/' }, 'Start a new analysis')));
      $('#snapshot-text').textContent = e.status === 410 ? 'This result is no longer available.' : 'This result could not be loaded.';
    }
    function nextLink(sec, text) {
      var a = h('a', { 'class': 'btn primary', href: '/analysis/' + aid + '/' + sec, 'data-section': sec }, text);
      a.addEventListener('click', function (e) { e.preventDefault(); go(sec, true); });
      return h('p', { 'class': 'actions' }, a);
    }
    function head(sec, title, intro) {
      clear(view);
      view.appendChild(h('h2', null, title));
      if (intro) { view.appendChild(h('p', { 'class': 'page-intro' }, intro)); }
    }

    function loadOverview() {
      if (overview) { return Promise.resolve(overview); }
      return api(base() + 'overview').then(function (o) {
        overview = o;
        var s = o.snapshot, t = $('#snapshot-text'); clear(t);
        t.appendChild(h('strong', null, o.channel.title));
        t.appendChild(document.createTextNode('  fetched ' + s.fetched_at_utc + ', ' + fmt(s.videos_fetched) + ' videos, '
          + s.api_units_used + ' API units. '));
        t.appendChild(h('span', { 'class': 'exp' }, 'This link works for about ' + Math.max(1, Math.round(o.expires_in_minutes / 60 * 10) / 10) + ' more hours.'));
        return o;
      });
    }

    /* ---------- overview */
    function renderOverview(o) {
      var v = o.overview, ch = o.channel, s = o.snapshot;
      head('overview', ch.title, 'One row is one public video. This page summarises the latest ' + fmt(v.videos) + ' videos fetched from YouTube on ' + s.fetched_at_utc + '.');
      var tiles = h('div', { 'class': 'tiles' },
        tile(N(v.videos), 'videos analysed'), tile(N(v.median_views), 'median views'), tile(N(v.mean_views), 'mean views'),
        tile(ch.subscribers_hidden ? 'hidden' : N(ch.subscribers), 'subscribers'),
        tile(N(v.likes_hidden), 'videos with likes hidden'), tile(N(v.comments_off), 'videos with comments off'),
        tile(v.median_duration_min == null ? '–' : fmt(v.median_duration_min, 1) + ' min', 'median length'));
      view.appendChild(tiles);
      view.appendChild(h('p', { 'class': 'muted' }, 'Published ' + v.first_published + ' to ' + v.last_published
        + (ch.video_count && ch.video_count > v.videos ? '. The channel lists ' + fmt(ch.video_count) + ' public videos; this is the latest ' + fmt(v.videos) + '.' : '.')));
      if (!v.enough_for_comparisons) {
        view.appendChild(callout('warn', 'Only ' + v.videos + ' videos were found. That is too few to compare groups, so treat everything here as description, not evidence.'));
      } else if (!v.enough_for_models) {
        view.appendChild(callout('warn', 'With ' + v.videos + ' videos the comparisons work, but the model previews need at least 40 and will stay off.'));
      }
      if (v.likes_hidden || v.comments_off) {
        view.appendChild(callout('blue', 'Hidden likes and switched-off comments are missing, not zero. Any average that needs them leaves those videos out.'));
      }
      view.appendChild(h('h3', null, 'Most viewed videos'));
      view.appendChild(table([
        { label: 'Title', cell: function (r) { return h('a', { href: 'https://www.youtube.com/watch?v=' + encodeURIComponent(r.video_id), target: '_blank', rel: 'noopener noreferrer', 'class': 'vid-title' }, r.title || '(untitled)'); } },
        { label: 'Views', key: 'views', num: true, fmt: N }, { label: 'Published', key: 'published' }
      ], v.top_videos, 'Ten most viewed videos, linked to YouTube'));
      view.appendChild(nextLink('cleaned', 'Next: see how the data was cleaned'));
    }

    /* ---------- cleaned */
    function renderCleaned(c) {
      var r = c.report;
      head('cleaned', 'Cleaned data', 'The cleaning is done on a copy. Every step is listed, and hidden counts stay blank rather than becoming zero.');
      var neg = Object.keys(r.negatives_to_missing).reduce(function (a, k) { return a + r.negatives_to_missing[k]; }, 0);
      view.appendChild(h('div', { 'class': 'tiles' }, tile(N(r.rows_before) + ' → ' + N(r.rows_after), 'rows, before → after'),
        tile(N(r.duplicates_removed), 'repeated videos removed'), tile(N(neg), 'impossible values set to missing'), tile(N(r.derived.length), 'measures added')));
      var ol = h('ol', { 'class': 'steps' });
      r.steps.forEach(function (s) { ol.appendChild(h('li', null, h('span', { 'class': 't' }, s.title + '. '), s.detail)); });
      view.appendChild(ol);
      view.appendChild(callout('warn', r.note));
      if (c.issues.length) {
        view.appendChild(h('h3', null, 'Things noticed in the fetched data'));
        var ul = h('ul', { 'class': 'issues' });
        c.issues.forEach(function (i) { ul.appendChild(h('li', null, h('span', { 'class': 'col' }, i.column + ': '), i.text)); });
        view.appendChild(ul);
      }
      var miss = Object.keys(r.missing_after).map(function (k) { return { column: k, n: r.missing_after[k], share: r.missing_after[k] / r.rows_after }; })
        .sort(function (a, b) { return b.n - a.n; });
      view.appendChild(h('h3', null, 'Blank values left in the cleaned copy'));
      view.appendChild(miss.length ? table([{ label: 'Column', key: 'column' }, { label: 'Blank', key: 'n', num: true, fmt: N }, { label: 'Share of videos', key: 'share', num: true, fmt: function (v) { return pct(v, 1); } }], miss, 'Blank values')
        : h('p', { 'class': 'muted' }, 'No blank values remain.'));
      view.appendChild(h('h3', null, 'Columns'));
      view.appendChild(table([{ label: 'Column', key: 'name' }, { label: 'Stored as', key: 'stored_as' }, { label: 'Looks like', key: 'kind' },
        { label: 'Blank', key: 'missing', num: true, fmt: N }, { label: 'Distinct', key: 'distinct', num: true, fmt: N }, { label: 'Example', key: 'example' }], c.columns, 'Columns in the fetched data'));
      var keys = ['video_id', 'published_at', 'title', 'view_count', 'like_count', 'comment_count', 'duration_seconds', 'format'];
      view.appendChild(h('h3', null, 'First rows after cleaning'));
      view.appendChild(table(keys.map(function (k) { return { label: k, key: k }; }), c.head, 'First rows of the cleaned data'));
      view.appendChild(nextLink('explore', 'Next: explore the data'));
    }

    /* ---------- explore */
    function renderExplore() {
      head('explore', 'Explore', 'Pick what to compare. Group sizes sit next to every number, and groups with too few videos are flagged.');
      var controls = h('div', { 'class': 'controls' });
      var out = h('div', null), errBox = h('p', { 'class': 'error', role: 'alert', hidden: '' });
      var els = {};
      function sel(id, label) { els[id] = h('select', { id: 'x-' + id }); return h('label', null, label, els[id]); }
      controls.append(sel('group', 'Compare groups of'), sel('metric', 'Measured by'), sel('x', 'Scatter X'), sel('y', 'Scatter Y'));
      els.min = h('input', { type: 'number', id: 'x-min', value: '10', min: '1', max: '100000' });
      controls.appendChild(h('label', null, 'Minimum videos per group', els.min));
      view.append(controls, errBox, out);
      var mine = ++seq, timer = null, first = true;

      function fill(sel, vals, chosen) {
        clear(sel);
        vals.forEach(function (v) { sel.appendChild(h('option', { value: v }, v)); });
        if (chosen && vals.indexOf(chosen) >= 0) { sel.value = chosen; }
      }
      function run() {
        var qs = first ? '' : '?' + ['group_col=' + els.group.value, 'metric=' + els.metric.value, 'x=' + els.x.value, 'y=' + els.y.value, 'min_videos=' + els.min.value]
          .map(function (p) { var i = p.indexOf('='); return p.slice(0, i + 1) + encodeURIComponent(p.slice(i + 1)); }).join('&');
        var token = ++seq;
        return api(base() + 'explore' + qs).then(function (r) {
          if (token !== seq) { return; }
          errBox.hidden = true;
          if (first) {
            first = false;
            fill(els.group, r.options.groups, r.selected.group_col); fill(els.metric, r.options.metrics, r.selected.metric);
            fill(els.x, r.options.metrics, r.selected.x); fill(els.y, r.options.metrics, r.selected.y);
          }
          drawExplore(out, r);
        }).catch(function (e) { if (e.status === 410) { expired(e); } else { errBox.textContent = e.message; errBox.hidden = false; } });
      }
      ['group', 'metric', 'x', 'y'].forEach(function (k) { els[k].addEventListener('change', run); });
      els.min.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(run, 400); });
      run().then(function () { out.appendChild(nextLink('meaning', 'Next: what it means')); });
    }
    function drawExplore(out, r) {
      clear(out);
      var g = r.group, sel = { group: g.group_col, metric: g.metric };
      out.appendChild(h('p', { 'class': 'muted' }, 'Looking at ' + N(r.rows_used) + ' videos.'));
      r.warnings.forEach(function (w) { out.appendChild(callout('warn', w)); });
      out.appendChild(h('h3', null, 'Median ' + sel.metric + ' by ' + sel.group));
      var cg = h('div', { 'class': 'chart' }); out.appendChild(cg);
      Charts.bar(cg, { noun: 'videos', aria: 'Bar chart of median ' + sel.metric + ' for each ' + sel.group + '. The table below has the same numbers.',
        yLabel: 'Median ' + sel.metric, xLabel: sel.group + '  (n = videos with a value)',
        items: g.rows.map(function (x) { return { label: x.group, value: x.median, n: x.posts, few: x.too_few,
          tip: x.group + ': median ' + fmt(x.median) + ', mean ' + fmt(x.mean) + ', ' + fmt(x.posts) + ' videos' + (x.too_few ? ' (few videos)' : '') }; }) });
      out.appendChild(table([{ label: sel.group, key: 'group' }, { label: 'Videos', key: 'posts', num: true, fmt: N },
        { label: 'Median', key: 'median', num: true, fmt: function (v) { return fmt(v, 1); } }, { label: 'Mean', key: 'mean', num: true, fmt: function (v) { return fmt(v, 1); } },
        { label: 'Group size', cell: function (x) { return x.too_few ? h('span', { 'class': 'badge few' }, 'few videos') : h('span', { 'class': 'badge' }, 'ok'); } }],
        g.rows, 'Median and mean ' + sel.metric + ' by ' + sel.group));
      if (g.excluded_missing_group) { out.appendChild(h('p', { 'class': 'muted' }, N(g.excluded_missing_group) + ' videos have no ' + sel.group + ' value and are left out.')); }
      var d = r.dist;
      out.appendChild(h('h3', null, 'How ' + sel.metric + ' is spread out'));
      var cd = h('div', { 'class': 'chart' }); out.appendChild(cd);
      if (d.n) {
        Charts.hist(cd, { edges: d.edges, counts: d.counts, median: d.median, xLabel: sel.metric, yLabel: 'Number of videos', aria: 'Histogram of ' + sel.metric });
        var f = N(d.n) + ' values. Mean ' + fmt(d.mean, 1) + ', median ' + fmt(d.median, 1) + ', range ' + fmt(d.min) + ' to ' + fmt(d.max) + '.';
        if (r.top_share) { f += ' The top 10% of videos (' + N(r.top_share.top_n) + ' of ' + N(r.top_share.of) + ') hold ' + pct(r.top_share.share) + ' of the total.'; }
        out.appendChild(h('p', { 'class': 'muted' }, f));
      } else { cd.textContent = 'No values to show.'; }
      var sc = r.scatter;
      if (sc && sc.points.length) {
        out.appendChild(h('h3', null, 'Is ' + sc.y + ' related to ' + sc.x + '?'));
        var cs = h('div', { 'class': 'chart' }); out.appendChild(cs);
        Charts.scatter(cs, { points: sc.points, xLabel: sc.x, yLabel: sc.y, xName: sc.x, yName: sc.y, aria: 'Scatter plot of ' + sc.y + ' against ' + sc.x });
        var t = '';
        if (sc.spearman != null) { var a = Math.abs(sc.spearman); t = 'Spearman correlation ' + sc.spearman.toFixed(2) + ' (' + (a < 0.3 ? 'weak' : a < 0.6 ? 'moderate' : 'strong') + ', ' + (sc.spearman >= 0 ? 'positive' : 'negative') + ') across ' + N(sc.n) + ' videos. Correlation is not causation.'; }
        out.appendChild(h('p', { 'class': 'muted' }, t));
      }
      if (r.weekday) {
        out.appendChild(h('h3', null, 'Median ' + sel.metric + ' by day of week (UTC)'));
        var cw = h('div', { 'class': 'chart' }); out.appendChild(cw);
        Charts.bar(cw, { noun: 'videos', aria: 'Bar chart of median ' + sel.metric + ' by day of week', yLabel: 'Median ' + sel.metric,
          items: r.weekday.rows.map(function (x) { return { label: x.day.slice(0, 3), value: x.median || 0, n: x.posts, few: x.posts < 30,
            tip: x.day + ': median ' + fmt(x.median) + ', ' + fmt(x.posts) + ' videos' }; }) });
      }
    }

    /* ---------- meaning */
    function renderMeaning(m) {
      head('meaning', 'What it means', 'Each pattern is written as Finding, Evidence, Action and Limitation from the numbers in this fetch. Yellow marks mean the evidence is thin.');
      var box = h('div', { 'class': 'findings' });
      m.cards.forEach(function (c) {
        var weak = c.strength === 'weak';
        box.appendChild(h('article', { 'class': 'finding' + (weak ? ' weak' : '') },
          h('h3', null, c.title, weak ? h('span', { 'class': 'flag' }, 'thin evidence') : null),
          h('dl', null, h('dt', null, 'Finding'), h('dd', null, c.finding), h('dt', null, 'Evidence'), h('dd', null, c.evidence),
            h('dt', null, 'Action'), h('dd', null, c.action), h('dt', null, 'Limitation'), h('dd', null, c.limitation))));
      });
      view.appendChild(box);
      var ul = h('ul', null); m.always.forEach(function (t) { ul.appendChild(h('li', null, t)); });
      view.appendChild(h('h3', null, 'Always keep in mind')); view.appendChild(ul);
      view.appendChild(nextLink('scaling', 'Next: the scaling experiment'));
    }


    /* ---------- sentiment (stage B) */
    function renderSentiment() {
      head('sentiment', 'Sentiment', 'What do people say in the comments? Comments are collected from YouTube when you ask, scored as positive, neutral or negative, and summarised. No author names are kept.');
      view.appendChild(callout('warn', 'Sentiment scoring is an estimate. It cannot read sarcasm and it can miss spellings it has not seen, especially in Roman Urdu. Treat the numbers as a direction, not a measurement.'));
      var st = h('span', { 'class': 'muted', role: 'status' }), err = h('p', { 'class': 'error', role: 'alert', hidden: '' });
      var out = h('div', { 'class': 'sent-out' });
      function opt(v, t, sel) { return h('option', Object.assign({ value: v }, sel ? { selected: '' } : {}), t); }
      function field(label, node, hint) { return h('label', { 'class': 'sf' }, h('span', { 'class': 't' }, label), node, hint ? h('span', { 'class': 'muted' }, hint) : null); }
      var src = h('select', { id: 's-source' }, opt('both', 'Both, kept apart', true), opt('own', 'The brand’s own videos'), opt('public', 'Other people’s videos that mention the brand'));
      var dFrom = h('input', { type: 'date', id: 's-from' }), dTo = h('input', { type: 'date', id: 's-to' });
      var nVid = h('select', { id: 's-videos' }, opt('10', '10 videos'), opt('20', '20 videos', true), opt('30', '30 videos'), opt('50', '50 videos'));
      var nCom = h('select', { id: 's-comments' }, opt('100', '100 comments'), opt('200', '200 comments', true), opt('500', '500 comments'));
      var alias = h('input', { type: 'text', id: 's-alias', maxlength: '120', placeholder: 'for example: khadi, khaadi pk' });
      var btn = h('button', { 'class': 'btn primary', type: 'button' }, 'Collect and score comments');
      view.appendChild(h('section', { 'class': 'card sent-form' },
        h('h3', null, 'Where should the comments come from?'),
        h('div', { 'class': 'sent-grid' }, field('Source', src), field('Comments written from', dFrom), field('Comments written to', dTo),
          field('Videos to use', nVid), field('Comments per video', nCom), field('Other names for the brand', alias, 'Used to find other people’s videos.')),
        h('p', { 'class': 'muted' }, 'Collecting uses YouTube quota that every visitor shares (roughly 50 to 250 units; the full allowance is 10,000 a day). Choosing dates or filters afterwards costs nothing.'),
        h('p', null, btn, ' ', st)));
      view.append(err, out);
      view.appendChild(nextLink('meaning', 'Next: what it means'));

      function fail(e) { btn.disabled = false; st.textContent = ''; if (e.status === 410) { expired(e); } else { err.textContent = e.message; err.hidden = false; } }
      btn.addEventListener('click', function () {
        err.hidden = true; btn.disabled = true; st.textContent = 'Fetching and scoring comments. This can take up to a minute…';
        postJSON(base() + 'sentiment/collect', { source: src.value, date_from: dFrom.value, date_to: dTo.value, max_videos: +nVid.value,
          max_comments: +nCom.value, aliases: alias.value }).then(function (r) { btn.disabled = false; st.textContent = ''; drawSentiment(r); }).catch(fail);
      });
      return api(base() + 'sentiment').then(function (r) { if (r.collected) { drawSentiment(r); } }).catch(function (e) { if (e.status === 410) { expired(e); } else { err.textContent = e.message; err.hidden = false; } });

      function drawSentiment(r) {
        clear(out);
        var c = r.collection;
        out.appendChild(h('p', { 'class': 'muted' }, 'Collected ' + r.snapshot.fetched_at_utc + ' from ' + fmt(c.videos_used || 0) + ' videos'
          + (c.videos_comments_disabled ? ' (' + c.videos_comments_disabled + ' had comments turned off)' : '') + '. ' + fmt(c.fetched || 0) + ' comments fetched, '
          + fmt(c.kept || 0) + ' kept after removing duplicates, spam, links and other languages. ' + r.scoring.note + ' '
          + (r.scoring.measured ? 'Checked on ' + fmt(r.scoring.measured.n) + ' comments labelled by a person: ' + pct(r.scoring.measured.accuracy) + ' agreed (always guessing the most common label would score ' + pct(r.scoring.measured.baseline) + ').'
            : 'Its accuracy has not been measured for this site yet.')));
        if (!r.available.sources.length) {
          out.appendChild(callout('warn', 'No usable comments were found for these choices. Try both sources, a wider date range, or more videos.'));
          return;
        }
        var f = r.filters, fb = h('div', { 'class': 'card sent-filters' }, h('h3', null, 'Narrow what is shown'));
        var fl = h('select', { id: 'f-lang' }, opt('', 'All languages', !f.language), opt('english', 'English', f.language === 'english'), opt('roman_urdu', 'Roman Urdu', f.language === 'roman_urdu'));
        var fs = h('select', { id: 'f-src' }, opt('', 'All sources', !f.source), opt('own', 'Own videos', f.source === 'own'), opt('public', 'Other people’s videos', f.source === 'public'));
        var ff = h('input', { type: 'date', id: 'f-from', value: f.date_from || '', min: r.available.first, max: r.available.last });
        var ft = h('input', { type: 'date', id: 'f-to', value: f.date_to || '', min: r.available.first, max: r.available.last });
        fb.appendChild(h('div', { 'class': 'sent-grid' }, field('Language', fl), field('Source', fs), field('From', ff), field('To', ft)));
        out.appendChild(fb);
        var body = h('div', { 'class': 'sent-body', 'aria-live': 'polite' });
        out.appendChild(body);
        function refilter() {
          var q = ['language=' + fl.value, 'source=' + fs.value, 'date_from=' + ff.value, 'date_to=' + ft.value].join('&');
          api(base() + 'sentiment?' + q).then(function (n) { n.available = r.available; body.replaceChildren(sentBody(n.summary, n.filters)); }).catch(function (e) { err.textContent = e.message; err.hidden = false; });
        }
        [fl, fs, ff, ft].forEach(function (x) { x.addEventListener('change', refilter); });
        body.appendChild(sentBody(r.summary, r.filters));
      }
    }
    function sentBody(sm) {
      var box = h('div', null);
      if (!sm.n) { box.appendChild(callout('warn', 'No comments match these filters. Widen the dates or choose “All”.')); return box; }
      var o = sm.overall;
      box.appendChild(h('div', { 'class': 'tiles' }, tile(N(sm.n), 'comments scored'), tile(pct(o.positive), 'positive'), tile(pct(o.neutral), 'neutral'),
        tile(pct(o.negative), 'negative'), tile((o.net >= 0 ? '+' : '') + Math.round(o.net * 100), 'net points (positive minus negative)')));
      sm.warnings.forEach(function (w) { box.appendChild(callout('warn', w)); });
      var c1 = h('div', { 'class': 'chart', role: 'img', 'aria-label': 'Share of comments by sentiment' });
      box.appendChild(h('h3', null, 'Share of comments')); box.appendChild(c1);
      Charts.bar(c1, { aria: 'Bar chart of positive, neutral and negative comment shares', yLabel: 'Share of comments', tickFmt: function (v) { return pct(v); }, valFmt: function (v) { return pct(v); }, noun: 'comments',
        items: [{ label: 'Positive', value: o.positive, n: Math.round(o.positive * sm.n) }, { label: 'Neutral', value: o.neutral, n: Math.round(o.neutral * sm.n) }, { label: 'Negative', value: o.negative, n: Math.round(o.negative * sm.n) }] });
      var cols = function (first) { return [{ label: first, key: 'group' }, { label: 'Comments', key: 'n', num: true, fmt: N },
        { label: 'Positive', key: 'positive', num: true, fmt: function (v) { return pct(v); } }, { label: 'Neutral', key: 'neutral', num: true, fmt: function (v) { return pct(v); } },
        { label: 'Negative', key: 'negative', num: true, fmt: function (v) { return pct(v); } },
        { label: 'Size', cell: function (x) { return x.few ? h('span', { 'class': 'badge few' }, 'few comments') : h('span', { 'class': 'badge' }, 'ok'); } }]; };
      var nice = { own: 'Own videos', public: 'Other people’s videos', english: 'English', roman_urdu: 'Roman Urdu' };
      var lab = function (rows) { return rows.map(function (x) { return Object.assign({}, x, { group: nice[x.group] || x.group }); }); };
      if (sm.by_source.length > 1) { box.appendChild(h('h3', null, 'By source')); box.appendChild(table(cols('Source'), lab(sm.by_source), 'Sentiment by source')); }
      if (sm.by_language.length > 1) { box.appendChild(h('h3', null, 'By language')); box.appendChild(table(cols('Language'), lab(sm.by_language), 'Sentiment by language')); }
      var pts = sm.trend.filter(function (t) { return !t.few; });
      box.appendChild(h('h3', null, 'Over time (by ' + sm.trend[0].unit + ')'));
      if (pts.length >= 3) {
        var c2 = h('div', { 'class': 'chart', role: 'img', 'aria-label': 'Positive and negative share over time' }); box.appendChild(c2);
        var day = function (t) { return Date.parse(t.period) / 86400000; };
        var xf = function (v) { return new Date(v * 86400000).toISOString().slice(0, sm.trend[0].unit === 'month' ? 7 : 10); };
        Charts.line(c2, { aria: 'Line chart of positive and negative comment shares over time', xLabel: sm.trend[0].unit === 'month' ? 'Month' : 'Week starting', yLabel: 'Share of comments',
          xFmt: xf, xTip: xf, yFmt: function (v) { return pct(v); },
          series: [{ name: 'Positive', points: pts.map(function (t) { return { x: day(t), y: t.positive }; }) }, { name: 'Negative', points: pts.map(function (t) { return { x: day(t), y: t.negative }; }) }] });
        box.appendChild(h('p', { 'class': 'muted' }, 'Periods with fewer than 10 comments are left out because their shares jump around.'));
      } else { box.appendChild(h('p', { 'class': 'muted' }, 'Too few comments in each period to draw a trend. Collect more videos or comments per video.')); }
      if (sm.topics.length) {
        box.appendChild(h('h3', null, 'What people mention'));
        box.appendChild(table([{ label: 'Topic', key: 'topic' }, { label: 'Comments', key: 'n', num: true, fmt: N }, { label: 'Positive', key: 'positive', num: true, fmt: function (v) { return pct(v); } },
          { label: 'Negative', key: 'negative', num: true, fmt: function (v) { return pct(v); } }, { label: 'Net points', key: 'net', num: true, fmt: function (v) { return (v >= 0 ? '+' : '') + Math.round(v * 100); } },
          { label: 'Size', cell: function (x) { return x.few ? h('span', { 'class': 'badge few' }, 'few comments') : h('span', { 'class': 'badge' }, 'ok'); } }], sm.topics, 'Topics mentioned in comments'));
        box.appendChild(h('p', { 'class': 'muted' }, 'Topics come from a fixed list of neutral keywords (price, quality, delivery, design, size, stores). One comment can count for several topics. The sentiment is that of the whole comment, and comments that use other words for a topic, such as “expensive”, are not counted here.'));
      }
      box.appendChild(h('h3', null, 'Videos with the most comments'));
      box.appendChild(table([{ label: 'Video', cell: function (x) { return h('a', { href: 'https://www.youtube.com/watch?v=' + encodeURIComponent(x.video_id), target: '_blank', rel: 'noopener noreferrer', 'class': 'vid-title' }, x.title || '(untitled)'); } },
        { label: 'Comments', key: 'n', num: true, fmt: N }, { label: 'Positive', key: 'positive', num: true, fmt: function (v) { return pct(v); } }, { label: 'Negative', key: 'negative', num: true, fmt: function (v) { return pct(v); } }], sm.by_video, 'Sentiment by video'));
      function quotes(title, list) {
        var ul = h('ul', { 'class': 'quotes' });
        list.forEach(function (q) { ul.appendChild(h('li', null, h('q', null, q.text), h('span', { 'class': 'muted' }, ' ' + (q.likes != null ? q.likes + ' likes, ' : '') + q.date + ', ' + (q.source === 'own' ? 'own video' : 'other video')))); });
        return h('div', { 'class': 'card' }, h('h4', null, title), list.length ? ul : h('p', { 'class': 'muted' }, 'None in this selection.'));
      }
      box.appendChild(h('h3', null, 'Example comments'));
      box.appendChild(h('div', { 'class': 'sent-quotes' }, quotes('Most-liked positive', sm.examples.positive), quotes('Most-liked negative', sm.examples.negative)));
      box.appendChild(h('p', { 'class': 'muted' }, 'Comments are shown without names. They are public on YouTube; this page keeps them in memory only until the result expires.'));
      return box;
    }

    /* ---------- scaling */
    function renderScaling() {
      head('scaling', 'Scaling', 'Run the same simple analysis on repeated copies of this channel’s data and time it. Repeated copies are an experiment, not new evidence.');
      var fs = h('fieldset', { 'class': 'factors' }, h('legend', null, 'Multipliers to run'));
      [1, 10, 100, 1000].forEach(function (f) {
        var cb = h('input', { type: 'checkbox', name: 'factor', value: String(f) }); if (f <= 100) { cb.checked = true; }
        fs.appendChild(h('label', null, cb, ' ' + f + 'x'));
      });
      var btn = h('button', { 'class': 'btn primary', type: 'button' }, 'Run the experiment');
      var st = h('span', { 'class': 'muted', role: 'status' }), err = h('p', { 'class': 'error', role: 'alert', hidden: '' }), out = h('div', null);
      view.append(fs, h('p', null, btn, ' ', st), err, out);
      view.appendChild(callout('blue', 'A channel is only a few hundred rows, so this is a Pandas experiment. There is no universal row count at which Pandas “fails”; the need for Spark depends on data size, the operation, hardware and how often it must run.'));
      view.appendChild(h('h3', null, 'Reflect'));
      var ol = h('ol', null);
      ['Which operation became slowest as the rows grew?', 'How much memory did the largest run use?', 'Repeated rows are easier for a computer than varied real data. How might that change the result?', 'What would change if the data were 100 GB, arrived every minute, or had to be shared by a team?']
        .forEach(function (t) { ol.appendChild(h('li', null, t)); });
      view.appendChild(ol);
      view.appendChild(nextLink('models', 'Next: model previews'));
      btn.addEventListener('click', function () {
        var fac = $$('input[name="factor"]', fs).filter(function (c) { return c.checked; }).map(function (c) { return c.value; });
        if (!fac.length) { err.textContent = 'Tick at least one multiplier.'; err.hidden = false; return; }
        err.hidden = true; btn.disabled = true; st.textContent = 'Running… bigger sizes take longer.';
        api(base() + 'scaling?factors=' + fac.join(',')).then(function (r) {
          btn.disabled = false; st.textContent = '';
          clear(out);
          out.appendChild(table([{ label: 'Multiplier', key: 'multiplier' }, { label: 'Rows', key: 'rows', num: true, fmt: N },
            { label: 'File size', key: 'file_mb', num: true, fmt: function (v) { return fmt(v, 1) + ' MB'; } },
            { label: 'Load time', key: 'load_seconds', num: true, fmt: fmtSec }, { label: 'Analysis time', key: 'analysis_seconds', num: true, fmt: fmtSec },
            { label: 'Slowest operation', key: 'slowest_operation' }, { label: 'Memory', key: 'memory_mb', num: true, fmt: function (v) { return fmt(v, 1) + ' MB'; } },
            { label: 'Result', cell: function (x) { return x.status === 'ok' ? 'ok' : h('span', { 'class': 'badge few' }, 'skipped: ' + x.reason); } }], r.results, 'Scaling results'));
          var ok = r.results.filter(function (x) { return x.status === 'ok'; });
          if (ok.length >= 2) {
            var ch = h('div', { 'class': 'chart' }); out.appendChild(ch);
            Charts.line(ch, { aria: 'Line chart of load time and analysis time against rows, log scales', xLog: true, yLog: true,
              xLabel: 'Rows (repeated copies)', yLabel: 'Seconds', xFmt: fmtRows, yFmt: fmtSec, xTip: function (v) { return fmt(v) + ' rows'; },
              series: [{ name: 'Load the CSV', points: ok.map(function (x) { return { x: x.rows, y: x.load_seconds }; }) },
                { name: 'Run the analysis', points: ok.map(function (x) { return { x: x.rows, y: x.analysis_seconds }; }) }] });
          }
          out.appendChild(h('p', { 'class': 'muted' }, r.note + ' ' + r.channel_note + ' Timings depend on this small shared server.'));
        }).catch(function (e) { btn.disabled = false; st.textContent = ''; if (e.status === 410) { expired(e); } else { err.textContent = e.message; err.hidden = false; } });
      });
    }

    /* ---------- models */
    function renderModels() {
      head('models', 'Models', 'Classification, clustering and regression as previews. Views, likes and comments are never used as inputs, and each model is compared with a simple baseline.');
      var btn = h('button', { 'class': 'btn primary', type: 'button' }, 'Run the three previews');
      var st = h('span', { 'class': 'muted', role: 'status' }), err = h('p', { 'class': 'error', role: 'alert', hidden: '' }), out = h('div', null);
      view.append(h('p', null, btn, ' ', st), err, out);
      view.appendChild(nextLink('report', 'Next: the report'));
      btn.addEventListener('click', function () {
        err.hidden = true; btn.disabled = true; st.textContent = 'Training three small models…';
        api(base() + 'models').then(function (m) { btn.disabled = false; st.textContent = ''; drawModels(out, m); })
          .catch(function (e) { btn.disabled = false; st.textContent = ''; if (e.status === 410) { expired(e); } else { err.textContent = e.message; err.hidden = false; } });
      });
    }
    function mcard(title) { var c = h('div', { 'class': 'card' }, h('h4', null, title)); for (var i = 1; i < arguments.length; i++) { c.appendChild(arguments[i]); } return c; }
    function drawModels(out, m) {
      clear(out);
      if (!m.available) { out.appendChild(callout('warn', m.reason)); return; }
      out.appendChild(h('p', { 'class': 'muted' }, 'Used ' + N(m.rows_used) + ' of ' + N(m.rows_total) + ' videos (videos with hidden counts are left out). ' + m.label_rule));
      var cards = h('div', { 'class': 'cards three' });
      if (m.classification) {
        var c = m.classification, gain = c.accuracy - c.baseline;
        cards.appendChild(mcard('Classification: high or low engagement',
          h('p', null, pct(c.accuracy) + ' of ' + N(c.test) + ' unseen test videos were classified correctly. Always guessing the bigger class scores ' + pct(c.baseline) + '.'),
          h('p', { 'class': 'muted' }, gain < 0.05 ? 'Barely better than guessing: do not present this as a useful prediction.' : 'Clearly better than guessing, but this is only a preview.')));
      }
      if (m.clustering) {
        var cc = m.clustering;
        cards.appendChild(mcard('Clustering: three video profiles',
          table([{ label: 'Group', key: 'cluster' }, { label: 'Videos', key: 'posts', num: true, fmt: N }].concat(cc.columns.map(function (k) { return { label: 'Median ' + k, key: k, num: true, fmt: function (v) { return fmt(v, 1); } }; })), cc.profile, 'Cluster profiles'),
          h('p', { 'class': 'muted' }, 'Clusters are not segments until you can describe and name them.')));
      }
      if (m.regression) {
        var g = m.regression, weak = g.mae_model >= 0.9 * g.mae_baseline;
        cards.appendChild(mcard('Regression: predict views',
          h('p', null, 'Predictions were off by ' + fmt(g.mae_model) + ' views on average. Always guessing the median is off by ' + fmt(g.mae_baseline) + '. R² on the log scale: ' + g.r2_log.toFixed(2) + '.'),
          h('p', { 'class': 'muted' }, weak ? 'The model barely beats the baseline: do not present it as useful.' : 'Better than the baseline, but this is only a preview.')));
      }
      out.appendChild(cards);
      out.appendChild(h('details', null, h('summary', null, 'Inputs used (' + m.features.length + ')'),
        h('p', { 'class': 'muted' }, m.features.join(', ') + (m.log_scaled_features.length ? '. Log-scaled because heavily skewed: ' + m.log_scaled_features.join(', ') + '.' : ''))));
      var ul = h('ul', null); m.notes.forEach(function (n) { ul.appendChild(h('li', null, n)); }); out.appendChild(ul);
    }

    /* ---------- report */
    function renderReport(o) {
      head('report', 'Report', 'A Markdown report with the snapshot details, cleaning steps, exploration, findings, scaling and models. It runs the scaling and model previews for you if you have not.');
      var dl = h('a', { 'class': 'btn primary', href: base() + 'report.md', download: '' }, 'Download report (.md)');
      var pr = h('button', { 'class': 'btn', type: 'button' }, 'Show report and print or save as PDF');
      var cp = h('button', { 'class': 'btn', type: 'button' }, 'Copy share link');
      var st = h('span', { 'class': 'muted', role: 'status' });
      view.appendChild(h('p', { 'class': 'actions' }, dl, pr, cp, st));
      var pre = h('pre', { 'class': 'preview', tabindex: '0', hidden: '' }); view.appendChild(pre);
      view.appendChild(callout('blue', 'Anyone with this link can open this analysis for about ' + Math.max(1, Math.round(o.expires_in_minutes / 60 * 10) / 10) + ' more hours. After that it is deleted, and you can run it again to get a fresh snapshot.'));
      view.appendChild(h('p', null, h('a', { href: '/' }, 'Analyse another channel')));
      cp.addEventListener('click', function () {
        var url = location.origin + '/analysis/' + aid + '/overview';
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(function () { st.textContent = 'Link copied.'; }, function () { st.textContent = url; });
        } else { st.textContent = url; }
      });
      pr.addEventListener('click', function () {
        st.textContent = 'Preparing the report…';
        fetch(base() + 'report.md').then(function (r) { return r.text(); }).then(function (t) {
          pre.textContent = t; pre.hidden = false; st.textContent = '';
          setTimeout(function () { window.print(); }, 150);
        }).catch(function () { st.textContent = 'Could not prepare the report. Try again.'; });
      });
    }

    /* ---------- router */
    var RENDER = {
      overview: function () { return loadOverview().then(renderOverview); },
      cleaned: function () { return api(base() + 'cleaned').then(renderCleaned); },
      explore: function () { renderExplore(); return Promise.resolve(); },
      sentiment: function () { return renderSentiment(); },
      meaning: function () { return api(base() + 'meaning').then(renderMeaning); },
      scaling: function () { renderScaling(); return Promise.resolve(); },
      models: function () { renderModels(); return Promise.resolve(); },
      report: function () { return loadOverview().then(renderReport); }
    };
    function go(sec, push) {
      current = sec;
      $$('.section-list a').forEach(function (a) {
        if (a.getAttribute('data-section') === sec) { a.setAttribute('aria-current', 'page'); } else { a.removeAttribute('aria-current'); }
      });
      if (push) { try { history.pushState(null, '', '/analysis/' + aid + '/' + sec); } catch (e) { /* ignore */ } }
      document.title = LABELS[sec] + ' · Data Detective';
      clear(view); view.appendChild(h('p', { 'class': 'muted' }, 'Loading…'));
      loadOverview().catch(function (e) { expired(e); throw e; })
        .then(function () { return RENDER[sec](); })
        .then(function () { if (push) { main.focus({ preventScroll: true }); window.scrollTo(0, 0); } })
        .catch(function (e) { if (e && e.status !== undefined && current === sec) { expired(e); } });
    }
    $$('.section-list a').forEach(function (a) {
      a.addEventListener('click', function (e) {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) { return; }
        e.preventDefault(); go(a.getAttribute('data-section'), true);
      });
    });
    window.addEventListener('popstate', function () { go(sectionFromPath(), false); });
    window.DD_SECTIONS = ORDER;
    go(sectionFromPath(), false);
  }

  var page = document.body.getAttribute('data-page');
  if (page === 'landing') { initLanding(); }
  if (page === 'results') { initResults(); }
})();
