/* views/my-child-admin.js — 「我的孩子」導師端：全班格 my-child.html#/admin（docs/ARCHITECTURE.md §3.1）。

   讀：blogs.all（全班部落格主頁）、entries.recentParent 與 blogComments.recentParent（全班最新的家長文與家長留言，
       集合群組查詢）、parentMap.all（每格底下的家長稱謂）。
   未讀：v1 沒有背景程式，由這一頁當場比對（判準在 core/seen.js）：家長新發的文、新留的話，
         晚於「這台裝置上次打開那個座號」的就亮起來。打開座號的文章列表＝看過了。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function teacherOnly(ctx) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只有導師能用。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    ctx.main.appendChild(box);
    return null;
  }

  /** 每個座號底下的家長稱謂（純家長、有效的對應）：{ 座號: ['母', '父'] } */
  function parentsBySeat(maps) {
    var out = {};
    (maps || []).forEach(function (m) {
      var x = m && m.data;
      if (!x || x.kind !== 'parent' || x.active !== true || !Array.isArray(x.seats)) return;
      x.seats.forEach(function (s) {
        if (!C.seats.valid(s)) return;
        (out[s] = out[s] || []).push(x.relation || '家長');
      });
    });
    return out;
  }

  C.myChild = C.myChild || {};

  C.myChild.admin = function (ctx) {
    if (!ctx.session.roles.teacher) return teacherOnly(ctx);
    var store = ctx.store;
    var box = el('div', 'container');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'My child・全班'));
    head.appendChild(el('h1', 'page-title', '我的孩子（全班）'));
    head.appendChild(el('p', 'page-dek', '每位孩子一格。亮起來的是家長新發的文、或新留的話（這台裝置還沒看過的）；點進去看過就會熄掉。'));
    box.appendChild(head);
    var summary = el('p', 'mc-summary');
    box.appendChild(summary);
    var grid = el('div', 'mc-grid mc-grid--class');
    grid.appendChild(C.dom.loading());
    box.appendChild(grid);
    ctx.main.appendChild(box);

    var unreadP = Promise.all([
      store.query('entries.recentParent'),
      store.query('blogComments.recentParent')
    ]).then(function (r) {
      var res = C.seen.compute(r[0].items, r[1].items, C.seen.load());
      C.seen.remember(res.latest);
      return res.bySeat;
    }, function () {
      return null; // 未讀是附加的：讀不到就不亮，格子照樣畫
    });

    return Promise.all([
      store.query('blogs.all'),
      unreadP,
      C.cards.parentMapItems(ctx).catch(function () { return []; })
    ]).then(function (r) {
      var blogs = r[0].items;
      var unread = r[1];
      var parents = parentsBySeat(r[2]);
      C.dom.clear(grid);
      if (!blogs.length) {
        grid.appendChild(el('p', 'notice', '還沒有開任何孩子的部落格。請 AI 助理照名冊幫全班開好（開部落格的腳本）。'));
        return;
      }
      var lit = 0;
      blogs.forEach(function (doc) {
        var x = doc.data || {};
        var seat = C.seats.valid(x.seat) ? x.seat : doc.id;
        if (!C.seats.valid(seat)) return;
        var u = unread && unread[seat];
        var a = C.dom.link(C.myChild.href('seat/' + seat), 'mc-card' + (u ? ' mc-card--new' : ''));
        a.setAttribute('data-seat', seat);
        a.appendChild(C.myChild.avatar(x));
        var label = el('span', 'mc-card-label');
        label.appendChild(el('span', 'mc-card-seat', '座號 ' + seat));
        label.appendChild(el('span', 'mc-card-name', x.displayName || '（沒有稱呼）'));
        var chips = el('span', 'mc-card-parents');
        (parents[seat] || []).forEach(function (rel) { chips.appendChild(el('span', 'chip chip--parent', rel)); });
        if (!(parents[seat] || []).length) chips.appendChild(el('span', 'chip chip--unread', '還沒有對應的家長'));
        label.appendChild(chips);
        a.appendChild(label);
        if (u) {
          lit++;
          var badges = el('span', 'mc-badges');
          if (u.posts) badges.appendChild(el('span', 'mc-new-badge', '新文章 ' + u.posts));
          if (u.replies) badges.appendChild(el('span', 'mc-new-badge mc-new-badge--reply', '新留言 ' + u.replies));
          a.appendChild(badges);
        }
        grid.appendChild(a);
      });
      summary.textContent = unread === null
        ? '（未讀提示暫時讀不到，稍後重新整理再試）'
        : (lit ? '有新動態的孩子：' + lit + ' 位。' : '目前沒有新的家長文章或留言。');
    }, function (err) {
      C.dom.clear(grid);
      grid.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };

  C.myChild.parentsBySeat = parentsBySeat;
})(typeof window !== 'undefined' ? window : globalThis);
