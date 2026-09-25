/* views/poem.js — 每日一詩 poem.html（docs/DATA-MODEL.md §2.11 的 kind 'poem'）。

   一個月一份單頁 pages/poems-YYYY-MM（scripts/publish_poems.py 寫的），一次只讀一份：
     · 預設看今天那一首；今天沒有就看這個月今天以前的最後一首；網址 ?d=YYYY-MM-DD 指定哪一天。
     · 下面列出這個月的每一首；?m=YYYY-MM 看別的月份（上一個月／下一個月）。
     · 還沒到的日子：讀者看不到（一天揭曉一首）；導師看得到，標「還沒到」。
   詩的正文逐字照原樣（空行、行首空白都保留），全部用 textContent。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;

  function validItem(it) {
    return it && typeof it === 'object' && typeof it.date === 'string' && DATE_RE.test(it.date) &&
      typeof it.title === 'string' && typeof it.text === 'string' && typeof it.author === 'string';
  }

  /** 月份加減：'2026-01', -1 → '2025-12' */
  function shiftMonth(ym, n) {
    var y = parseInt(ym.slice(0, 4), 10);
    var m = parseInt(ym.slice(5, 7), 10) - 1 + n;
    y += Math.floor(m / 12);
    m = ((m % 12) + 12) % 12;
    return y + '-' + (m < 9 ? '0' : '') + (m + 1);
  }

  /** 這個月能看的詩（依日期）＋ 要顯示哪一首。純函式（tests/js/v11.test.js）。
      items：月份文件的 data.items；today：'YYYY-MM-DD'；want：網址指定的日期；showFuture：導師 */
  function pick(items, today, want, showFuture) {
    var list = (Array.isArray(items) ? items : []).filter(validItem).slice().sort(function (a, b) {
      return a.date < b.date ? -1 : (a.date > b.date ? 1 : 0);
    });
    if (!showFuture) list = list.filter(function (it) { return it.date <= today; });
    var chosen = null;
    var i;
    if (want) {
      for (i = 0; i < list.length; i++) if (list[i].date === want) chosen = list[i];
    }
    if (!chosen) {
      for (i = 0; i < list.length; i++) if (list[i].date === today) chosen = list[i];
    }
    if (!chosen) {
      for (i = list.length - 1; i >= 0; i--) {
        if (list[i].date <= today) { chosen = list[i]; break; }
      }
    }
    if (!chosen && list.length) chosen = list[0];
    return { list: list, chosen: chosen };
  }

  function poemCard(it, today) {
    var art = el('article', 'poem-card');
    art.setAttribute('aria-live', 'polite');
    var meta = el('p', 'poem-date');
    meta.appendChild(el('span', 'stamp-date', C.util.fmtStamp(it.date)));
    if (it.date === today) meta.appendChild(el('span', 'chip chip--read', '今天'));
    if (it.date > today) meta.appendChild(el('span', 'chip chip--unread', '還沒到（只有導師看得到）'));
    art.appendChild(meta);
    art.appendChild(el('h2', 'poem-title', it.title));
    var by = el('p', 'poem-author', it.author);
    if (typeof it.source === 'string' && it.source) by.appendChild(el('span', 'poem-source', '・' + it.source));
    art.appendChild(by);
    art.appendChild(el('div', 'poem-text', it.text));
    if (typeof it.guide === 'string' && it.guide) {
      var guide = el('section', 'poem-guide');
      guide.appendChild(el('h3', 'poem-guide-title', '導讀'));
      guide.appendChild(el('p', 'poem-guide-text', it.guide));
      art.appendChild(guide);
    }
    return art;
  }

  function monthLabel(ym) {
    return ym.slice(0, 4) + ' 年 ' + parseInt(ym.slice(5, 7), 10) + ' 月';
  }

  C.views.poem = function (ctx) {
    var store = ctx.store;
    var teacher = !!ctx.session.roles.teacher;
    var today = C.util.today();
    var thisMonth = today.slice(0, 7);
    var m = ctx.params.get('m');
    var want = ctx.params.get('d');
    if (!want || !DATE_RE.test(want)) want = null;
    if (!C.paths.isMonth(m)) m = want ? want.slice(0, 7) : thisMonth;
    if (!teacher && m > thisMonth) m = thisMonth;

    var box = el('div', 'container container--narrow poem-page');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Poetry'));
    head.appendChild(el('h1', 'page-title', '每日一詩'));
    head.appendChild(el('p', 'page-dek', '每天一首，陪孩子和家人開始這一天。'));
    box.appendChild(head);
    var todayBox = el('div', 'poem-today');
    todayBox.appendChild(C.dom.loading());
    var monthBox = el('section', 'poem-month');
    C.dom.add(box, todayBox, monthBox);
    ctx.main.appendChild(box);

    var nav = el('nav', 'poem-month-nav');
    nav.setAttribute('aria-label', '換月份');
    var prev = shiftMonth(m, -1);
    var next = shiftMonth(m, 1);
    nav.appendChild(C.dom.link(C.route.href('poem', { m: prev }), 'chip', '‹ ' + monthLabel(prev)));
    nav.appendChild(el('span', 'poem-month-current', monthLabel(m)));
    if (teacher || next <= thisMonth) nav.appendChild(C.dom.link(C.route.href('poem', { m: next }), 'chip', monthLabel(next) + ' ›'));

    return store.get(C.paths.poemMonth(m)).then(function (doc) {
      var data = doc && doc.data && doc.data.kind === 'poem' && doc.data.data ? doc.data.data : null;
      var r = pick(data ? data.items : [], today, want, teacher);
      C.dom.clear(todayBox);
      if (!r.chosen) {
        var n = el('div', 'notice');
        n.appendChild(el('p', null, m === thisMonth ? '這個月還沒有詩。' : monthLabel(m) + '沒有詩。'));
        if (teacher) {
          n.appendChild(el('p', null, '跟 AI 助理說「幫我選下個月的詩」，它會照劇本準備草稿給你看；你確認每一首都能公開使用之後才會放上來。'));
        }
        todayBox.appendChild(n);
      } else {
        todayBox.appendChild(poemCard(r.chosen, today));
      }
      monthBox.appendChild(nav);
      if (r.list.length) {
        monthBox.appendChild(el('h2', 'section-title section-title--small', monthLabel(m) + '的詩'));
        var ol = el('ol', 'poem-list');
        r.list.forEach(function (it) {
          var li = el('li', it === r.chosen ? 'is-current' : null);
          var a = C.dom.link(C.route.href('poem', { m: m, d: it.date }), null, null);
          a.appendChild(el('span', 'poem-list-date', C.util.fmtStamp(it.date).slice(5)));
          a.appendChild(el('span', 'poem-list-title', it.title));
          a.appendChild(el('span', 'poem-list-author', it.author));
          if (it === r.chosen) a.setAttribute('aria-current', 'true');
          li.appendChild(a);
          ol.appendChild(li);
        });
        monthBox.appendChild(ol);
      }
    }, function (err) {
      C.dom.clear(todayBox);
      todayBox.appendChild(C.errors.box(err, { where: 'single' }));
    });
  };

  C.poem = { pick: pick, shiftMonth: shiftMonth };
})(typeof window !== 'undefined' ? window : globalThis);
