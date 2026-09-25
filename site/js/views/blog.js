/* views/blog.js — 班級紀事列表（私密紀事以鎖頭卡依日期併入）與分類頁（docs/ARCHITECTURE.md §3.1）。

   · 一般讀者：posts.recent；私密讀者另發 private.list（沒有私密讀者身分的畫面根本不發這個查詢）。
   · 導師：.teacher 版查詢（看得到下架的），卡片上多一個「已讀 X/N」徽章。
   · 往下捲：按「再載入 20 篇」用 startAfter 游標接著讀。私密紀事只有一頁（最多 100 篇），
     依日期插進已經載入的範圍裡，範圍外的等下一頁載入時再插。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function header(title, dek) {
    var h = el('header', 'page-header');
    h.appendChild(el('p', 'eyebrow', 'Class journal'));
    h.appendChild(el('h1', 'page-title', title));
    if (dek) h.appendChild(el('p', 'page-dek', dek));
    return h;
  }

  function categoryChips(active) {
    var cats = C.config().categories || [];
    if (!cats.length) return null;
    var nav = el('nav', 'cat-chips');
    nav.setAttribute('aria-label', '分類');
    var all = C.dom.link(C.route.href('blog'), 'chip' + (active ? '' : ' is-current'), '全部');
    nav.appendChild(all);
    cats.forEach(function (c) {
      var a = C.dom.link(C.route.href('category', { c: c }), 'chip' + (active === c ? ' is-current' : ''), c);
      nav.appendChild(a);
    });
    return nav;
  }

  /** 共用的「列表＋再載入」。queryName／params：一般紀事；withPrivate：要不要併入私密紀事 */
  function list(ctx, queryName, params, withPrivate) {
    var stack = el('div', 'entry-stack scatter');
    var more = C.dom.button('btn load-more', '再載入 20 篇', null);
    more.hidden = true;
    var wrap = el('div', 'journal');
    C.dom.add(wrap, stack, more);

    var privates = [];
    var privIndex = 0;
    var privReady = Promise.resolve();
    if (withPrivate) {
      var pname = ctx.session.roles.teacher ? 'private.list.teacher' : 'private.list';
      privReady = ctx.store.query(pname).then(function (p) { privates = p.items; }, function () {
        privates = []; // 私密區被拒：靜默不顯示任何痕跡
      });
    }

    function insertPrivatesDownTo(date, last) {
      while (privIndex < privates.length) {
        var pd = privates[privIndex].data.date || '';
        if (!last && pd < date) break;
        stack.appendChild(C.cards.privatePost(ctx, privates[privIndex]));
        privIndex++;
      }
    }

    var cursor = null;
    var shown = 0;
    function loadPage() {
      more.disabled = true;
      var page = cursor ? { after: cursor } : undefined;
      return Promise.all([ctx.store.query(queryName, params, page), privReady]).then(function (r) {
        var res = r[0];
        res.items.forEach(function (doc) {
          insertPrivatesDownTo(doc.data.date || '', false);
          stack.appendChild(C.cards.post(ctx, doc, { headingTag: 'h2' }));
          shown++;
        });
        cursor = res.next;
        if (!cursor) insertPrivatesDownTo('', true);
        if (!shown && !privIndex) stack.appendChild(el('p', 'empty', '這裡還沒有紀事。'));
        more.hidden = !cursor;
        more.disabled = false;
      });
    }
    more.addEventListener('click', function () {
      loadPage().catch(function (err) {
        more.disabled = false;
        wrap.appendChild(C.errors.box(err, { where: 'list' }));
      });
    });
    return loadPage().then(function () { return wrap; });
  }

  C.views.blog = function (ctx) {
    var main = ctx.main;
    var container = el('div', 'container container--narrow');
    container.appendChild(header('班級紀事', '班上的大小事，照日期排好。'));
    var chips = categoryChips(null);
    if (chips) container.appendChild(chips);
    main.appendChild(container);
    var teacher = ctx.session.roles.teacher;
    var withPrivate = teacher || ctx.session.roles.privateReader;
    return list(ctx, teacher ? 'posts.recent.teacher' : 'posts.recent', {}, withPrivate).then(function (w) {
      container.appendChild(w);
    });
  };

  C.views.category = function (ctx) {
    var main = ctx.main;
    var c = ctx.params.get('c') || '';
    var cats = C.config().categories || [];
    var container = el('div', 'container container--narrow');
    main.appendChild(container);
    if (cats.indexOf(c) < 0) {
      container.appendChild(header('找不到這個分類'));
      container.appendChild(C.dom.link(C.route.href('blog'), 'section-link', '回班級紀事'));
      return null;
    }
    ctx.setTitle('分類：' + c);
    container.appendChild(header(c, '這個分類底下的紀事。'));
    var chips = categoryChips(c);
    if (chips) container.appendChild(chips);
    var teacher = ctx.session.roles.teacher;
    return list(ctx, teacher ? 'posts.byCategory.teacher' : 'posts.byCategory', { category: c }, false).then(function (w) {
      container.appendChild(w);
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
