/* cards.js — 列表卡片（首頁、紀事列表、分類頁共用）：紀事卡、私密紀事鎖頭卡、相簿卡、專題活動卡。

   卡片上的附加資訊（留言數、導師的已讀徽章）是非必要的：讀不到就靜默不顯示（ARCHITECTURE §2.6）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  /** 導師看的「純家長集合」與私密名單：同一次畫面只讀一次 */
  function parentMapItems(ctx) {
    return ctx.shared('parentMapItems', function () {
      return ctx.store.query('parentMap.all').then(function (p) { return p.items; });
    });
  }
  function parentKeys(ctx) {
    return parentMapItems(ctx).then(function (items) { return C.readStats.parentKeys(items); });
  }
  function privateAllow(ctx) {
    return ctx.shared('privateAllow', function () {
      return ctx.store.query('privateAllowlist.all').then(function (p) { return p.items; });
    });
  }

  function commentBadge(ctx, thread) {
    var span = el('span', 'badge badge--comments');
    span.hidden = true;
    ctx.track(ctx.store.count('comments.count', { thread: thread }).then(function (n) {
      if (n > 0) {
        span.textContent = '留言 ' + n;
        span.hidden = false;
      }
    }, function () { /* 附加資訊，讀不到就不顯示 */ }));
    return span;
  }

  function readBadge(ctx, thread, isPrivate) {
    var span = el('span', 'badge badge--read');
    span.hidden = true;
    var p;
    if (isPrivate) {
      p = Promise.all([ctx.store.count('reads.count', { thread: thread }), privateAllow(ctx)]).then(function (r) {
        return C.readStats.privateStats(r[0], r[1], ctx.session.user && ctx.session.user.emailKey);
      });
    } else {
      p = Promise.all([ctx.store.count('reads.countParents', { thread: thread }), parentKeys(ctx)]).then(function (r) {
        return C.readStats.cardStats(r[0], r[1]);
      });
    }
    ctx.track(p.then(function (st) {
      span.textContent = C.readStats.label(st);
      span.title = '導師才看得到';
      span.hidden = false;
    }, function () { /* 靜默 */ }));
    return span;
  }

  function stamp(date) {
    var t = el('time', 'stamp-date', C.util.fmtStamp(date));
    t.dateTime = String(date || '');
    return t;
  }

  /** 班級紀事卡片。doc：posts.recent 的一筆；opts.size：'feature'｜'normal' */
  function post(ctx, doc, opts) {
    opts = opts || {};
    var x = doc.data || {};
    var slug = doc.id;
    var thread = C.paths.thread('post', slug);
    var href = C.route.href('post', { s: slug });
    var art = el('article', 'entry' + (opts.size === 'feature' ? ' entry--feature' : ''));
    var media = C.dom.link(href, 'entry-media-link');
    media.setAttribute('aria-hidden', 'true');
    media.tabIndex = -1;
    media.appendChild(C.photos.coverBox(ctx.store, doc.path, x, 'entry-media'));
    art.appendChild(media);
    var meta = el('div', 'entry-meta');
    meta.appendChild(stamp(x.date));
    if (x.category) {
      meta.appendChild(C.dom.link(C.route.href('category', { c: x.category }), 'chip chip--cat', x.category));
    }
    if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架'));
    meta.appendChild(commentBadge(ctx, thread));
    if (ctx.session.roles.teacher) meta.appendChild(readBadge(ctx, thread, false));
    art.appendChild(meta);
    var h = el(opts.headingTag || 'h3', 'entry-title');
    h.appendChild(C.dom.link(href, null, x.title || '（沒有標題）'));
    art.appendChild(h);
    if (x.excerpt) art.appendChild(el('p', 'entry-excerpt', C.text.excerpt(x.excerpt, 200)));
    art.appendChild(C.dom.link(href, 'read-more', '讀全文'));
    return art;
  }

  /** 私密紀事的鎖頭卡（只有私密讀者與導師的畫面會出現） */
  function privatePost(ctx, doc) {
    var x = doc.data || {};
    var href = C.route.href('private', { p: doc.id });
    var art = el('article', 'entry entry--private');
    var meta = el('div', 'entry-meta');
    meta.appendChild(stamp(x.date));
    meta.appendChild(el('span', 'chip chip--lock', '🔒 私密紀事'));
    if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架'));
    var thread = C.paths.thread('private', doc.id);
    meta.appendChild(commentBadge(ctx, thread));
    if (ctx.session.roles.teacher) meta.appendChild(readBadge(ctx, thread, true));
    art.appendChild(meta);
    var h = el('h3', 'entry-title');
    h.appendChild(C.dom.link(href, null, x.title || '（沒有標題）'));
    art.appendChild(h);
    if (x.excerpt) art.appendChild(el('p', 'entry-excerpt', C.text.excerpt(x.excerpt, 200)));
    art.appendChild(el('p', 'entry-private-note', '只有私密名單裡的家長與老師看得到這一篇。'));
    art.appendChild(C.dom.link(href, 'read-more', '讀全文'));
    return art;
  }

  /** 相簿卡（首頁相簿條、相簿列表） */
  function album(ctx, doc) {
    var x = doc.data || {};
    var href = C.route.href('album', { a: doc.id });
    var a = C.dom.link(href, 'album-card');
    var empty = !(x.photoCount > 0) && !x.linkUrl;
    if (empty) {
      var ph = el('div', 'album-cover is-empty');
      ph.appendChild(el('span', 'album-empty-text', '尚未設定相簿連結'));
      a.appendChild(ph);
    } else {
      a.appendChild(C.photos.coverBox(ctx.store, doc.path, x, 'album-cover'));
    }
    var label = el('span', 'album-label');
    label.appendChild(el('span', 'album-title', x.title || '（沒有標題）'));
    label.appendChild(el('span', 'album-meta', C.util.fmtStamp(x.date) + (x.photoCount > 0 ? '・' + x.photoCount + ' 張' : '')));
    if (x.visible === false) label.appendChild(el('span', 'chip chip--hidden', '已下架'));
    a.appendChild(label);
    return a;
  }

  /** 專題活動卡片（pages 的 data.cards） */
  function fun(ctx, pageDoc, c, i) {
    var art = el('article', 'fun-card');
    if (typeof c.pid === 'string' && C.paths.RE.pid.test(c.pid)) {
      var box = el('div', 'fun-media');
      var img = el('img');
      img.alt = '';
      img.loading = 'lazy';
      box.appendChild(img);
      C.photos.fill(img, ctx.store, pageDoc.path, c.pid, 'thumb', function () {
        box.replaceChild(C.photos.missing('沒有照片'), img);
      });
      art.appendChild(box);
    }
    art.appendChild(el('h3', 'fun-title', c.title || ''));
    if (c.text) {
      var p = el('p', 'fun-text');
      p.appendChild(C.text.render(c.text));
      art.appendChild(p);
    }
    art.setAttribute('data-n', String((i % 3) + 1));
    return art;
  }

  /** 課表（pages 的 kind: 'schedule'，data.rows＝[{ cells: [字串] }]）：第一列與第一欄是表頭 */
  function schedule(data) {
    var rows = data && Array.isArray(data.rows) ? data.rows : [];
    var wrap = el('div', 'table-wrap');
    var table = el('table', 'schedule');
    rows.forEach(function (r, i) {
      var tr = el('tr');
      (r && Array.isArray(r.cells) ? r.cells : []).forEach(function (cell, j) {
        tr.appendChild(el(i === 0 || j === 0 ? 'th' : 'td', null, String(cell === null || cell === undefined ? '' : cell)));
      });
      table.appendChild(tr);
    });
    wrap.appendChild(table);
    return wrap;
  }

  C.cards = {
    post: post, privatePost: privatePost, album: album, fun: fun, schedule: schedule,
    parentMapItems: parentMapItems, parentKeys: parentKeys, privateAllow: privateAllow
  };
})(typeof window !== 'undefined' ? window : globalThis);
