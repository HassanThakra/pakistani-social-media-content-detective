/* Data Detective: front-end logic.
   Everything user- or data-derived is inserted with textContent / DOM calls, never innerHTML. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var fmt = Charts.fmt;

  var S = {
    cfg: { max_upload_mb: 10, max_rows: 300000, scaling_max_rows: 1000000, cache_minutes: 15 },
    source: 'bundled', file: null, label: '',
    inspect: null, clean: null, explore: null, scaling: null, models: null,
    focus: { col: null, val: null }, sel: {}
  };
  var NOTES = {};

  /* ---------------------------------------------------------------- small helpers */
  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (k === 'class') { e.className = attrs[k]; }
        else if (attrs[k] != null) { e.setAttribute(k, attrs[k]); }
      }
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) { continue; }
      e.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function clear(node) { node.replaceChildren(); }
  function show(node, on) { node.hidden = !on; }
  function pct(v, d) { return (v * 100).toFixed(d == null ? 0 : d) + '%'; }
  function fmtSec(v) {
    if (v >= 1) { return (+v.toFixed(2)) + ' s'; }
    var ms = v * 1000;
    return (+ms.toFixed(ms < 10 ? 1 : 0)) + ' ms';
  }
  function fmtRows(v) {
    if (v >= 1e6) { return (+(v / 1e6).toFixed(2)) + 'M'; }
    if (v >= 1e3) { return (+(v / 1e3).toFixed(1)) + 'k'; }
    return String(v);
  }
  function callout(cls, text) { return h('div', { class: 'callout ' + cls }, text); }
  function tile(value, label) { return h('div', { class: 'tile' }, h('div', { class: 'v' }, value), h('div', { class: 'l' }, label)); }

  function table(cols, rows, caption) {
    var head = h('tr', null);
    cols.forEach(function (c) { head.appendChild(h('th', { 'class': c.num ? 'num' : '', scope: 'col' }, c.label)); });
    var body = h('tbody', null);
    rows.forEach(function (r) {
      var tr = h('tr', null);
      cols.forEach(function (c) {
        var v = c.cell ? c.cell(r) : r[c.key];
        var td = h('td', { 'class': c.num ? 'num' : '' });
        if (v && v.nodeType) { td.appendChild(v); }
        else if (v != null) { td.textContent = c.fmt ? c.fmt(v) : String(v); }
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    var t = h('table', null, caption ? h('caption', { 'class': 'visually-hidden' }, caption) : null, h('thead', null, head), body);
    return h('div', { 'class': 'table-wrap', tabindex: '0', role: 'region', 'aria-label': caption || 'Table' }, t);
  }

  function busy(btn, statusEl, msg, on) {
    btn.disabled = on;
    if (statusEl) { statusEl.textContent = on ? msg : ''; }
  }
  function showError(id, msg) {
    var e = $(id);
    e.textContent = msg || '';
    e.hidden = !msg;
  }

  /* ---------------------------------------------------------------- notes (saved only in this browser) */
  var NOTES_KEY = 'dd_notes_v1';
  var saveTimer = null;
  function loadNotes() {
    try { NOTES = JSON.parse(localStorage.getItem(NOTES_KEY) || '{}') || {}; } catch (e) { NOTES = {}; }
  }
  function saveNotes() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try { localStorage.setItem(NOTES_KEY, JSON.stringify(NOTES)); } catch (e) { /* storage unavailable: notes stay in memory */ }
    }, 300);
  }
  function bindNote(elm) {
    var key = elm.getAttribute('data-note');
    if (NOTES[key] != null) { elm.value = NOTES[key]; }
    elm.addEventListener('input', function () {
      NOTES[key] = elm.value;
      saveNotes();
      if (!$('#panel-8').hidden) { renderChecklist(); }
    });
  }
  function note(k) { return (NOTES[k] || '').trim(); }

  /* ---------------------------------------------------------------- tooltip */
  var tipEl = $('#tip');
  function placeTip(x, y) {
    var w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    var left = Math.min(x + 14, window.innerWidth - w - 8), top = y + 16;
    if (top + hh > window.innerHeight - 8) { top = y - hh - 12; }
    tipEl.style.left = Math.max(8, left) + 'px';
    tipEl.style.top = Math.max(8, top) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) { return; }
    tipEl.textContent = t.getAttribute('data-tip');
    tipEl.hidden = false;
    placeTip(e.clientX, e.clientY);
  });
  document.addEventListener('mousemove', function (e) { if (!tipEl.hidden) { placeTip(e.clientX, e.clientY); } });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest && e.target.closest('[data-tip]')) { tipEl.hidden = true; }
  });
  document.addEventListener('focusin', function (e) {
    var t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!t) { return; }
    tipEl.textContent = t.getAttribute('data-tip');
    tipEl.hidden = false;
    var r = t.getBoundingClientRect();
    placeTip(r.left + r.width / 2, r.top);
  });
  document.addEventListener('focusout', function () { tipEl.hidden = true; });

  /* ---------------------------------------------------------------- tabs */
  var tabs = $$('[role="tab"]');
  function selectTab(n, moveFocus) {
    tabs.forEach(function (t) {
      var on = t.id === 'tab-' + n;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      $('#panel-' + t.id.slice(4)).hidden = !on;
      if (on && moveFocus) { t.focus(); }
    });
    if (String(n) === '8') { renderChecklist(); }
    try { history.replaceState(null, '', '#' + n); } catch (e) { /* ignore */ }
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () { selectTab(t.id.slice(4)); });
    t.addEventListener('keydown', function (e) {
      var j = null;
      if (e.key === 'ArrowRight') { j = (i + 1) % tabs.length; }
      else if (e.key === 'ArrowLeft') { j = (i - 1 + tabs.length) % tabs.length; }
      else if (e.key === 'Home') { j = 0; }
      else if (e.key === 'End') { j = tabs.length - 1; }
      if (j !== null) { e.preventDefault(); selectTab(tabs[j].id.slice(4), true); }
    });
  });
  $$('[data-goto]').forEach(function (b) {
    b.addEventListener('click', function () {
      selectTab(b.getAttribute('data-goto'));
      $('#main').scrollIntoView();
    });
  });

  /* ---------------------------------------------------------------- theme */
  var THEMES = ['auto', 'light', 'dark'];
  function applyTheme(t) {
    if (t === 'light' || t === 'dark') { document.documentElement.setAttribute('data-theme', t); }
    else { document.documentElement.removeAttribute('data-theme'); }
    $('#theme-btn').textContent = 'Theme: ' + t;
  }
  var theme = 'auto';
  try { theme = localStorage.getItem('dd_theme') || 'auto'; } catch (e) { /* ignore */ }
  if (THEMES.indexOf(theme) < 0) { theme = 'auto'; }
  applyTheme(theme);
  $('#theme-btn').addEventListener('click', function () {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(theme);
    try { localStorage.setItem('dd_theme', theme); } catch (e) { /* ignore */ }
  });

  /* ---------------------------------------------------------------- api */
  function formData(extra) {
    var fd = new FormData();
    fd.append('source', S.source);
    if (S.source === 'upload' && S.file) { fd.append('file', S.file); }
    for (var k in (extra || {})) { if (extra[k] != null) { fd.append(k, extra[k]); } }
    return fd;
  }
  function api(path, extra) {
    return fetch(path, { method: 'POST', body: formData(extra) }).then(function (resp) {
      return resp.json().catch(function () { return null; }).then(function (data) {
        if (!resp.ok) { throw new Error((data && data.error) || ('The server returned an error (' + resp.status + ').')); }
        return data;
      });
    }, function () { throw new Error('Could not reach the server. Check your connection and try again.'); });
  }

  /* ---------------------------------------------------------------- step 2: load */
  function updateSourceUI() {
    var v = $('input[name="source"]:checked').value;
    show($('#upload-row'), v === 'upload');
  }
  $$('input[name="source"]').forEach(function (r) { r.addEventListener('change', updateSourceUI); });
  $('#file-input').addEventListener('change', function () {
    if ($('#file-input').files.length) { $('input[name="source"][value="upload"]').checked = true; updateSourceUI(); }
  });

  function updateDatabar() {
    var bar = $('#databar'), txt = $('#databar-text');
    clear(txt);
    if (!S.inspect) { txt.textContent = 'No data loaded yet. Go to step 2 to load some.'; return; }
    var rows = S.clean ? S.clean.report.rows_after : S.inspect.profile.rows;
    if (S.source === 'upload') {
      txt.appendChild(h('strong', null, S.label));
      txt.appendChild(document.createTextNode(' (' + fmt(rows) + ' rows after cleaning). Processed in memory, never saved to disk, and discarded after about ' + S.cfg.cache_minutes + ' minutes.'));
    } else {
      txt.appendChild(h('strong', null, S.label));
      txt.appendChild(document.createTextNode(' (' + fmt(rows) + ' rows after cleaning). No license is stated and it is not verified as data from any Pakistani brand.'));
    }
  }

  function loadData() {
    var src = $('input[name="source"]:checked').value;
    showError('#load-error', '');
    var file = $('#file-input').files[0] || null;
    if (src === 'upload') {
      if (!file) { showError('#load-error', 'Choose a CSV file first.'); return; }
      if (file.size > S.cfg.max_upload_mb * 1024 * 1024) { showError('#load-error', 'That file is larger than the ' + S.cfg.max_upload_mb + ' MB limit.'); return; }
    }
    S.source = src; S.file = src === 'upload' ? file : null;
    var btn = $('#load-btn'), st = $('#load-status');
    busy(btn, st, 'Loading and checking the data…', true);
    api('/api/inspect').then(function (ins) {
      S.inspect = ins; S.label = ins.label;
      return api('/api/clean');
    }).then(function (cl) {
      S.clean = cl; S.explore = S.scaling = S.models = null;
      S.focus = { col: cl.focus.col, val: cl.focus.val };
      resetDatasetNotes();
      renderInspect(); renderClean(); updateDatabar();
      var ok = setupExplore();
      resetScale(); resetModels();
      busy(btn, st, '', false);
      st.textContent = 'Loaded. Next: step 3 cleans a copy.';
      return ok ? runExplore() : null;
    }).catch(function (e) {
      busy(btn, st, '', false);
      showError('#load-error', e.message);
    });
  }
  $('#load-btn').addEventListener('click', loadData);

  /* notes about one dataset should not leak onto a different dataset */
  function resetDatasetNotes() {
    var last = null;
    try { last = localStorage.getItem('dd_last_label'); localStorage.setItem('dd_last_label', S.label); } catch (e) { /* ignore */ }
    if (last !== null && last !== S.label) {
      Object.keys(NOTES).forEach(function (k) {
        if (k === 'record' || k === 'provenance' || k.indexOf('meaning:') === 0) { delete NOTES[k]; }
      });
      saveNotes();
      ['record', 'provenance'].forEach(function (k) { var e = $('[data-note="' + k + '"]'); if (e) { e.value = ''; } });
    }
  }

  function renderInspect() {
    var p = S.inspect.profile;
    show($('#inspect-out'), true);
    var tiles = $('#tiles'); clear(tiles);
    tiles.append(tile(fmt(p.rows), 'rows'), tile(fmt(p.columns), 'columns'),
      tile(fmt(p.exact_duplicates), 'exact duplicate rows'), tile(fmt(p.missing_cells), 'blank cells'));

    var iss = $('#issues'); clear(iss);
    if (!p.issues.length) { iss.appendChild(h('li', null, 'No obvious problems detected. Still check each column yourself.')); }
    p.issues.forEach(function (i) { iss.appendChild(h('li', null, h('span', { 'class': 'col' }, i.column + ': '), i.text)); });

    var pv = p.provenance, box = $('#provenance'); clear(box);
    box.className = 'callout' + (pv.looks_templated ? ' warn' : '');
    var lines = [];
    if (pv.distinct_texts != null) {
      lines.push('The “' + pv.text_column + '” column has only ' + fmt(pv.distinct_texts) + ' different values across ' + fmt(pv.rows) + ' rows.');
      if (pv.top_texts && pv.top_texts.length) { lines.push('Most common: “' + pv.top_texts[0].text + '” (' + pv.top_texts[0].count + ' times).'); }
    }
    if (pv.distinct_hashtags != null) { lines.push(fmt(pv.distinct_hashtags) + ' different hashtags are used in total.'); }
    if (pv.distinct_users != null) { lines.push(fmt(pv.distinct_users) + ' different users; the busiest account has ' + pv.max_posts_by_one_user + ' posts.'); }
    if (pv.looks_templated) { lines.push('That is very repetitive. Real posts are rarely this repetitive, so this data may be generated or templated.'); }
    if (!lines.length) { lines.push('No text column was found to check.'); }
    lines.push('Nothing in the file says how it was collected. Treat real-world claims with caution.');
    lines.forEach(function (t) { box.appendChild(h('p', null, t)); });

    var cols = $('#columns'); clear(cols);
    cols.appendChild(table([
      { label: 'Column', key: 'name' }, { label: 'Stored as', key: 'stored_as' }, { label: 'Looks like', key: 'kind' },
      { label: 'Blank', key: 'missing', num: true, fmt: function (v) { return fmt(v); } },
      { label: 'Distinct', key: 'distinct', num: true, fmt: function (v) { return fmt(v); } },
      { label: 'Example', key: 'example' },
      { label: 'What it means (you verify)', cell: function (r) {
        var inp = h('input', { type: 'text', 'data-note': 'meaning:' + r.name, 'aria-label': 'Meaning of column ' + r.name, maxlength: '300' });
        bindNote(inp);
        return inp;
      } }
    ], p.cols, 'Columns in the raw file'));

    var head = $('#head'); clear(head);
    var keys = p.cols.map(function (c) { return c.name; });
    head.appendChild(table(keys.map(function (k) { return { label: k, key: k }; }), p.head, 'First rows of the raw file'));
  }

  /* ---------------------------------------------------------------- step 3: clean */
  function renderClean() {
    var c = S.clean, r = c.report;
    show($('#clean-empty'), false); show($('#clean-out'), true);
    var tiles = $('#clean-tiles'); clear(tiles);
    tiles.append(tile(fmt(r.rows_before) + ' → ' + fmt(r.rows_after), 'rows, before → after'),
      tile(fmt(r.duplicates_removed), 'duplicate rows removed'),
      tile(fmt(Object.keys(r.negatives_to_missing).reduce(function (a, k) { return a + r.negatives_to_missing[k]; }, 0)), 'impossible values set to missing'),
      tile(fmt(r.derived.length), 'columns added'));
    var steps = $('#clean-steps'); clear(steps);
    r.steps.forEach(function (s) { steps.appendChild(h('li', null, h('span', { 'class': 't' }, s.title + '. '), s.detail)); });
    $('#clean-note').textContent = r.note;

    var colSel = $('#focus-col'); clear(colSel);
    colSel.appendChild(h('option', { value: '' }, 'All rows'));
    c.roles.groups.forEach(function (g) { colSel.appendChild(h('option', { value: g }, g)); });
    colSel.value = S.focus.col || '';
    fillFocusValues();

    var miss = Object.keys(r.missing_after).map(function (k) { return { column: k, n: r.missing_after[k], pct: r.missing_after[k] / r.rows_after }; })
      .sort(function (a, b) { return b.n - a.n; });
    var m = $('#missing-after'); clear(m);
    if (!miss.length) { m.appendChild(h('p', { 'class': 'muted' }, 'No blank values remain.')); }
    else {
      m.appendChild(table([{ label: 'Column', key: 'column' }, { label: 'Blank values', key: 'n', num: true, fmt: function (v) { return fmt(v); } },
        { label: 'Share of rows', key: 'pct', num: true, fmt: function (v) { return pct(v, 1); } }], miss, 'Blank values after cleaning'));
    }
  }

  function fillFocusValues() {
    var col = $('#focus-col').value, valSel = $('#focus-val'); clear(valSel);
    if (!col) { valSel.disabled = true; S.focus = { col: null, val: null }; focusInfo(); return; }
    valSel.disabled = false;
    (S.clean.focus_options[col] || []).forEach(function (o) { valSel.appendChild(h('option', { value: o.value }, o.value + ' (' + fmt(o.count) + ')')); });
    if (S.focus.col === col && S.focus.val) { valSel.value = S.focus.val; }
    S.focus = { col: col, val: valSel.value || null };
    focusInfo();
  }
  function focusInfo() {
    var total = S.clean.report.rows_after, n = total;
    if (S.focus.col && S.focus.val) {
      var o = (S.clean.focus_options[S.focus.col] || []).filter(function (x) { return x.value === S.focus.val; })[0];
      if (o) { n = o.count; }
    }
    $('#focus-info').textContent = S.focus.col ? ('Looking at ' + fmt(n) + ' of ' + fmt(total) + ' rows.') : ('Looking at all ' + fmt(total) + ' rows.');
  }
  $('#focus-col').addEventListener('change', function () { S.focus = { col: $('#focus-col').value || null, val: null }; fillFocusValues(); runExplore(); });
  $('#focus-val').addEventListener('change', function () { S.focus.val = $('#focus-val').value || null; focusInfo(); runExplore(); });

  /* ---------------------------------------------------------------- step 4: explore */
  function fillSelect(sel, values, preferred) {
    clear(sel);
    values.forEach(function (v) { sel.appendChild(h('option', { value: v }, v)); });
    for (var i = 0; i < preferred.length; i++) { if (values.indexOf(preferred[i]) >= 0) { sel.value = preferred[i]; return; } }
  }
  function setupExplore() {
    var roles = S.clean.roles;
    show($('#explore-empty'), false);
    show($('#explore-ui'), true);
    if (!roles.groups.length || !roles.metrics.length) {
      showError('#explore-error', 'This file needs at least one category column (like platform) and one numeric column (like likes) to explore.');
      show($('#explore-out'), false);
      return false;
    }
    showError('#explore-error', '');
    show($('#explore-out'), true);
    var groupPref = ['sentiment', 'content_type', 'platform'].filter(function (g) { return g !== S.focus.col; });
    fillSelect($('#sel-group'), roles.groups, groupPref.concat(roles.groups.filter(function (g) { return g !== S.focus.col; })));
    fillSelect($('#sel-metric'), roles.metrics, ['comments', 'likes']);
    fillSelect($('#sel-x'), roles.metrics, ['likes']);
    var yPref = ['comments'].filter(function (m) { return m !== $('#sel-x').value; });
    fillSelect($('#sel-y'), roles.metrics, yPref.concat(roles.metrics.filter(function (m) { return m !== $('#sel-x').value; })));
    return true;
  }
  var exploreSeq = 0, minTimer = null;
  function runExplore() {
    if (!S.clean || $('#explore-ui').hidden || !$('#sel-group').value) { return Promise.resolve(); }
    var seq = ++exploreSeq;
    var roles = S.clean.roles;
    var sel = { group: $('#sel-group').value, metric: $('#sel-metric').value, min: $('#sel-min').value, x: $('#sel-x').value, y: $('#sel-y').value };
    S.sel = sel;
    return api('/api/explore', {
      focus_col: S.focus.col || '', focus_val: S.focus.val || '', apply_focus: $('#sel-focus').checked ? '1' : '0',
      group_col: sel.group, metric: sel.metric, min_posts: sel.min, x: sel.x, y: sel.y, dt_col: roles.dates[0] || ''
    }).then(function (r) {
      if (seq !== exploreSeq) { return; }
      showError('#explore-error', '');
      S.explore = r; S.explore.sel = sel; S.explore.scope = scopeText();
      renderExplore();
    }).catch(function (e) {
      if (seq !== exploreSeq) { return; }
      showError('#explore-error', e.message);
    });
  }
  function scopeText() {
    if ($('#sel-focus').checked && S.focus.col && S.focus.val) { return S.focus.col + ' = ' + S.focus.val; }
    return 'all rows';
  }
  ['#sel-group', '#sel-metric', '#sel-x', '#sel-y', '#sel-focus'].forEach(function (id) { $(id).addEventListener('change', runExplore); });
  $('#sel-min').addEventListener('input', function () { clearTimeout(minTimer); minTimer = setTimeout(runExplore, 400); });

  function renderWarnings(box, list) {
    clear(box);
    (list || []).forEach(function (w) { box.appendChild(callout('warn', w)); });
  }

  function renderExplore() {
    var r = S.explore, sel = r.sel, g = r.group;
    $('#explore-scope').textContent = 'Looking at: ' + r.scope + ' (' + fmt(r.rows_used) + ' rows).';
    renderWarnings($('#explore-warnings'), r.warnings);
    renderWarnings($('#interpret-warnings'), r.warnings);

    $('#h-group').textContent = 'Median ' + sel.metric + ' by ' + sel.group;
    Charts.bar($('#chart-group'), {
      aria: 'Bar chart of median ' + sel.metric + ' for each ' + sel.group + '. The table below has the same numbers.',
      yLabel: 'Median ' + sel.metric, xLabel: sel.group + '  (n = posts with a value)',
      items: g.rows.map(function (x) {
        return { label: x.group, value: x.median, n: x.posts, few: x.too_few,
          tip: x.group + ': median ' + fmt(x.median) + ', mean ' + fmt(x.mean) + ', ' + fmt(x.posts) + ' posts' + (x.too_few ? ' (few posts)' : '') };
      })
    });
    var tg = $('#table-group'); clear(tg);
    tg.appendChild(table([
      { label: sel.group, key: 'group' },
      { label: 'Posts', key: 'posts', num: true, fmt: function (v) { return fmt(v); } },
      { label: 'Median', key: 'median', num: true, fmt: function (v) { return fmt(v, 1); } },
      { label: 'Mean', key: 'mean', num: true, fmt: function (v) { return fmt(v, 1); } },
      { label: 'Group size', cell: function (x) { return x.too_few ? h('span', { 'class': 'badge few' }, 'few posts') : h('span', { 'class': 'badge' }, 'ok'); } }
    ], g.rows, 'Median and mean ' + sel.metric + ' by ' + sel.group));
    if (g.excluded_missing_group) {
      tg.appendChild(h('p', { 'class': 'muted' }, fmt(g.excluded_missing_group) + ' rows have no ' + sel.group + ' value and are left out of this table.'));
    }

    var d = r.dist;
    $('#h-dist').textContent = 'How ' + sel.metric + ' is spread out';
    if (d.n) {
      Charts.hist($('#chart-dist'), { edges: d.edges, counts: d.counts, median: d.median, xLabel: sel.metric, aria: 'Histogram of ' + sel.metric });
      var facts = fmt(d.n) + ' values. Mean ' + fmt(d.mean, 1) + ', median ' + fmt(d.median, 1) + ', range ' + fmt(d.min) + ' to ' + fmt(d.max) + '.';
      if (r.top_share) { facts += ' The top 10% of posts (' + fmt(r.top_share.top_n) + ' of ' + fmt(r.top_share.of) + ') hold ' + pct(r.top_share.share) + ' of all ' + sel.metric + '.'; }
      $('#dist-facts').textContent = facts;
    } else { clear($('#chart-dist')); $('#dist-facts').textContent = 'No values to show.'; }

    var sc = r.scatter, sbox = $('#chart-scatter');
    $('#h-scatter').textContent = sc ? ('Is ' + sc.y + ' related to ' + sc.x + '?') : 'Scatter plot';
    if (sc && sc.points.length) {
      Charts.scatter(sbox, { points: sc.points, xLabel: sc.x, yLabel: sc.y, xName: sc.x, yName: sc.y, aria: 'Scatter plot of ' + sc.y + ' against ' + sc.x });
      var f = '';
      if (sc.spearman != null) {
        var a = Math.abs(sc.spearman), word = a < 0.3 ? 'weak' : a < 0.6 ? 'moderate' : 'strong';
        f = 'Spearman correlation ' + sc.spearman.toFixed(2) + ' (' + word + ', ' + (sc.spearman >= 0 ? 'positive' : 'negative') + ') across ' + fmt(sc.n) + ' posts. Correlation is not causation.';
      }
      if (sc.shown < sc.n) { f += ' Showing a random ' + fmt(sc.shown) + ' of ' + fmt(sc.n) + ' points.'; }
      $('#scatter-facts').textContent = f;
    } else { clear(sbox); $('#scatter-facts').textContent = ''; }

    var wk = r.weekday;
    show($('#weekday-block'), !!wk);
    if (wk) {
      $('#h-weekday').textContent = 'Median ' + sel.metric + ' by day of week';
      Charts.bar($('#chart-weekday'), {
        aria: 'Bar chart of median ' + sel.metric + ' by day of week', yLabel: 'Median ' + sel.metric,
        items: wk.rows.map(function (x) { return { label: x.day.slice(0, 3), value: x.median || 0, n: x.posts, few: x.posts < 30,
          tip: x.day + ': median ' + fmt(x.median) + ', mean ' + fmt(x.mean) + ', ' + fmt(x.posts) + ' posts' }; })
      });
      var tw = $('#table-weekday'); clear(tw);
      tw.appendChild(table([{ label: 'Day', key: 'day' }, { label: 'Posts', key: 'posts', num: true, fmt: function (v) { return fmt(v); } },
        { label: 'Median', key: 'median', num: true, fmt: function (v) { return fmt(v, 1); } },
        { label: 'Mean', key: 'mean', num: true, fmt: function (v) { return fmt(v, 1); } }], wk.rows, 'Median and mean by day'));
    }
  }

  /* ---------------------------------------------------------------- step 6: scale */
  function resetScale() {
    show($('#scale-empty'), false); show($('#scale-ui'), true); show($('#scale-out'), false);
    showError('#scale-error', '');
    var rows = S.clean.report.rows_after;
    $$('input[name="factor"]').forEach(function (cb) {
      var f = parseInt(cb.value, 10), over = rows * f > S.cfg.scaling_max_rows;
      cb.disabled = over;
      if (over) { cb.checked = false; }
      var lab = cb.parentNode;
      var extra = lab.querySelector('small');
      if (extra) { extra.remove(); }
      if (over) { lab.appendChild(h('small', null, ' (over this server\'s ' + fmtRows(S.cfg.scaling_max_rows) + '-row limit)')); }
    });
    S.scaling = null;
  }
  $('#scale-btn').addEventListener('click', function () {
    var factors = $$('input[name="factor"]').filter(function (c) { return c.checked && !c.disabled; }).map(function (c) { return c.value; });
    if (!factors.length) { showError('#scale-error', 'Tick at least one multiplier.'); return; }
    var roles = S.clean.roles, eng = (S.clean.engagement || []).filter(function (m) { return m === 'likes' || m === 'comments'; });
    var metrics = (eng.length ? eng : roles.metrics).slice(0, 2);
    var group = roles.groups.indexOf('platform') >= 0 ? 'platform' : roles.groups[0];
    var btn = $('#scale-btn'), st = $('#scale-status');
    showError('#scale-error', '');
    busy(btn, st, 'Running… bigger sizes take longer.', true);
    api('/api/scaling', { factors: factors.join(','), group_col: group, metrics: metrics.join(',') }).then(function (r) {
      busy(btn, st, '', false);
      S.scaling = r;
      renderScale();
    }).catch(function (e) { busy(btn, st, '', false); showError('#scale-error', e.message); });
  });
  function renderScale() {
    var r = S.scaling;
    show($('#scale-out'), true);
    var t = $('#scale-table'); clear(t);
    t.appendChild(table([
      { label: 'Multiplier', key: 'multiplier' },
      { label: 'Rows', key: 'rows', num: true, fmt: function (v) { return fmt(v); } },
      { label: 'File size', key: 'file_mb', num: true, fmt: function (v) { return fmt(v, 1) + ' MB'; } },
      { label: 'Load time', key: 'load_seconds', num: true, fmt: fmtSec },
      { label: 'Analysis time', key: 'analysis_seconds', num: true, fmt: fmtSec },
      { label: 'Slowest operation', key: 'slowest_operation' },
      { label: 'Memory', key: 'memory_mb', num: true, fmt: function (v) { return fmt(v, 1) + ' MB'; } },
      { label: 'Result', cell: function (x) { return x.status === 'ok' ? 'ok' : h('span', { 'class': 'badge few' }, 'skipped: ' + x.reason); } }
    ], r.results, 'Scaling experiment results'));
    var ok = r.results.filter(function (x) { return x.status === 'ok'; });
    if (ok.length >= 2) {
      Charts.line($('#chart-scale'), {
        aria: 'Line chart of load time and analysis time against number of rows, on log scales',
        xLog: true, yLog: true, xLabel: 'Rows (repeated copies of the same data)', yLabel: 'Seconds',
        xFmt: fmtRows, yFmt: fmtSec, xTip: function (v) { return fmt(v) + ' rows'; },
        series: [
          { name: 'Load the CSV', points: ok.map(function (x) { return { x: x.rows, y: x.load_seconds }; }) },
          { name: 'Run the analysis', points: ok.map(function (x) { return { x: x.rows, y: x.analysis_seconds }; }) }
        ]
      });
    } else { clear($('#chart-scale')); }
    $('#scale-note').textContent = r.note + ' Timings depend on this server, which is a small shared computer. Run it again and compare.';
  }

  /* ---------------------------------------------------------------- step 7: analytics */
  function resetModels() {
    show($('#models-empty'), false); show($('#models-ui'), true); clear($('#models-out')); showError('#models-error', '');
    S.models = null;
  }
  $('#models-btn').addEventListener('click', function () {
    var btn = $('#models-btn'), st = $('#models-status');
    showError('#models-error', '');
    busy(btn, st, 'Training three small models…', true);
    api('/api/models').then(function (m) { busy(btn, st, '', false); S.models = m; renderModels(); })
      .catch(function (e) { busy(btn, st, '', false); showError('#models-error', e.message); });
  });
  function card(title) {
    var c = h('div', { 'class': 'card' }, h('h4', null, title));
    for (var i = 1; i < arguments.length; i++) { c.appendChild(arguments[i]); }
    return c;
  }
  function renderModels() {
    var m = S.models, out = $('#models-out'); clear(out);
    if (!m.available) { out.appendChild(callout('warn', m.reason)); return; }
    out.appendChild(h('p', { 'class': 'muted' }, 'Used ' + fmt(m.rows_used) + ' of ' + fmt(m.rows_total) + ' rows. ' + m.label_rule));
    var cards = h('div', { 'class': 'cards three' });
    if (m.classification) {
      var c = m.classification, gain = c.accuracy - c.baseline;
      cards.appendChild(card('Classification: high or low engagement',
        h('p', null, pct(c.accuracy) + ' of ' + fmt(c.test) + ' unseen test posts were classified correctly. Always guessing the bigger class scores ' + pct(c.baseline) + '.'),
        h('p', { 'class': 'muted' }, gain < 0.05 ? 'Barely better than guessing: do not present this as a useful prediction.' : 'Clearly better than guessing, but this is only a demo.')));
    }
    if (m.clustering) {
      var cc = m.clustering;
      cards.appendChild(card('Clustering: three groups of posts',
        table([{ label: 'Group', key: 'cluster' }, { label: 'Posts', key: 'posts', num: true, fmt: function (v) { return fmt(v); } }]
          .concat(cc.columns.map(function (k) { return { label: 'Median ' + k, key: k, num: true, fmt: function (v) { return fmt(v, 1); } }; })), cc.profile, 'Cluster profiles'),
        h('p', { 'class': 'muted' }, 'Clusters are not business segments until you can describe and name them.')));
    }
    if (m.regression) {
      var g = m.regression, weak = g.mae_model >= 0.9 * g.mae_baseline;
      cards.appendChild(card('Regression: predict likes',
        h('p', null, 'Predictions were off by ' + fmt(g.mae_model, 1) + ' likes on average. Always guessing the median is off by ' + fmt(g.mae_baseline, 1) + '. R² on the log scale: ' + g.r2_log.toFixed(2) + '.'),
        h('p', { 'class': 'muted' }, weak ? 'The model barely beats the baseline: do not present it as useful.' : 'Better than the baseline, but this is only a demo.')));
    }
    out.appendChild(cards);
    var det = h('details', null, h('summary', null, 'Features used (' + m.features.length + ')'),
      h('p', { 'class': 'muted' }, m.features.join(', ') + (m.log_scaled_features && m.log_scaled_features.length ? '. Log-scaled because they are heavily skewed: ' + m.log_scaled_features.join(', ') + '.' : '')));
    out.appendChild(det);
    var ul = h('ul', null); (m.notes || []).forEach(function (n) { ul.appendChild(h('li', null, n)); });
    out.appendChild(ul);
  }

  /* ---------------------------------------------------------------- step 8: checklist and report */
  function checklistItems() {
    var anyMeaning = Object.keys(NOTES).some(function (k) { return k.indexOf('meaning:') === 0 && (NOTES[k] || '').trim().length >= 3; });
    return [
      { t: 'Dataset source, license/provenance note, and data dictionary', done: !!S.inspect && note('provenance').length >= 10 && anyMeaning },
      { t: 'Record count, column types, missing-value and duplicate checks', done: !!S.inspect },
      { t: 'At least two summary statistics and two useful charts', done: !!S.explore },
      { t: 'Two evidence-based observations and one marketing recommendation', done: note('finding').length >= 15 && note('evidence').length >= 10 && note('finding2').length >= 15 && note('action').length >= 15 },
      { t: 'One limitation and a reason a scalable tool might help at larger scale', done: note('limitation').length >= 15 && !!S.scaling && note('reflect').length >= 15 }
    ];
  }
  function renderChecklist() {
    var ul = $('#checklist'); clear(ul);
    checklistItems().forEach(function (i) {
      ul.appendChild(h('li', { 'class': i.done ? 'done' : '' }, h('span', { 'class': 'mark', 'aria-hidden': 'true' }, i.done ? '✓' : '○'),
        h('span', null, i.t), h('span', { 'class': 'state' }, i.done ? 'looks done' : 'not yet')));
    });
  }

  function esc(s) { return String(s == null ? '' : s).replace(/\|/g, '\\|').replace(/\r?\n/g, ' '); }
  function mdTable(head, rows) {
    return ['| ' + head.map(esc).join(' | ') + ' |', '|' + head.map(function () { return '---'; }).join('|') + '|']
      .concat(rows.map(function (r) { return '| ' + r.map(esc).join(' | ') + ' |'; })).join('\n');
  }
  function buildReport() {
    var L = [], N = function (k) { return note(k) || '_(not written yet)_'; };
    L.push('# Project 1 report: Data Detective', '');
    L.push('Generated ' + new Date().toISOString().slice(0, 10) + '.', '');
    L.push('**Business question:** A Pakistani clothing brand posts on Instagram. Which content receives attention, and what should it publish next?', '');
    if (!S.inspect) { L.push('_No dataset was loaded._'); return L.join('\n'); }
    L.push('## 1. Dataset', '', '**Source:** ' + S.label);
    if (S.source === 'bundled') { L.push('', '> The bundled dataset has no stated license and is not verified as data from any Pakistani brand. Make no claims about Pakistan from it.'); }
    L.push('', '**What is one record?** ' + N('record'), '', '**Source, license and provenance note:** ' + N('provenance'), '');
    var p = S.inspect.profile;
    L.push('Raw file: ' + fmt(p.rows) + ' rows, ' + p.columns + ' columns, ' + fmt(p.exact_duplicates) + ' exact duplicate rows, ' + fmt(p.missing_cells) + ' blank cells.', '');
    L.push('### Data dictionary', '');
    L.push(mdTable(['Column', 'Stored as', 'Looks like', 'Blank', 'Distinct', 'What it means (verified by the student)'],
      p.cols.map(function (c) { return [c.name, c.stored_as, c.kind, c.missing, c.distinct, (NOTES['meaning:' + c.name] || '').trim() || '(not written)']; })), '');
    L.push('### Problems found in the raw file', '');
    p.issues.forEach(function (i) { L.push('- **' + i.column + ':** ' + i.text); });
    L.push('', '## 2. Cleaning', '');
    if (S.clean) {
      S.clean.report.steps.forEach(function (s) { L.push('- **' + s.title + '.** ' + s.detail); });
      L.push('', S.clean.report.note, '', 'Rows: ' + fmt(S.clean.report.rows_before) + ' before, ' + fmt(S.clean.report.rows_after) + ' after cleaning.', '');
    }
    L.push('## 3. Exploration', '');
    if (S.explore) {
      var e = S.explore, s = e.sel;
      L.push('Looking at: ' + e.scope + ' (' + fmt(e.rows_used) + ' rows). Median and mean ' + s.metric + ' by ' + s.group + ':', '');
      L.push(mdTable([s.group, 'Posts', 'Median', 'Mean', 'Group size'], e.group.rows.map(function (x) { return [x.group, x.posts, fmt(x.median, 1), fmt(x.mean, 1), x.too_few ? 'few posts' : 'ok']; })), '');
      if (e.dist.n) {
        L.push('Spread of ' + s.metric + ': mean ' + fmt(e.dist.mean, 1) + ', median ' + fmt(e.dist.median, 1) + ', range ' + fmt(e.dist.min) + ' to ' + fmt(e.dist.max) +
          (e.top_share ? '. The top 10% of posts hold ' + pct(e.top_share.share) + ' of all ' + s.metric + '.' : '.'), '');
      }
      if (e.scatter && e.scatter.spearman != null) { L.push('Spearman correlation between ' + e.scatter.x + ' and ' + e.scatter.y + ': ' + e.scatter.spearman.toFixed(2) + ' (n=' + fmt(e.scatter.n) + ').', ''); }
      if (e.warnings && e.warnings.length) { L.push('Cautions shown by the tool:'); e.warnings.forEach(function (w) { L.push('- ' + w); }); L.push(''); }
    } else { L.push('_Not run._', ''); }
    L.push('## 4. Interpretation', '',
      '**Observation 1:** ' + N('finding'), '', '**Evidence:** ' + N('evidence'), '',
      '**Observation 2:** ' + N('finding2'), '', '**Evidence:** ' + N('evidence2'), '',
      '**Recommendation (action):** ' + N('action'), '', '**Limitation:** ' + N('limitation'), '');
    L.push('## 5. Scaling experiment', '');
    if (S.scaling) {
      L.push(mdTable(['Multiplier', 'Rows', 'File MB', 'Load', 'Analysis', 'Slowest operation', 'Memory MB', 'Result'],
        S.scaling.results.map(function (x) { return x.status === 'ok' ? [x.multiplier, fmt(x.rows), fmt(x.file_mb, 1), fmtSec(x.load_seconds), fmtSec(x.analysis_seconds), x.slowest_operation, fmt(x.memory_mb, 1), 'ok'] : [x.multiplier, fmt(x.rows), '', '', '', '', '', 'skipped: ' + x.reason]; })), '');
      L.push('_' + S.scaling.note + '_', '');
    } else { L.push('_Not run._', ''); }
    L.push('**Reflection:** ' + N('reflect'), '');
    L.push('## 6. Analytics preview', '');
    var m = S.models;
    if (m && m.available) {
      if (m.classification) { L.push('- Classification: ' + pct(m.classification.accuracy) + ' test accuracy vs ' + pct(m.classification.baseline) + ' baseline.'); }
      if (m.regression) { L.push('- Regression: mean error ' + fmt(m.regression.mae_model, 1) + ' likes vs ' + fmt(m.regression.mae_baseline, 1) + ' for guessing the median (R² on log scale ' + m.regression.r2_log.toFixed(2) + ').'); }
      if (m.clustering) { L.push('- Clustering: three groups, profiled by median ' + m.clustering.columns.join(', ') + '.'); }
      L.push('');
    } else { L.push('_Not run._', ''); }
    L.push('**Which technique would help the marketing question, and what evidence would it need?** ' + N('analytics'), '');
    L.push('## 7. Closing question', '', '_What does the data tell us, what business problem does it reveal, and what should the business do next?_', '', N('closing'), '');
    L.push('## Checklist (from the tool, not a grade)', '');
    checklistItems().forEach(function (i) { L.push('- [' + (i.done ? 'x' : ' ') + '] ' + i.t); });
    L.push('', '---', '', 'Caveats: repeated rows in the scaling experiment are not new evidence. The dataset has no reach or impressions, so no engagement rate on reach and no paid-ad conclusions can be drawn. Optional class hashtag: #UMTDataDetective.');
    return L.join('\n');
  }
  $('#report-preview-btn').addEventListener('click', function () {
    var pre = $('#report-preview'); pre.textContent = buildReport(); pre.hidden = false;
  });
  $('#report-btn').addEventListener('click', function () {
    var blob = new Blob([buildReport()], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = h('a', { href: url, download: 'project1_report.md' });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  });
  $('#clear-notes').addEventListener('click', function () {
    if (!window.confirm('Delete everything you have typed on this device? This cannot be undone.')) { return; }
    NOTES = {};
    try { localStorage.removeItem(NOTES_KEY); } catch (e) { /* ignore */ }
    $$('[data-note]').forEach(function (e) { e.value = ''; });
    renderChecklist();
  });

  /* ---------------------------------------------------------------- start */
  loadNotes();
  $$('[data-note]').forEach(bindNote);
  fetch('/api/config').then(function (r) { return r.json(); }).then(function (c) {
    S.cfg = c;
    $('#upload-hint').textContent = 'Up to ' + c.max_upload_mb + ' MB and ' + fmt(c.max_rows) + ' rows. Needs a header row.';
  }).catch(function () { /* defaults are fine */ });
  var start = (location.hash || '').replace('#', '');
  if (/^[1-8]$/.test(start)) { selectTab(start); }
  window.DD = { state: S };   // handy for debugging in the browser console
})();
