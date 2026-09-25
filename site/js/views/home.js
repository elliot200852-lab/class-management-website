/* views/home.js — 首頁：橫幅、最新 3 篇、行事曆、相簿條、專題活動卡片（docs/ARCHITECTURE.md §3.1）。

   讀：config/site（行事曆網址，只收公開日曆網址）、pages/home、posts.recent（limit 3）、
       albums.list、pages.byKind（fun）、comments.count。導師一律用 .teacher 版的查詢。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function section(cls, eyebrow, title, moreHref, moreText) {
    var s = el('section', 'section ' + cls);
    var head = el('div', 'section-head');
    var titles = el('div', 'section-head-titles');
    if (eyebrow) titles.appendChild(el('p', 'eyebrow', eyebrow));
    titles.appendChild(el('h2', 'section-title', title));
    head.appendChild(titles);
    if (moreHref) head.appendChild(C.dom.link(moreHref, 'section-link', moreText || '看全部'));
    s.appendChild(head);
    return s;
  }

  function banner(ctx) {
    var wrap = el('section', 'hero');
    var text = el('div', 'hero-text');
    text.appendChild(el('p', 'hero-eyebrow', 'Welcome'));
    text.appendChild(el('h1', 'hero-title', C.config().className || '我的班級'));
    var lead = el('p', 'hero-lead', '');
    text.appendChild(lead);
    wrap.appendChild(text);
    var frame = el('div', 'hero-photo');
    wrap.appendChild(frame);
    ctx.track(ctx.store.get(C.paths.page('home')).then(function (doc) {
      var data = doc && doc.data && doc.data.data ? doc.data.data : {};
      lead.textContent = data.bannerText || '歡迎來到我們的班級網站。';
      if (typeof data.bannerPid === 'string' && C.paths.RE.pid.test(data.bannerPid)) {
        var img = el('img');
        img.alt = '';
        frame.appendChild(img);
        frame.appendChild(el('span', 'tape tape--a'));
        C.photos.fill(img, ctx.store, doc.path, data.bannerPid, 'image', function () {
          frame.hidden = true;
        });
      } else {
        frame.hidden = true;
      }
    }, function () {
      lead.textContent = '歡迎來到我們的班級網站。';
      frame.hidden = true;
    }));
    return wrap;
  }

  function latest(ctx) {
    var s = section('section--latest', 'Latest', '最新紀事', C.route.href('blog'), '看全部紀事');
    var grid = el('div', 'entry-grid scatter');
    s.appendChild(grid);
    var name = ctx.session.roles.teacher ? 'posts.recent.teacher' : 'posts.recent';
    return ctx.store.query(name, { limit: 3 }).then(function (page) {
      if (!page.items.length) {
        grid.appendChild(el('p', 'empty', '還沒有紀事。'));
        return s;
      }
      page.items.forEach(function (doc, i) {
        grid.appendChild(C.cards.post(ctx, doc, { size: i === 0 ? 'feature' : 'normal' }));
      });
      return s;
    }, function (err) {
      s.appendChild(C.errors.box(err, { where: 'list' }));
      return s;
    });
  }

  function calendar(ctx) {
    var s = section('section--calendar', 'Calendar', '班級行事曆');
    var body = el('div', 'calendar-card');
    s.appendChild(body);
    ctx.track(ctx.siteInfo().then(function (info) {
      var u = C.text.safeUrl(info && info.calendarIcsUrl);
      if (!u) {
        body.appendChild(el('p', 'empty', '老師還沒有設定行事曆。'));
        return;
      }
      body.appendChild(el('p', 'calendar-lead', '把班級行事曆加進你的手機日曆，活動與放假日就會自動出現。'));
      // Google 日曆的「用網址新增」：cid 帶 webcal 形式的網址（連結本身仍是 https）
      var google = 'https://calendar.google.com/calendar/render?cid=' +
        encodeURIComponent('webcal://' + u.host + u.pathname + u.search);
      var row = el('div', 'calendar-actions');
      var a = C.text.extLink(google, '用 Google 日曆訂閱');
      if (a.nodeType === 1) a.className = 'btn btn--primary';
      row.appendChild(a);
      var copy = C.dom.button('btn', '複製行事曆網址', null);
      var msg = el('span', 'form-msg');
      msg.setAttribute('aria-live', 'polite');
      copy.addEventListener('click', function () {
        var done = function () { msg.textContent = '已複製。iPhone：設定 → 行事曆 → 帳號 → 加入帳號 → 其他 → 加入已訂閱的行事曆，貼上網址。'; };
        try {
          g.navigator.clipboard.writeText(u.href).then(done, function () { msg.textContent = u.href; });
        } catch (e) {
          msg.textContent = u.href;
        }
      });
      row.appendChild(copy);
      body.appendChild(row);
      body.appendChild(msg);
    }));
    return s;
  }

  function albums(ctx) {
    if (!C.layout.flagOn('gallery')) return null;
    var s = section('section--albums', 'Albums', '相簿', C.route.href('gallery'), '看全部相簿');
    var strip = el('div', 'album-strip');
    s.appendChild(strip);
    var name = ctx.session.roles.teacher ? 'albums.list.teacher' : 'albums.list';
    ctx.track(ctx.store.query(name, { limit: 12 }).then(function (page) {
      if (!page.items.length) {
        strip.appendChild(el('p', 'empty', '還沒有相簿。'));
        return;
      }
      page.items.forEach(function (doc) { strip.appendChild(C.cards.album(ctx, doc)); });
    }, function () { strip.appendChild(el('p', 'empty', '相簿暫時讀不到。')); }));
    return s;
  }

  function fun(ctx) {
    if (!C.layout.flagOn('fun')) return null;
    var s = section('section--fun', 'Projects', '專題活動', C.route.href('page', { id: 'fun' }), '看更多');
    var grid = el('div', 'fun-grid scatter');
    s.appendChild(grid);
    var name = ctx.session.roles.teacher ? 'pages.byKind.teacher' : 'pages.byKind';
    ctx.track(ctx.store.query(name, { kind: 'fun' }).then(function (page) {
      var n = 0;
      page.items.forEach(function (doc) {
        var cards = doc.data && doc.data.data && Array.isArray(doc.data.data.cards) ? doc.data.data.cards : [];
        cards.forEach(function (c) {
          if (n >= 3 || !c || typeof c !== 'object') return;
          grid.appendChild(C.cards.fun(ctx, doc, c, n));
          n++;
        });
      });
      if (!n) grid.appendChild(el('p', 'empty', '老師還沒有寫專題活動。'));
    }, function () { grid.appendChild(el('p', 'empty', '暫時讀不到。')); }));
    return s;
  }

  C.views.home = function (ctx) {
    var main = ctx.main;
    main.appendChild(banner(ctx));
    return latest(ctx).then(function (latestSection) {
      var container = el('div', 'container');
      C.dom.add(container, latestSection, calendar(ctx), albums(ctx), fun(ctx));
      main.appendChild(container);
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
