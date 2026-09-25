/* views/post.js — 單篇紀事 post.html?s=<slug>（docs/ARCHITECTURE.md §3.1）。

   讀：posts/{slug}、content/main、photoSrc、上一篇（posts.recent，after 目前這篇、limit 1）、
       下一篇（posts.newer）、comments.thread（即時）、markRead；導師另加 reads.all、parentMap.all。
   · 網址參數先經 CMW.paths 驗過；不合格式、不存在 → 「找不到」。
   · 讀者對單篇被拒（多半是已下架）→ 「這篇找不到（可能已下架）」，不說「沒有權限」。
   · 開過這一頁＝已讀（導師不寫回條）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function notFound(main, text) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, text || '這篇找不到（可能已下架或網址打錯了）。'));
    n.appendChild(C.dom.link(C.route.href('blog'), 'section-link', '回班級紀事'));
    box.appendChild(n);
    main.appendChild(box);
  }

  function shareButton(title, slug) {
    var wrap = el('div', 'share');
    var msg = el('span', 'form-msg');
    msg.setAttribute('aria-live', 'polite');
    var btn = C.dom.button('btn btn--small', '分享這一篇', function () {
      var url = C.route.absolute('post', { s: slug });
      var nav = g.navigator || {};
      if (typeof nav.share === 'function') {
        nav.share({ title: title, url: url }).catch(function () { /* 使用者取消 */ });
        return;
      }
      try {
        nav.clipboard.writeText(url).then(function () {
          msg.textContent = '連結已複製，可以貼到 LINE。只有登入的家長與老師打得開。';
        }, function () { msg.textContent = url; });
      } catch (e) {
        msg.textContent = url;
      }
    });
    C.dom.add(wrap, btn, msg);
    return wrap;
  }

  function readPanel(ctx, thread) {
    var box = el('details', 'read-panel');
    var sum = el('summary', 'read-panel-summary', '已讀：讀取中…');
    box.appendChild(sum);
    var body = el('div', 'read-panel-body');
    box.appendChild(body);
    ctx.track(Promise.all([ctx.store.query('reads.all', { thread: thread }), C.cards.parentMapItems(ctx)]).then(function (r) {
      var keys = C.readStats.parentKeys(r[1]);
      var st = C.readStats.postStats(r[0].items, keys);
      sum.textContent = C.readStats.label(st) + '（只有導師看得到）';
      var readSeats = [];
      var unreadSeats = [];
      r[1].forEach(function (m) {
        if (!keys[m.id]) return;
        var seats = (m.data.seats || []).join('、');
        (st.readKeys[m.id] ? readSeats : unreadSeats).push('座號 ' + seats + (m.data.relation ? '（' + m.data.relation + '）' : ''));
      });
      function row(label, list, cls) {
        var p = el('div', 'read-row');
        p.appendChild(el('p', 'read-row-label', label + '（' + list.length + '）'));
        var chips = el('div', 'read-chips');
        list.sort().forEach(function (t) { chips.appendChild(el('span', 'chip ' + cls, t)); });
        p.appendChild(chips);
        return p;
      }
      body.appendChild(row('還沒讀', unreadSeats, 'chip--unread'));
      body.appendChild(row('已讀', readSeats, 'chip--read'));
    }, function () { sum.textContent = '已讀：讀不到'; }));
    return box;
  }

  function prevNext(ctx, doc) {
    var nav = el('nav', 'post-nav');
    nav.setAttribute('aria-label', '上一篇與下一篇');
    var teacher = ctx.session.roles.teacher;
    var older = ctx.store.query(teacher ? 'posts.recent.teacher' : 'posts.recent', { limit: 1 }, { after: doc.cursor });
    var newer = ctx.store.query(teacher ? 'posts.newer.teacher' : 'posts.newer', {}, { before: doc.cursor });
    ctx.track(Promise.all([newer, older]).then(function (r) {
      var n = r[0].items[0];
      var o = r[1].items[0];
      if (n) {
        var a = C.dom.link(C.route.href('post', { s: n.id }), 'post-nav-link post-nav-newer');
        a.appendChild(el('span', 'post-nav-dir', '← 較新的一篇'));
        a.appendChild(el('span', 'post-nav-title', n.data.title || ''));
        nav.appendChild(a);
      }
      if (o) {
        var b = C.dom.link(C.route.href('post', { s: o.id }), 'post-nav-link post-nav-older');
        b.appendChild(el('span', 'post-nav-dir', '較早的一篇 →'));
        b.appendChild(el('span', 'post-nav-title', o.data.title || ''));
        nav.appendChild(b);
      }
    }, function () { /* 上一篇下一篇是附加的 */ }));
    return nav;
  }

  C.views.post = function (ctx) {
    var main = ctx.main;
    var slug = ctx.params.get('s') || '';
    if (!C.paths.isSlug(slug)) { notFound(main); return null; }
    var store = ctx.store;
    var postPath = C.paths.post(slug);
    var thread = C.paths.thread('post', slug);

    return store.get(postPath).then(function (doc) {
      if (!doc) { notFound(main); return null; }
      var x = doc.data;
      ctx.setTitle(x.title || '班級紀事');
      var art = el('article', 'post container container--narrow');
      var crumb = el('p', 'breadcrumb');
      crumb.appendChild(C.dom.link(C.route.href('blog'), null, '← 班級紀事'));
      art.appendChild(crumb);
      var head = el('header', 'post-head');
      var meta = el('div', 'entry-meta');
      var t = el('time', 'stamp-date', C.util.fmtDate(x.date));
      t.dateTime = String(x.date || '');
      meta.appendChild(t);
      if (x.category) meta.appendChild(C.dom.link(C.route.href('category', { c: x.category }), 'chip chip--cat', x.category));
      if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
      head.appendChild(meta);
      head.appendChild(el('h1', 'post-title', x.title || '（沒有標題）'));
      head.appendChild(shareButton(x.title || '', slug));
      art.appendChild(head);
      if (ctx.session.roles.teacher) art.appendChild(readPanel(ctx, thread));

      var bodyBox = el('div', 'post-body');
      bodyBox.appendChild(C.dom.loading());
      art.appendChild(bodyBox);
      main.appendChild(art);

      if (!ctx.session.roles.teacher) {
        store.markRead(thread).catch(function () { /* 已讀回條是附加的，失敗不打擾讀者 */ });
      }

      var content = store.get(C.paths.postContent(slug)).then(function (c) {
        C.dom.clear(bodyBox);
        var blocks = c && c.data ? c.data.blocks : null;
        if (!Array.isArray(blocks) || !blocks.length) {
          bodyBox.appendChild(el('p', 'empty', '這一篇沒有內文。'));
          return;
        }
        bodyBox.appendChild(C.blocks.render(blocks, { store: store, owner: postPath, demo: store.isDemo }));
      }, function (err) {
        C.dom.clear(bodyBox);
        bodyBox.appendChild(C.errors.box(err, { where: 'single' }));
      });
      ctx.track(content);

      art.appendChild(prevNext(ctx, doc));
      C.comments.mount(ctx, art, thread);
      return content;
    }, function (err) {
      var e = C.errors.from(err);
      if (e.code === 'denied' || e.code === 'invalid') { notFound(main, C.errors.message(e, 'single')); return null; }
      throw e;
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
