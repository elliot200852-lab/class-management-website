/* views/admin.js — 留言後台（導師）：全站最新留言、顯示／收起（docs/ARCHITECTURE.md §3.1）。

   讀：comments.admin（集合群組、即時）、allowlist.all（作者代號 → 名單身分）、parentMap.all（→ 座號）、
       roster/students（→ 學生稱呼）。留言本身只存作者代號，信箱不會出現在留言上。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var KIND_LABEL = { post: '班級紀事', album: '相簿', 'private': '私密紀事' };
  var PAGE_OF = { post: 'post', album: 'album', 'private': 'private' };
  var PARAM_OF = { post: 's', album: 'a', 'private': 'p' };

  function teacherOnly(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只有導師能用。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    main.appendChild(box);
  }

  C.views.admin = function (ctx) {
    var main = ctx.main;
    if (!ctx.session.roles.teacher) { teacherOnly(main); return null; }
    var store = ctx.store;
    var container = el('div', 'container');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Comments'));
    head.appendChild(el('h1', 'page-title', '留言後台'));
    head.appendChild(el('p', 'page-dek', '全站最新 200 則留言。收起的留言只有導師看得到，隨時可以還原。'));
    container.appendChild(head);

    var filter = 'all';
    var tabs = el('div', 'tabs');
    tabs.setAttribute('role', 'tablist');
    var tabDefs = [['all', '全部'], ['visible', '顯示中'], ['hidden', '已收起']];
    var tabBtns = {};
    tabDefs.forEach(function (t) {
      var b = C.dom.button('tab', t[1], function () {
        filter = t[0];
        Object.keys(tabBtns).forEach(function (k) {
          tabBtns[k].className = 'tab' + (k === filter ? ' is-current' : '');
          tabBtns[k].setAttribute('aria-selected', k === filter ? 'true' : 'false');
        });
        draw();
      });
      b.setAttribute('role', 'tab');
      tabBtns[t[0]] = b;
      tabs.appendChild(b);
    });
    tabBtns.all.className = 'tab is-current';
    tabBtns.all.setAttribute('aria-selected', 'true');
    container.appendChild(tabs);
    var listBox = el('div', 'admin-list');
    listBox.appendChild(C.dom.loading());
    container.appendChild(listBox);
    main.appendChild(container);

    // 身分對照：代號 → 名單 → 座號 → 學生稱呼
    var who = Promise.all([
      store.query('allowlist.all').then(function (p) { return p.items; }, function () { return []; }),
      C.cards.parentMapItems(ctx).catch(function () { return []; }),
      store.get(C.paths.rosterStudents()).then(function (d) { return d ? d.data.students || [] : []; }, function () { return []; })
    ]).then(function (r) {
      var byAlias = {};
      r[0].forEach(function (a) { if (a.data && a.data.alias) byAlias[a.data.alias] = { key: a.id, kind: a.data.kind }; });
      var mapByKey = {};
      r[1].forEach(function (m) { mapByKey[m.id] = m.data; });
      var nameBySeat = {};
      r[2].forEach(function (s) { if (s && s.seat) nameBySeat[s.seat] = s.displayName || s.name || ''; });
      return function (alias) {
        var a = byAlias[alias];
        if (!a) return '（已不在名單）';
        if (a.kind === 'teacher') return '導師本人';
        var m = mapByKey[a.key];
        if (!m || !Array.isArray(m.seats) || !m.seats.length) return a.kind === 'staff' ? '同仁' : '家長（沒有對應座號）';
        var seats = m.seats.map(function (s) {
          return '座號 ' + s + (nameBySeat[s] ? ' ' + nameBySeat[s] : '');
        }).join('、');
        if (m.kind === 'staff') return '同仁（可讀 ' + seats + ' 的部落格）';
        return seats + (m.relation ? '（' + m.relation + '）' : '');
      };
    });

    var titles = {};
    var latest = null;
    var identify = null;

    function threadTitle(info, span) {
      var key = info.thread;
      if (!titles[key]) {
        var getter = info.kind === 'post' ? C.paths.post(info.slug) : (info.kind === 'album' ? C.paths.album(info.slug) : C.paths.privatePost(info.slug));
        titles[key] = store.get(getter).then(function (d) { return d && d.data ? d.data.title || '' : ''; }, function () { return ''; });
      }
      titles[key].then(function (t) { if (t) span.textContent = t; });
    }

    function row(doc) {
      var x = doc.data;
      var info = C.paths.parseComment(doc.path);
      var item = el('article', 'admin-item' + (x.status === 'hidden' ? ' is-hidden' : ''));
      var top = el('div', 'admin-item-top');
      top.appendChild(el('time', 'comment-time', C.util.fmtTime(x.createdAt)));
      if (info) {
        top.appendChild(el('span', 'chip', KIND_LABEL[info.kind]));
        var params = {};
        params[PARAM_OF[info.kind]] = info.slug;
        var link = C.dom.link(C.route.href(PAGE_OF[info.kind], params), 'admin-thread', info.slug);
        threadTitle(info, link);
        top.appendChild(link);
      }
      item.appendChild(top);
      var author = el('p', 'admin-author');
      author.appendChild(el('strong', null, x.authorName || '（沒有署名）'));
      author.appendChild(C.comments.roleTag(x.role));
      var idSpan = el('span', 'admin-identity', identify ? identify(x.authorAlias) : '');
      author.appendChild(idSpan);
      item.appendChild(author);
      var body = el('p', 'comment-body');
      body.appendChild(C.text.render(x.body || ''));
      item.appendChild(body);
      var hidden = x.status === 'hidden';
      var actions = el('div', 'comment-actions');
      if (info) {
        var toggle = C.dom.button('btn btn--small', hidden ? '還原顯示' : '收起', function () {
          toggle.disabled = true;
          store.update(C.paths.comment(info.thread, doc.id), { status: hidden ? 'visible' : 'hidden' }).catch(function (err) {
            toggle.disabled = false;
            actions.appendChild(el('span', 'form-msg', C.errors.message(err, 'form') || '沒有成功'));
          });
        });
        actions.appendChild(toggle);
      }
      if (hidden) actions.appendChild(el('span', 'chip chip--hidden', '已收起'));
      item.appendChild(actions);
      return item;
    }

    function draw() {
      if (!latest) return;
      C.dom.clear(listBox);
      var items = latest.items.filter(function (d) {
        return filter === 'all' || d.data.status === filter;
      });
      if (!items.length) {
        listBox.appendChild(el('p', 'empty', filter === 'hidden' ? '沒有收起的留言。' : '還沒有留言。'));
        return;
      }
      items.forEach(function (d) { listBox.appendChild(row(d)); });
    }

    return new Promise(function (resolve) {
      var first = true;
      var stop = store.watch('comments.admin', {}, function (page, err) {
        if (!ctx.isCurrent()) return;
        if (err) {
          C.dom.clear(listBox);
          listBox.appendChild(C.errors.box(err, { where: 'list' }));
        } else {
          latest = page;
          draw();
        }
        if (first) {
          first = false;
          who.then(function (fn) { identify = fn; draw(); resolve(); }, function () { resolve(); });
        }
      });
      ctx.onCleanup(stop);
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
