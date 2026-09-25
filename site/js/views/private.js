/* views/private.js — 私密紀事 private.html（列表）與 private.html?p=<slug>（單篇）（docs/DATA-MODEL.md §2.10）。

   · 只有私密讀者與導師：畫面判斷 Session 沒有私密讀者身分 → 只說「這一頁只給私密名單」，**一個查詢都不發**。
     這一句話對「有沒有私密紀事、有幾篇」不透露任何資訊；真正的門是安全規則。
   · 列表：private.list（導師 .teacher 版）。一般紀事列表也會用同一種鎖頭卡把它們依日期併進去（views/blog.js）。
   · 單篇：private_posts/{slug}（摘要與正文同一份）、照片、留言（門票：私密讀者）、開過＝已讀；
     導師另看已讀 X/N（N＝私密名單人數扣掉導師，DATA-MODEL §2.8）。
   · 分頁標題固定是「私密紀事」，不放任何一篇的標題（瀏覽紀錄、分享畫面都不會露出來）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function onlyForPrivate(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只給私密名單裡的家長與老師。'));
    n.appendChild(C.dom.link(C.route.href('blog'), 'section-link', '回班級紀事'));
    box.appendChild(n);
    main.appendChild(box);
  }

  function notFound(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這篇找不到（可能已下架或網址打錯了）。'));
    n.appendChild(C.dom.link(C.route.href('private'), 'section-link', '回私密紀事'));
    box.appendChild(n);
    main.appendChild(box);
  }

  function list(ctx) {
    var container = el('div', 'container container--narrow');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Private notes'));
    head.appendChild(el('h1', 'page-title', '私密紀事'));
    head.appendChild(el('p', 'page-dek', '只有私密名單裡的家長與老師看得到這裡的文章。'));
    container.appendChild(head);
    var stack = el('div', 'entry-stack scatter');
    container.appendChild(stack);
    ctx.main.appendChild(container);
    var name = ctx.session.roles.teacher ? 'private.list.teacher' : 'private.list';
    return ctx.store.query(name).then(function (page) {
      if (!page.items.length) {
        stack.appendChild(el('p', 'empty', '目前沒有私密紀事。'));
        return;
      }
      page.items.forEach(function (doc) { stack.appendChild(C.cards.privatePost(ctx, doc)); });
    }, function (err) {
      C.dom.clear(stack);
      stack.appendChild(C.errors.box(err, { where: 'list' }));
    });
  }

  /** 導師看的已讀：X/N＋誰還沒讀（用座號與稱謂表示，不顯示信箱） */
  function readPanel(ctx, thread) {
    var box = el('details', 'read-panel');
    var sum = el('summary', 'read-panel-summary', '已讀：讀取中…');
    box.appendChild(sum);
    var body = el('div', 'read-panel-body');
    box.appendChild(body);
    var teacherKey = ctx.session.user && ctx.session.user.emailKey;
    ctx.track(Promise.all([
      ctx.store.query('reads.all', { thread: thread }),
      C.cards.privateAllow(ctx),
      C.cards.parentMapItems(ctx)
    ]).then(function (r) {
      var readKeys = {};
      r[0].items.forEach(function (d) { readKeys[d.id] = true; });
      var members = r[1].filter(function (d) { return d.id !== teacherKey; });
      var st = C.readStats.privateStats(r[0].items.length, r[1], teacherKey);
      sum.textContent = C.readStats.label(st) + '（只有導師看得到）';
      var mapByKey = {};
      r[2].forEach(function (m) { mapByKey[m.id] = m.data || {}; });
      var readList = [];
      var unreadList = [];
      members.forEach(function (d) {
        var m = mapByKey[d.id];
        var label = m && Array.isArray(m.seats) && m.seats.length
          ? '座號 ' + m.seats.join('、') + (m.relation ? '（' + m.relation + '）' : '')
          : '名單成員';
        (readKeys[d.id] ? readList : unreadList).push(label);
      });
      function row(label, arr, cls) {
        var p = el('div', 'read-row');
        p.appendChild(el('p', 'read-row-label', label + '（' + arr.length + '）'));
        var chips = el('div', 'read-chips');
        arr.sort().forEach(function (t) { chips.appendChild(el('span', 'chip ' + cls, t)); });
        p.appendChild(chips);
        return p;
      }
      body.appendChild(row('還沒讀', unreadList, 'chip--unread'));
      body.appendChild(row('已讀', readList, 'chip--read'));
    }, function () { sum.textContent = '已讀：讀不到'; }));
    return box;
  }

  function single(ctx, slug) {
    var main = ctx.main;
    if (!C.paths.isSlug(slug)) { notFound(main); return null; }
    var store = ctx.store;
    var path = C.paths.privatePost(slug);
    var thread = C.paths.thread('private', slug);
    return store.get(path).then(function (doc) {
      if (!doc) { notFound(main); return null; }
      var x = doc.data || {};
      var art = el('article', 'post container container--narrow post--private');
      var crumb = el('p', 'breadcrumb');
      crumb.appendChild(C.dom.link(C.route.href('private'), null, '← 私密紀事'));
      art.appendChild(crumb);
      var head = el('header', 'post-head');
      var meta = el('div', 'entry-meta');
      var t = el('time', 'stamp-date', C.util.fmtDate(x.date));
      t.dateTime = String(x.date || '');
      meta.appendChild(t);
      meta.appendChild(el('span', 'chip chip--lock', '🔒 私密紀事'));
      if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
      head.appendChild(meta);
      head.appendChild(el('h1', 'post-title', x.title || '（沒有標題）'));
      head.appendChild(el('p', 'entry-private-note', '只有私密名單裡的家長與老師看得到這一篇，請不要轉貼。'));
      art.appendChild(head);
      if (ctx.session.roles.teacher) art.appendChild(readPanel(ctx, thread));
      var bodyBox = el('div', 'post-body');
      if (Array.isArray(x.blocks) && x.blocks.length) {
        bodyBox.appendChild(C.blocks.render(x.blocks, { store: store, owner: path, demo: store.isDemo }));
      } else {
        bodyBox.appendChild(el('p', 'empty', '這一篇沒有內文。'));
      }
      art.appendChild(bodyBox);
      C.comments.mount(ctx, art, thread);
      main.appendChild(art);
      if (!ctx.session.roles.teacher) {
        store.markRead(thread).catch(function () { /* 已讀回條是附加的，失敗不打擾讀者 */ });
      }
      return null;
    }, function (err) {
      var e = C.errors.from(err);
      if (e.code === 'denied' || e.code === 'invalid') { notFound(main); return null; }
      throw e;
    });
  }

  C.views['private'] = function (ctx) {
    var r = ctx.session.roles;
    if (!r.teacher && !r.privateReader) { onlyForPrivate(ctx.main); return null; }
    var slug = ctx.params.get('p');
    if (slug) return single(ctx, slug);
    return list(ctx);
  };
})(typeof window !== 'undefined' ? window : globalThis);
