/* views/seating.js — 導師專用頁的「座位表」分頁（teacher.html#/seating；docs/DATA-MODEL.md §2.18）。

   讀：seating.all（全部方案，只有導師讀得到）＋ roster/students（座號 → 稱呼）。雲端的座位表只存座號，
   名字由這一頁當場用名冊補上；名冊對不到就顯示座號，不會留白。
   畫：SVG 全部由程式產生（createElementNS＋setAttribute，不解析任何字串）。
     · 第一排＝最靠黑板；每一排置中對齊；"-"＝走道（不畫）、""＝空位（虛線空桌）。
     · 兩種方向：老師站在講台看（黑板在下，預設）／學生面向黑板看（黑板在上）。兩者是 180 度旋轉，左右也跟著對調。
   互動：切換方案、切換方向（記在這台裝置）、點一個座位標記起來（再點一次取消）、列印（只印座位表，A4 橫式）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var NS = 'http://www.w3.org/2000/svg';
  var AISLE = '-';
  var G = { cw: 104, ch: 66, gx: 12, gy: 26, m: 28, boardH: 34, boardGap: 26, boardW: 320 };
  var VIEW_KEY = 'cmw-seating-view';

  /** 座位的幾何位置（純函式，測試直接呼叫）。rows：[[座號或 '' 或 '-']]；teacherView：黑板在下。 */
  function layout(rows, teacherView) {
    rows = Array.isArray(rows) ? rows : [];
    var cols = 1;
    rows.forEach(function (r) { if (Array.isArray(r) && r.length > cols) cols = r.length; });
    var step = G.cw + G.gx;
    var w = 2 * G.m + cols * G.cw + (cols - 1) * G.gx;
    var top = G.m + G.boardH + G.boardGap;
    var h = top + rows.length * G.ch + Math.max(0, rows.length - 1) * G.gy + G.m;
    var bw = Math.min(G.boardW, w - 2 * G.m);
    var board = { x: (w - bw) / 2, y: G.m, w: bw, h: G.boardH };
    var cells = [];
    rows.forEach(function (row, r) {
      if (!Array.isArray(row)) return;
      var offset = (cols - row.length) * step / 2;
      row.forEach(function (s, i) {
        if (s === AISLE) return;
        cells.push({ seat: s, kind: s ? 'seat' : 'empty', row: r, col: i,
          x: G.m + offset + i * step, y: top + r * (G.ch + G.gy) });
      });
    });
    if (teacherView) {
      cells.forEach(function (c) { c.x = w - c.x - G.cw; c.y = h - c.y - G.ch; });
      board.x = w - board.x - board.w;
      board.y = h - board.y - board.h;
    }
    return { w: w, h: h, cw: G.cw, ch: G.ch, board: board, cells: cells };
  }

  /** 方案清單（新的在前）裡「今天在用」的那一個：起用日期 ≤ 今天的最新一個；都還沒到就拿最早的。 */
  function pickCurrent(plans, today) {
    for (var i = 0; i < plans.length; i++) {
      if (String(plans[i].data.date || '') <= today) return plans[i];
    }
    return plans.length ? plans[plans.length - 1] : null;
  }

  function rowsOf(data) {
    return (Array.isArray(data && data.rows) ? data.rows : []).map(function (r) {
      return r && Array.isArray(r.seats) ? r.seats.filter(function (s) { return typeof s === 'string'; }) : [];
    });
  }

  function svgEl(tag, attrs, text) {
    var e = g.document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, String(attrs[k])); });
    if (text !== undefined) e.textContent = String(text);
    return e;
  }

  function nameSize(name) {
    var n = Array.from(String(name)).length;
    if (n <= 3) return 20;
    if (n <= 5) return 17;
    return 14;
  }

  /** 一張座位表的 SVG。names：{座號: 稱呼} */
  function drawSvg(data, names, teacherView, title) {
    var L = layout(rowsOf(data), teacherView);
    var svg = svgEl('svg', { viewBox: '0 0 ' + L.w + ' ' + L.h, 'class': 'seating-svg', role: 'img' });
    svg.appendChild(svgEl('title', {}, title || '座位表'));
    svg.appendChild(svgEl('rect', { x: 1, y: 1, width: L.w - 2, height: L.h - 2, rx: 10, 'class': 'seat-room' }));
    svg.appendChild(svgEl('rect', { x: L.board.x, y: L.board.y, width: L.board.w, height: L.board.h, rx: 4, 'class': 'seat-board' }));
    svg.appendChild(svgEl('text', { x: L.board.x + L.board.w / 2, y: L.board.y + L.board.h / 2 + 6, 'text-anchor': 'middle',
      'class': 'seat-board-label' }, '黑　板'));
    L.cells.forEach(function (c) {
      var grp = svgEl('g', { 'class': 'seat-card seat-card--' + c.kind, 'data-seat': c.seat || '' });
      grp.appendChild(svgEl('rect', { x: c.x, y: c.y, width: L.cw, height: L.ch, rx: 8, 'class': 'seat-desk' }));
      if (c.kind === 'seat') {
        grp.appendChild(svgEl('text', { x: c.x + 8, y: c.y + 16, 'class': 'seat-no' }, c.seat));
        var name = names[c.seat] || '座號 ' + c.seat;
        var size = nameSize(name);
        var t = svgEl('text', { x: c.x + L.cw / 2, y: c.y + L.ch / 2 + size / 2 + 6, 'text-anchor': 'middle',
          'class': 'seat-name', 'font-size': size }, name);
        if (Array.from(name).length > 6) {
          t.setAttribute('textLength', String(L.cw - 14));
          t.setAttribute('lengthAdjust', 'spacingAndGlyphs');
        }
        grp.appendChild(t);
        grp.setAttribute('tabindex', '0');
        grp.setAttribute('role', 'button');
        grp.setAttribute('aria-label', '座號 ' + c.seat + ' ' + (names[c.seat] || ''));
      } else {
        grp.appendChild(svgEl('text', { x: c.x + L.cw / 2, y: c.y + L.ch / 2 + 5, 'text-anchor': 'middle',
          'class': 'seat-empty-label' }, '空位'));
      }
      svg.appendChild(grp);
    });
    return svg;
  }

  function counts(data) {
    var n = 0;
    var e = 0;
    rowsOf(data).forEach(function (r) {
      r.forEach(function (s) { if (s === '') e++; else if (s !== AISLE) n++; });
    });
    return { seats: n, empty: e };
  }

  function lsGet(k) { try { return g.localStorage ? g.localStorage.getItem(k) : null; } catch (e) { return null; } }
  function lsSet(k, v) { try { if (g.localStorage) g.localStorage.setItem(k, v); } catch (e) { /* 忽略 */ } }

  /** 在 box 裡畫座位表分頁（teacher.js 呼叫）。回 Promise。 */
  function render(ctx, box) {
    var store = ctx.store;
    var holder = el('div', 'seating');
    holder.appendChild(C.dom.loading());
    box.appendChild(holder);
    var root = g.document.documentElement;
    root.classList.add('cmw-print-seating');
    ctx.onCleanup(function () { root.classList.remove('cmw-print-seating'); });
    return Promise.all([
      store.query('seating.all'),
      store.get(C.paths.rosterStudents()).then(function (d) { return d && d.data ? d.data.students || [] : []; },
        function () { return []; })
    ]).then(function (r) {
      C.dom.clear(holder);
      var plans = r[0].items.filter(function (p) { return p.data && Array.isArray(p.data.rows); });
      var names = {};
      r[1].forEach(function (s) { if (s && C.seats.valid(s.seat)) names[s.seat] = s.displayName || s.name || ''; });
      if (!plans.length) {
        var n = el('div', 'notice');
        n.appendChild(el('p', null, '還沒有座位表。'));
        n.appendChild(el('p', null, '跟 AI 助理說「排座位」或「上傳座位表」，它會照劇本幫你把排好的座位寫成檔案、給你看過再放上來。' +
          '只有你看得到座位表。'));
        holder.appendChild(n);
        return;
      }
      var current = pickCurrent(plans, C.util.today());
      var teacherView = lsGet(VIEW_KEY) !== 'student';

      var controls = el('div', 'seating-controls no-print');
      var planNav = el('div', 'seating-plans');
      planNav.setAttribute('role', 'group');
      planNav.setAttribute('aria-label', '座位方案');
      var viewNav = el('div', 'seating-views');
      viewNav.setAttribute('role', 'group');
      viewNav.setAttribute('aria-label', '看的方向');
      var printBtn = C.dom.button('btn btn--small', '列印座位表', function () { g.print(); });
      C.dom.add(controls, planNav, viewNav, printBtn);
      var sheet = el('div', 'seating-print');
      C.dom.add(holder, controls, sheet);

      function draw() {
        C.dom.clear(planNav);
        plans.forEach(function (p) {
          var b = C.dom.button('chip seating-plan-btn' + (p === current ? ' is-current' : ''),
            (p.data.title || p.id) + '（' + (p.data.date || '') + ' 起）', function () { current = p; draw(); });
          b.setAttribute('aria-pressed', p === current ? 'true' : 'false');
          b.setAttribute('data-plan', p.id);
          planNav.appendChild(b);
        });
        C.dom.clear(viewNav);
        [[true, '老師站在講台看（黑板在下）'], [false, '學生面向黑板看（黑板在上）']].forEach(function (v) {
          var b = C.dom.button('chip seating-view-btn' + (teacherView === v[0] ? ' is-current' : ''), v[1], function () {
            teacherView = v[0];
            lsSet(VIEW_KEY, teacherView ? 'teacher' : 'student');
            draw();
          });
          b.setAttribute('aria-pressed', teacherView === v[0] ? 'true' : 'false');
          b.setAttribute('data-view', v[0] ? 'teacher' : 'student');
          viewNav.appendChild(b);
        });
        C.dom.clear(sheet);
        var d = current.data;
        var cnt = counts(d);
        sheet.appendChild(el('h2', 'seating-title', d.title || current.id));
        sheet.appendChild(el('p', 'seating-meta', (d.date || '') + ' 起用・學生 ' + cnt.seats + ' 位' +
          (cnt.empty ? '・空位 ' + cnt.empty : '') + '・' + (teacherView ? '老師站在講台看' : '學生面向黑板看')));
        var svg = drawSvg(d, names, teacherView, d.title);
        var toggle = function (e) {
          var t = e.target;
          while (t && t !== svg && !(t.getAttribute && /\bseat-card--seat\b/.test(t.getAttribute('class') || ''))) t = t.parentNode;
          if (!t || t === svg) return;
          var cls = t.getAttribute('class') || '';
          t.setAttribute('class', /\bis-picked\b/.test(cls) ? cls.replace(/\s*is-picked\b/, '') : cls + ' is-picked');
        };
        svg.addEventListener('click', toggle);
        svg.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(e); }
        });
        var frame = el('div', 'seating-frame');
        frame.appendChild(svg);
        sheet.appendChild(frame);
        if (d.note) sheet.appendChild(el('p', 'seating-note', d.note));
      }
      draw();
    }, function (err) {
      C.dom.clear(holder);
      holder.appendChild(C.errors.box(err, { where: 'list' }));
    });
  }

  C.seating = { layout: layout, pickCurrent: pickCurrent, counts: counts, render: render, AISLE: AISLE };
})(typeof window !== 'undefined' ? window : globalThis);
