/* views/page.js — 單頁 page.html?id=<pageId>：關於我們、專題活動、行事曆、課表、獨立單頁（docs/ARCHITECTURE.md §3.1）。

   讀：pages/{pageId}、photos.thumbs（有照片時；點開看大圖）。依 kind 畫 data：
     fun → 卡片；schedule → 表格；calendar → 活動清單；course → 說明卡。正文一律走 CMW.blocks。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function notFound(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁找不到（可能還沒建立，或網址打錯了）。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    main.appendChild(box);
  }

  function arr(v) { return Array.isArray(v) ? v : []; }

  function funCards(ctx, doc, data) {
    var grid = el('div', 'fun-grid scatter');
    arr(data.cards).forEach(function (c, i) {
      if (c && typeof c === 'object') grid.appendChild(C.cards.fun(ctx, doc, c, i));
    });
    return grid;
  }

  function events(data) {
    var ul = el('ul', 'event-list');
    arr(data.events).forEach(function (e) {
      if (!e) return;
      var li = el('li');
      li.appendChild(el('time', 'stamp-date', C.util.fmtStamp(e.date)));
      li.appendChild(el('span', 'event-title', e.title || ''));
      ul.appendChild(li);
    });
    if (!ul.firstChild) ul.appendChild(el('li', 'empty', '目前沒有活動。'));
    return ul;
  }

  function course(data) {
    var wrap = el('div', 'course-cards');
    arr(data.cards).forEach(function (c) {
      if (!c) return;
      var art = el('article', 'fun-card');
      art.appendChild(el('h3', 'fun-title', c.title || ''));
      if (c.text) {
        var p = el('p', 'fun-text');
        p.appendChild(C.text.render(c.text));
        art.appendChild(p);
      }
      if (c.url) art.appendChild(C.text.extLink(c.url, '看更多'));
      wrap.appendChild(art);
    });
    arr(data.videos).forEach(function (v) {
      if (v && v.url) wrap.appendChild(C.blocks.render([{ t: 'video', url: v.url, title: v.title }], { demo: C.getStore().isDemo }));
    });
    return wrap;
  }

  function photoGrid(ctx, doc) {
    var sec = el('section', 'page-photos');
    sec.hidden = true;
    var grid = el('div', 'thumb-grid');
    sec.appendChild(el('h2', 'section-title section-title--small', '照片'));
    sec.appendChild(grid);
    ctx.track(ctx.store.query('photos.thumbs', { owner: doc.path }).then(function (page) {
      if (!page.items.length) return;
      sec.hidden = false;
      var items = page.items.map(function (t) { return { owner: doc.path, pid: t.id, caption: t.data.caption || '' }; });
      items.forEach(function (it, i) {
        var b = el('button', 'thumb');
        b.type = 'button';
        b.setAttribute('aria-label', '看大圖' + (it.caption ? '：' + it.caption : ''));
        var img = el('img');
        img.alt = it.caption || '';
        img.loading = 'lazy';
        b.appendChild(img);
        C.photos.fill(img, ctx.store, doc.path, it.pid, 'thumb');
        b.addEventListener('click', function () { C.lightbox.open(ctx.store, items, i); });
        grid.appendChild(b);
      });
    }, function () { /* 照片是附加的 */ }));
    return sec;
  }

  C.views.page = function (ctx) {
    var main = ctx.main;
    var id = ctx.params.get('id') || '';
    if (!C.paths.isPageId(id)) { notFound(main); return null; }
    var path = C.paths.page(id);
    return ctx.store.get(path).then(function (doc) {
      if (!doc) { notFound(main); return; }
      var x = doc.data || {};
      ctx.setTitle(x.title || '');
      var art = el('article', 'single-page container container--narrow kind-' + (x.kind || 'standalone'));
      var head = el('header', 'page-header');
      head.appendChild(el('h1', 'page-title', x.title || ''));
      if (x.visible === false) head.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
      art.appendChild(head);
      if (Array.isArray(x.blocks) && x.blocks.length) {
        var body = el('div', 'post-body');
        body.appendChild(C.blocks.render(x.blocks, { store: ctx.store, owner: path, demo: ctx.store.isDemo }));
        art.appendChild(body);
      }
      var data = x.data && typeof x.data === 'object' ? x.data : {};
      if (x.kind === 'fun') art.appendChild(funCards(ctx, doc, data));
      else if (x.kind === 'schedule') art.appendChild(C.cards.schedule(data));
      else if (x.kind === 'calendar') art.appendChild(events(data));
      else if (x.kind === 'course') art.appendChild(course(data));
      else if (x.kind === 'home' && data.bannerText) art.appendChild(el('p', 'hero-lead', data.bannerText));
      if (x.kind !== 'fun') art.appendChild(photoGrid(ctx, doc));
      main.appendChild(art);
    }, function (err) {
      var e = C.errors.from(err);
      if (e.code === 'denied' || e.code === 'invalid') { notFound(main); return; }
      throw e;
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
