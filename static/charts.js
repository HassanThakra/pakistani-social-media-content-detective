/* Data Detective: tiny dependency-free SVG charts (bar, histogram, scatter, line).
   Every chart is drawn with DOM calls (textContent only), so data values can never inject HTML.
   Hover text lives in data-tip attributes; app.js shows it in one shared tooltip. */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    for (var k in (attrs || {})) { e.setAttribute(k, attrs[k]); }
    if (text != null) { e.textContent = text; }
    return e;
  }

  function fmt(v, d) {
    if (v == null || !isFinite(v)) { return '–'; }
    var a = Math.abs(v);
    if (a >= 1000) { return Math.round(v).toLocaleString('en-US'); }
    if (Number.isInteger(v)) { return String(v); }
    var dd = d != null ? d : (a >= 100 ? 0 : a >= 10 ? 1 : a >= 1 ? 2 : 3);
    return Number(v.toFixed(dd)).toString();
  }

  function niceNum(range, round) {
    var exp = Math.floor(Math.log10(range));
    var f = range / Math.pow(10, exp);
    var nf;
    if (round) { nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10; }
    else { nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10; }
    return nf * Math.pow(10, exp);
  }

  function niceScale(min, max, n) {
    n = n || 5;
    if (!(max > min)) { max = min + 1; }
    var range = niceNum(max - min, false);
    var step = niceNum(range / (n - 1), true);
    var lo = Math.floor(min / step) * step;
    var hi = Math.ceil(max / step) * step;
    var ticks = [];
    for (var v = lo; v <= hi + step / 2; v += step) { ticks.push(+v.toFixed(10)); }
    return { min: lo, max: hi, ticks: ticks };
  }

  function logScale(min, max) {
    var lo = Math.floor(Math.log10(min)), hi = Math.ceil(Math.log10(max));
    if (hi === lo) { hi = lo + 1; }
    var ticks = [];
    for (var k = lo; k <= hi; k++) { ticks.push(Math.pow(10, k)); }
    return { min: Math.pow(10, lo), max: Math.pow(10, hi), ticks: ticks, log: true };
  }

  function pos(sc, v, size) {
    if (sc.log) { return (Math.log10(v) - Math.log10(sc.min)) / (Math.log10(sc.max) - Math.log10(sc.min)) * size; }
    return (v - sc.min) / (sc.max - sc.min) * size;
  }

  function topRound(x, y, w, h, r) {
    r = Math.max(0, Math.min(r, h, w / 2));
    return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
  }

  function svgRoot(W, H, aria) {
    return el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': aria || 'Chart' });
  }

  function yAxis(svg, sc, m, W, H, label, tickFmt) {
    var ih = H - m.t - m.b;
    sc.ticks.forEach(function (t) {
      var y = m.t + ih - pos(sc, t, ih);
      svg.appendChild(el('line', { x1: m.l, x2: W - m.r, y1: y, y2: y, 'class': 'gridline' }));
      svg.appendChild(el('text', { x: m.l - 8, y: y + 4, 'text-anchor': 'end' }, (tickFmt || fmt)(t)));
    });
    if (label) {
      var cy = m.t + ih / 2;
      svg.appendChild(el('text', { x: 14, y: cy, 'text-anchor': 'middle', 'class': 'axis-title',
        transform: 'rotate(-90 14 ' + cy + ')' }, label));
    }
  }

  function xAxisNumeric(svg, sc, m, W, H, label, tickFmt) {
    var iw = W - m.l - m.r, base = H - m.b;
    svg.appendChild(el('line', { x1: m.l, x2: W - m.r, y1: base, y2: base, 'class': 'axisline' }));
    sc.ticks.forEach(function (t) {
      var x = m.l + pos(sc, t, iw);
      svg.appendChild(el('line', { x1: x, x2: x, y1: base, y2: base + 4, 'class': 'axisline' }));
      svg.appendChild(el('text', { x: x, y: base + 18, 'text-anchor': 'middle' }, (tickFmt || fmt)(t)));
    });
    if (label) { svg.appendChild(el('text', { x: m.l + iw / 2, y: H - 6, 'text-anchor': 'middle', 'class': 'axis-title' }, label)); }
  }

  function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  /* ------------------------------------------------------------ bar chart */
  function bar(container, o) {
    var items = o.items || [];
    var W = 680, rotate = items.length > 7;
    var m = { l: 58, r: 14, t: 20, b: rotate ? 112 : 78 }, H = rotate ? 380 : 340;
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var maxv = Math.max.apply(null, items.map(function (d) { return d.value; }).concat([0]));
    var sc = niceScale(0, maxv || 1);
    var svg = svgRoot(W, H, o.aria);
    yAxis(svg, sc, m, W, H, o.yLabel, o.tickFmt);
    svg.appendChild(el('line', { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, 'class': 'axisline' }));
    var band = iw / Math.max(items.length, 1), bw = Math.min(56, band * 0.62);
    items.forEach(function (d, i) {
      var x = m.l + band * i + (band - bw) / 2;
      var h = Math.max(0, pos(sc, d.value, ih)), y = m.t + ih - h;
      var tip = d.tip || (d.label + ': ' + fmt(d.value) + (d.n != null ? ' (n=' + fmt(d.n) + (d.few ? ', few ' + (o.noun || 'posts') : '') + ')' : ''));
      if (h > 0) {
        svg.appendChild(el('path', { d: topRound(x, y, bw, h, 4), 'class': 'bar' + (d.few ? ' few' : ''),
          tabindex: 0, 'data-tip': tip, 'aria-label': tip }));
      }
      svg.appendChild(el('text', { x: x + bw / 2, y: y - 6, 'text-anchor': 'middle', 'class': 'val' }, o.valFmt ? o.valFmt(d.value) : fmt(d.value)));
      var cx = x + bw / 2, by = m.t + ih;
      if (rotate) {
        var t = el('text', { x: cx, y: by + 14, 'text-anchor': 'end', transform: 'rotate(-35 ' + cx + ' ' + (by + 14) + ')' },
          trunc(d.label, 14) + (d.n != null ? ' (n=' + fmt(d.n) + ')' : ''));
        svg.appendChild(t);
      } else {
        svg.appendChild(el('text', { x: cx, y: by + 18, 'text-anchor': 'middle' }, trunc(d.label, 16)));
        if (d.n != null) { svg.appendChild(el('text', { x: cx, y: by + 34, 'text-anchor': 'middle', 'class': 'axis-title' }, 'n=' + fmt(d.n))); }
        if (d.few) { svg.appendChild(el('text', { x: cx, y: by + 50, 'text-anchor': 'middle', 'class': 'axis-title' }, 'few ' + (o.noun || 'posts'))); }
      }
    });
    if (o.xLabel) { svg.appendChild(el('text', { x: m.l + iw / 2, y: H - 6, 'text-anchor': 'middle', 'class': 'axis-title' }, o.xLabel)); }
    container.replaceChildren(svg);
  }

  /* ------------------------------------------------------------ histogram */
  function hist(container, o) {
    var edges = o.edges, counts = o.counts;
    var W = 680, H = 300, m = { l: 58, r: 14, t: 20, b: 56 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var xs = niceScale(edges[0], edges[edges.length - 1], 7);
    xs.min = Math.min(xs.min, edges[0]); xs.max = Math.max(xs.max, edges[edges.length - 1]);
    var ys = niceScale(0, Math.max.apply(null, counts.concat([1])));
    var svg = svgRoot(W, H, o.aria);
    yAxis(svg, ys, m, W, H, o.yLabel || 'Number of posts');
    counts.forEach(function (c, i) {
      var x0 = m.l + pos(xs, edges[i], iw), x1 = m.l + pos(xs, edges[i + 1], iw);
      var h = pos(ys, c, ih);
      if (h <= 0) { return; }
      var tip = fmt(edges[i]) + ' to ' + fmt(edges[i + 1]) + ': ' + fmt(c) + ' posts';
      svg.appendChild(el('rect', { x: x0 + 0.5, y: m.t + ih - h, width: Math.max(1, x1 - x0 - 1), height: h, 'class': 'bar',
        tabindex: 0, 'data-tip': tip, 'aria-label': tip }));
    });
    xAxisNumeric(svg, { min: xs.min, max: xs.max, ticks: xs.ticks.filter(function (t) { return t >= xs.min && t <= xs.max; }) },
      m, W, H, o.xLabel);
    if (o.median != null && o.median >= xs.min && o.median <= xs.max) {
      var mx = m.l + pos(xs, o.median, iw);
      svg.appendChild(el('line', { x1: mx, x2: mx, y1: m.t, y2: m.t + ih, 'class': 'medline' }));
      svg.appendChild(el('text', { x: mx + 5, y: m.t + 11, 'class': 'val' }, 'median ' + fmt(o.median)));
    }
    container.replaceChildren(svg);
  }

  /* ------------------------------------------------------------ scatter */
  function scatter(container, o) {
    var pts = o.points || [];
    var W = 680, H = 360, m = { l: 58, r: 16, t: 16, b: 56 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var xv = pts.map(function (p) { return p[0]; }), yv = pts.map(function (p) { return p[1]; });
    var xs = niceScale(Math.min.apply(null, xv.concat([0])), Math.max.apply(null, xv.concat([1])), 6);
    var ys = niceScale(Math.min.apply(null, yv.concat([0])), Math.max.apply(null, yv.concat([1])), 6);
    var svg = svgRoot(W, H, o.aria);
    yAxis(svg, ys, m, W, H, o.yLabel);
    xAxisNumeric(svg, xs, m, W, H, o.xLabel);
    pts.forEach(function (p) {
      var tip = o.xName + ' ' + fmt(p[0]) + ', ' + o.yName + ' ' + fmt(p[1]);
      svg.appendChild(el('circle', { cx: m.l + pos(xs, p[0], iw), cy: m.t + ih - pos(ys, p[1], ih), r: 3.2, 'class': 'dot', 'data-tip': tip }));
    });
    container.replaceChildren(svg);
  }

  /* ------------------------------------------------------------ line chart (optionally log-log) */
  function line(container, o) {
    var series = o.series || [];
    var W = 680, H = 340, m = { l: 62, r: 120, t: 20, b: 56 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var all = [];
    series.forEach(function (s) { s.points.forEach(function (p) { all.push(p); }); });
    var valid = all.filter(function (p) { return (!o.xLog || p.x > 0) && (!o.yLog || p.y > 0); });
    if (!valid.length) { container.textContent = 'No data to draw.'; return; }
    var xmin = Math.min.apply(null, valid.map(function (p) { return p.x; })), xmax = Math.max.apply(null, valid.map(function (p) { return p.x; }));
    var ymin = Math.min.apply(null, valid.map(function (p) { return p.y; })), ymax = Math.max.apply(null, valid.map(function (p) { return p.y; }));
    var xs = o.xLog ? logScale(xmin, xmax) : niceScale(xmin, xmax);
    var ys = o.yLog ? logScale(ymin, ymax) : niceScale(Math.min(0, ymin), ymax);
    var svg = svgRoot(W, H, o.aria);
    yAxis(svg, ys, m, W, H, o.yLabel, o.yFmt);
    xAxisNumeric(svg, xs, m, W, H, o.xLabel, o.xFmt);
    series.forEach(function (s, si) {
      var cls = String(si + 1), pts = s.points.filter(function (p) { return (!o.xLog || p.x > 0) && (!o.yLog || p.y > 0); })
        .sort(function (a, b) { return a.x - b.x; });
      if (!pts.length) { return; }
      var d = pts.map(function (p, i) {
        return (i ? 'L' : 'M') + (m.l + pos(xs, p.x, iw)).toFixed(1) + ',' + (m.t + ih - pos(ys, p.y, ih)).toFixed(1);
      }).join('');
      svg.appendChild(el('path', { d: d, 'class': 'line-' + cls }));
      pts.forEach(function (p) {
        var tip = s.name + ' at ' + (o.xTip ? o.xTip(p.x) : fmt(p.x)) + ': ' + (o.yFmt ? o.yFmt(p.y) : fmt(p.y));
        svg.appendChild(el('circle', { cx: m.l + pos(xs, p.x, iw), cy: m.t + ih - pos(ys, p.y, ih), r: 5, 'class': 'mark-' + cls,
          tabindex: 0, 'data-tip': tip, 'aria-label': tip }));
      });
      var last = pts[pts.length - 1];
      svg.appendChild(el('text', { x: m.l + pos(xs, last.x, iw) + 10, y: m.t + ih - pos(ys, last.y, ih) + 4, 'class': 'label-' + cls, 'font-weight': 600 }, s.name));
    });
    var legend = document.createElement('div');
    legend.className = 'legend';
    series.forEach(function (s, si) {
      var item = document.createElement('span');
      var sw = document.createElement('i'); sw.className = 's' + (si + 1);
      item.appendChild(sw); item.appendChild(document.createTextNode(s.name));
      legend.appendChild(item);
    });
    container.replaceChildren(legend, svg);
  }

  window.Charts = { bar: bar, hist: hist, scatter: scatter, line: line, fmt: fmt, niceScale: niceScale };
})();
