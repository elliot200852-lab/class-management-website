/* views/family-photos.js — 導師限定的個人照相簿（family-photos.html；docs/DATA-MODEL.md §2.18）。

   只有導師看得到：不是導師就只顯示一句說明，**一個查詢都不發**（安全規則本來就會擋）。
   讀：personalPhotos.all（每位孩子一份，照片 pid）、parentPhotos.all（家長合照：稱謂、備註、照片 pid）、
       roster/students（座號 → 稱呼）。格子只讀縮圖；點開才讀兩張顯示圖（孩子＋家長合照並排）。
   雲端不存家長姓名，只存稱謂（母、父……），稱謂來自老師電腦裡的 parent-roles.yaml。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function teacherOnly(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只有導師能用。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    main.appendChild(box);
    return null;
  }

  function firstPid(data) {
    var p = data && Array.isArray(data.photoPids) ? data.photoPids[0] : null;
    return typeof p === 'string' && C.paths.RE.pid.test(p) ? p : null;
  }

  /** 看大圖：孩子的個人照與家長合照並排。list：[{ seat, name, personal, parent }]；i：從第幾位開始 */
  function openViewer(store, list, i) {
    var d = g.document;
    var state = { i: i };
    var root = el('div', 'lightbox fp-viewer');
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', '看個人照與家長合照');
    var panes = el('div', 'fp-panes');
    var caption = el('p', 'fp-viewer-caption');
    var rel = el('p', 'fp-viewer-rel');
    var note = el('p', 'fp-viewer-note');
    var btnClose = C.dom.button('lightbox-btn lightbox-close', '✕', close);
    btnClose.setAttribute('aria-label', '關閉');
    var btnPrev = C.dom.button('lightbox-btn lightbox-prev', '‹', function () { show(state.i - 1); });
    btnPrev.setAttribute('aria-label', '上一位');
    var btnNext = C.dom.button('lightbox-btn lightbox-next', '›', function () { show(state.i + 1); });
    btnNext.setAttribute('aria-label', '下一位');
    if (list.length < 2) { btnPrev.hidden = true; btnNext.hidden = true; }
    C.dom.add(root, btnClose, panes, btnPrev, btnNext, caption, rel, note);

    function pane(owner, pid, label, emptyText) {
      var box = el('figure', 'fp-pane');
      var frame = el('div', 'fp-pane-photo');
      box.appendChild(frame);
      box.appendChild(el('figcaption', 'fp-pane-label', label));
      if (!pid) {
        frame.appendChild(el('p', 'fp-pane-empty', emptyText));
        return box;
      }
      frame.appendChild(el('p', 'lightbox-wait', '讀取中…'));
      var mine = state.i;
      C.photos.src(store, owner, pid, 'image').then(function (u) {
        if (state.i !== mine || !root.parentNode) return;
        C.dom.clear(frame);
        if (!u) { frame.appendChild(C.photos.missing()); return; }
        var img = d.createElement('img');
        img.alt = label;
        img.src = u;
        frame.appendChild(img);
      });
      return box;
    }

    function show(k) {
      var n = list.length;
      state.i = (k + n) % n;
      var it = list[state.i];
      C.dom.clear(panes);
      panes.appendChild(pane(C.paths.personalPhoto(it.seat), firstPid(it.personal), '個人照', '還沒有個人照'));
      panes.appendChild(pane(C.paths.parentPhoto(it.seat), firstPid(it.parent), '家長合照', '還沒有家長合照'));
      caption.textContent = '座號 ' + it.seat + (it.name ? '・' + it.name : '');
      var rels = it.parent && Array.isArray(it.parent.relations) ? it.parent.relations.filter(function (x) { return typeof x === 'string'; }) : [];
      rel.textContent = it.parent ? '家長合照：' + (rels.length ? rels.join('、') : '（沒有寫稱謂）') : '';
      note.textContent = it.parent && typeof it.parent.note === 'string' ? it.parent.note : '';
      note.hidden = !note.textContent;
    }

    function onKey(e) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') show(state.i - 1);
      else if (e.key === 'ArrowRight') show(state.i + 1);
    }
    function close() {
      d.removeEventListener('keydown', onKey);
      if (root.parentNode) root.parentNode.removeChild(root);
      d.documentElement.classList.remove('has-lightbox');
    }
    root.addEventListener('click', function (e) { if (e.target === root || e.target === panes) close(); });
    d.addEventListener('keydown', onKey);
    d.body.appendChild(root);
    d.documentElement.classList.add('has-lightbox');
    show(i);
    btnClose.focus();
    return close;
  }

  C.views['family-photos'] = function (ctx) {
    if (!ctx.session.roles.teacher) return teacherOnly(ctx.main);
    var store = ctx.store;
    var box = el('div', 'container');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Private album・導師限定'));
    head.appendChild(el('h1', 'page-title', '個人照'));
    head.appendChild(el('p', 'page-dek', '只有導師看得到（家長與同仁都讀不到）。點一位孩子，旁邊會並排家長合照。'));
    box.appendChild(head);
    var summary = el('p', 'mc-summary');
    var grid = el('div', 'fp-grid');
    grid.appendChild(C.dom.loading());
    C.dom.add(box, summary, grid);
    ctx.main.appendChild(box);
    var closeViewer = null;
    ctx.onCleanup(function () { if (closeViewer) closeViewer(); });

    return Promise.all([
      store.query('personalPhotos.all'),
      store.query('parentPhotos.all'),
      store.get(C.paths.rosterStudents()).then(function (d) { return d && d.data ? d.data.students || [] : []; },
        function () { return []; })
    ]).then(function (r) {
      var personal = {};
      var parent = {};
      r[0].items.forEach(function (x) { if (C.seats.valid(x.id)) personal[x.id] = x.data || {}; });
      r[1].items.forEach(function (x) { if (C.seats.valid(x.id)) parent[x.id] = x.data || {}; });
      var names = {};
      var seats = [];
      r[2].forEach(function (s) {
        if (s && C.seats.valid(s.seat)) { names[s.seat] = s.displayName || s.name || ''; seats.push(s.seat); }
      });
      Object.keys(personal).concat(Object.keys(parent)).forEach(function (s) { if (seats.indexOf(s) < 0) seats.push(s); });
      seats.sort();
      C.dom.clear(grid);
      if (!seats.length) {
        grid.appendChild(el('p', 'notice', '還沒有名冊，也還沒有任何個人照。請 AI 助理照「個人照」劇本把照片放上來。'));
        return;
      }
      var list = seats.map(function (s) { return { seat: s, name: names[s] || '', personal: personal[s] || null, parent: parent[s] || null }; });
      list.forEach(function (it, i) {
        var card = C.dom.button('fp-card', '', function () { closeViewer = openViewer(store, list, i); });
        card.setAttribute('data-seat', it.seat);
        var photo = el('span', 'fp-photo');
        var pid = firstPid(it.personal);
        if (pid) {
          var img = g.document.createElement('img');
          img.alt = '';
          img.loading = 'lazy';
          photo.appendChild(img);
          C.photos.fill(img, store, C.paths.personalPhoto(it.seat), pid, 'thumb', function () {
            C.dom.clear(photo);
            photo.appendChild(el('span', 'fp-photo-empty', '照片讀不到'));
          });
        } else {
          photo.appendChild(el('span', 'fp-photo-empty', '還沒有個人照'));
          card.className += ' is-empty';
        }
        card.appendChild(photo);
        var cap = el('span', 'fp-cap');
        cap.appendChild(el('span', 'fp-seat', '座號 ' + it.seat));
        cap.appendChild(el('span', 'fp-name', it.name || '（名冊沒有這一號）'));
        if (it.parent) cap.appendChild(el('span', 'chip chip--parent', '家長合照'));
        card.appendChild(cap);
        card.setAttribute('aria-label', '座號 ' + it.seat + ' ' + it.name + (it.parent ? '（有家長合照）' : ''));
        grid.appendChild(card);
      });
      summary.textContent = '個人照 ' + Object.keys(personal).length + ' 位、家長合照 ' + Object.keys(parent).length +
        ' 位（名冊 ' + r[2].length + ' 位）。';
    }, function (err) {
      C.dom.clear(grid);
      grid.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };

  C.familyPhotos = { firstPid: firstPid };
})(typeof window !== 'undefined' ? window : globalThis);
