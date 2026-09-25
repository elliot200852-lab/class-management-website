/* views/print.js — 匯出 PDF（只有導師能用）：blog-print.html（班級紀事）與 my-child-print.html（學生部落格）。

   做法：用瀏覽器自己的「列印 → 另存為 PDF」，不裝任何外部函式庫。
     1. 選日期範圍（班級紀事另可選分類；部落格選「一位學生」或「全班」），下面列出範圍裡的文章，一開始全部打勾
        （已下架的預設不勾）；可以逐篇取消。
     2. 按「產生列印版」：這一頁下面組出整份列印版（封面、目錄、每篇內文與照片），照片用顯示圖（不是縮圖），
        **全部照片載入完成才開放列印**（列印時還沒載入的照片會是空白）。
     3. 按「列印／存成 PDF」→ 瀏覽器的列印視窗 → 目的地選「另存為 PDF」。紙張 A4；只印列印版，
        頁首、導覽、選單都不會印出來（site.css 的列印樣式）。
   不是導師：只顯示一句說明，一個查詢都不發。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var MAX_PAGES = 25;          // 班級紀事最多讀 25 頁 × 20 篇（一學年綽綽有餘）

  function teacherOnly(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只有導師能用。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    main.appendChild(box);
    return null;
  }

  // ── 純函式（tests/js/v11.test.js） ─────────────────────
  function inRange(date, from, to) {
    date = String(date || '');
    return (!from || date >= from) && (!to || date <= to);
  }

  function byDateAsc(a, b) {
    var da = String(a.date || '');
    var db = String(b.date || '');
    if (da !== db) return da < db ? -1 : 1;
    return a.id < b.id ? -1 : (a.id > b.id ? 1 : 0);
  }

  function rangeText(from, to) {
    if (from && to) return from + ' ～ ' + to;
    if (from) return from + ' 以後';
    if (to) return to + ' 以前';
    return '全部日期';
  }

  // ── 共用的畫面零件 ─────────────────────────────────────
  function header(kind) {
    var h = el('header', 'page-header no-print');
    h.appendChild(el('p', 'eyebrow', 'Export・導師限定'));
    h.appendChild(el('h1', 'page-title', kind === 'blog' ? '匯出 PDF：班級紀事' : '匯出 PDF：學生部落格'));
    h.appendChild(el('p', 'page-dek', '選好範圍與要匯出的文章 →「產生列印版」→ 照片都準備好之後按「列印／存成 PDF」，' +
      '在列印視窗的「目的地」選「另存為 PDF」。紙張是 A4。'));
    var nav = el('nav', 'tabs');
    nav.setAttribute('aria-label', '匯出哪一種');
    [['blog', '班級紀事', 'blog-print'], ['child', '學生部落格', 'my-child-print']].forEach(function (t) {
      var a = C.dom.link(C.route.href(t[2]), 'tab' + (kind === t[0] ? ' is-current' : ''), t[1]);
      if (kind === t[0]) a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    h.appendChild(nav);
    return h;
  }

  function field(label, input) {
    var w = el('label', 'export-field');
    w.appendChild(el('span', 'field-label', label));
    w.appendChild(input);
    return w;
  }

  function dateInput(id) {
    var i = el('input', 'field field--small');
    i.type = 'date';
    i.id = id;
    return i;
  }

  function checkbox(id, label, checked) {
    var w = el('label', 'export-check');
    var b = el('input');
    b.type = 'checkbox';
    b.id = id;
    b.checked = !!checked;
    w.appendChild(b);
    w.appendChild(g.document.createTextNode(' ' + label));
    return { el: w, box: b };
  }

  /** 逐篇勾選清單。groups：[{ title?, items: [{ id, date, title, note?, hidden? }] }]。
      使用者改過的勾選記在 picked（重篩時保留）；沒改過的：沒下架＝勾、已下架＝不勾。 */
  function checklist(onChange) {
    var picked = {};
    var groups = [];
    var wrap = el('div', 'export-list');
    var head = el('div', 'export-list-head');
    var count = el('span', 'export-count');
    var actions = el('span', 'export-list-actions');
    var body = el('div', 'export-groups');
    C.dom.add(head, count, actions);
    C.dom.add(wrap, head, body);

    function isOn(it) { return Object.prototype.hasOwnProperty.call(picked, it.id) ? picked[it.id] : !it.hidden; }
    function all() { var out = []; groups.forEach(function (gr) { out = out.concat(gr.items); }); return out; }
    function paint() {
      var items = all();
      var n = items.filter(isOn).length;
      count.textContent = '將匯出 ' + n + '／' + items.length + ' 篇';
      Array.prototype.forEach.call(body.querySelectorAll('input[type=checkbox]'), function (b) {
        var it = b.cmwItem;
        b.checked = isOn(it);
        b.parentNode.parentNode.className = b.checked ? '' : 'is-off';
      });
      if (onChange) onChange();
    }
    actions.appendChild(C.dom.button('btn-link', '全選', function () { all().forEach(function (it) { picked[it.id] = true; }); paint(); }));
    actions.appendChild(C.dom.button('btn-link', '全不選', function () { all().forEach(function (it) { picked[it.id] = false; }); paint(); }));

    function render(next) {
      groups = next || [];
      C.dom.clear(body);
      var total = 0;
      groups.forEach(function (gr) {
        if (!gr.items.length) return;
        var sec = el('div', 'export-group');
        if (gr.title) sec.appendChild(el('h3', 'export-group-title', gr.title));
        var ul = el('ul', 'export-items');
        gr.items.forEach(function (it) {
          total++;
          var li = el('li');
          var lab = el('label');
          var b = el('input');
          b.type = 'checkbox';
          b.cmwItem = it;
          b.addEventListener('change', function () { picked[it.id] = b.checked; paint(); });
          lab.appendChild(b);
          lab.appendChild(el('span', 'export-d', it.date || '—'));
          lab.appendChild(el('span', 'export-t', it.title || '（沒有標題）'));
          if (it.note) lab.appendChild(el('span', 'chip', it.note));
          if (it.hidden) lab.appendChild(el('span', 'chip chip--hidden', '已下架'));
          li.appendChild(lab);
          ul.appendChild(li);
        });
        sec.appendChild(ul);
        body.appendChild(sec);
      });
      if (!total) body.appendChild(el('p', 'empty', '這個範圍沒有文章。'));
      paint();
    }

    return {
      el: wrap,
      render: render,
      selected: function () { return all().filter(isOn); }
    };
  }

  /** 照片進度：全部照片載入（或確定讀不到）之後才 resolve。 */
  function photoTracker(onProgress) {
    var total = 0;
    var done = 0;
    var failed = 0;
    var jobs = [];
    return {
      add: function (store, owner, pid, caption) {
        total++;
        var fig = el('figure', 'print-fig');
        var img = g.document.createElement('img');
        img.alt = caption || '';
        fig.appendChild(img);
        if (caption) fig.appendChild(el('figcaption', null, caption));
        jobs.push(C.photos.src(store, owner, pid, 'image').then(function (u) {
          if (!u) { failed++; fig.replaceChild(C.photos.missing(), img); return null; }
          return new Promise(function (resolve) {
            img.addEventListener('load', function () { resolve(); });
            img.addEventListener('error', function () { failed++; resolve(); });
            img.src = u;
          });
        }).then(function () { done++; onProgress(done, total, failed); }));
        return fig;
      },
      wait: function () { onProgress(done, total, failed); return Promise.all(jobs).then(function () { return { total: total, failed: failed }; }); }
    };
  }

  /** 班級紀事正文 → 列印用的節點（照片用顯示圖、影片印成一行連結文字） */
  function printBlocks(blocks, owner, store, tracker, withPhotos) {
    var root = el('div', 'print-body blocks');
    (Array.isArray(blocks) ? blocks : []).forEach(function (b) {
      if (!C.blocks.validBlock(b)) return;
      if (b.t === 'img') {
        if (withPhotos) root.appendChild(tracker.add(store, owner, b.pid, b.caption || ''));
        return;
      }
      if (b.t === 'video') {
        var p = el('p', 'print-video', '影片：' + (b.title ? b.title + '　' : ''));
        p.appendChild(el('span', 'print-url', b.url));
        root.appendChild(p);
        return;
      }
      var r = C.blocks.render([b], {});
      while (r.firstChild) root.appendChild(r.firstChild);
    });
    return root;
  }

  function cover(title, lines) {
    var c = el('section', 'print-cover');
    c.appendChild(el('p', 'print-cover-class', C.config().className || '我的班級'));
    c.appendChild(el('h1', 'print-cover-title', title));
    lines.forEach(function (t) { c.appendChild(el('p', 'print-cover-line', t)); });
    c.appendChild(el('p', 'print-cover-line', '匯出日期：' + C.util.today()));
    return c;
  }

  /** 兩頁共用的外框：面板、狀態列、列印版。回 { panel, status, doc, printBtn, genBtn, setReady } */
  function frame(ctx, kind) {
    var root = g.document.documentElement;
    root.classList.add('cmw-print-doc');
    ctx.onCleanup(function () { root.classList.remove('cmw-print-doc'); });
    var box = el('div', 'container');
    box.appendChild(header(kind));
    var panel = el('section', 'export-panel no-print');
    var status = el('p', 'export-status no-print');
    status.setAttribute('aria-live', 'polite');
    var buttons = el('div', 'export-buttons no-print');
    var genBtn = C.dom.button('btn btn--primary', '產生列印版', null);
    var printBtn = C.dom.button('btn', '列印／存成 PDF', function () { g.print(); });
    printBtn.disabled = true;
    C.dom.add(buttons, genBtn, printBtn);
    var doc = el('div', 'print-doc');
    C.dom.add(box, panel, buttons, status, doc);
    ctx.main.appendChild(box);
    return {
      panel: panel, status: status, doc: doc, genBtn: genBtn, printBtn: printBtn,
      reset: function (msg) {
        printBtn.disabled = true;
        C.dom.clear(doc);
        doc.className = 'print-doc';
        status.textContent = msg || '';
      }
    };
  }

  /** 產生列印版的共同流程：build(tracker) 組好節點（回 Promise<{ docs: n }>）→ 等照片 → 開放列印 */
  function generate(ctx, F, build) {
    F.reset('正在準備列印版…');
    F.genBtn.disabled = true;
    var seq = {};
    F.current = seq;
    var tracker = photoTracker(function (done, total, failed) {
      if (F.current !== seq || !total) return;
      F.status.textContent = '正在準備照片：' + done + '／' + total + ' 張' + (failed ? '（' + failed + ' 張讀不到）' : '');
    });
    return Promise.resolve().then(function () { return build(tracker); }).then(function (info) {
      return tracker.wait().then(function (ph) {
        if (F.current !== seq) return;
        F.genBtn.disabled = false;
        F.printBtn.disabled = false;
        F.doc.className = 'print-doc is-ready';
        F.status.textContent = '準備好了：' + info.docs + ' 篇' + (ph.total ? '、照片 ' + ph.total + ' 張' : '') +
          (ph.failed ? '（' + ph.failed + ' 張讀不到，會印成灰框）' : '') + '。按「列印／存成 PDF」。';
      });
    }).catch(function (err) {
      F.genBtn.disabled = false;
      F.status.textContent = '';
      C.dom.clear(F.doc);
      F.doc.appendChild(C.errors.box(err, { where: 'list' }));
    });
  }

  // ═══ 班級紀事 ═══════════════════════════════════════════
  function loadAllPosts(store) {
    var out = [];
    function next(page, n) {
      return store.query('posts.recent.teacher', {}, page).then(function (p) {
        out = out.concat(p.items);
        if (p.next && n < MAX_PAGES) return next({ after: p.next }, n + 1);
        return out;
      });
    }
    return next(null, 1);
  }

  C.views['blog-print'] = function (ctx) {
    if (!ctx.session.roles.teacher) return teacherOnly(ctx.main);
    var store = ctx.store;
    var F = frame(ctx, 'blog');
    var from = dateInput('ex-from');
    var to = dateInput('ex-to');
    var cat = el('select', 'field field--small');
    cat.id = 'ex-cat';
    [''].concat(C.config().categories || []).forEach(function (c) {
      var o = el('option', null, c || '全部分類');
      o.value = c;
      cat.appendChild(o);
    });
    var optPhotos = checkbox('ex-photos', '附上照片', true);
    var optBreak = checkbox('ex-break', '每篇從新的一頁開始', true);
    var filters = el('div', 'export-filters');
    C.dom.add(filters, field('從', from), field('到', to), field('分類', cat));
    var opts = el('div', 'export-options');
    C.dom.add(opts, optPhotos.el, optBreak.el);
    var list = checklist(function () { F.reset(''); });
    C.dom.add(F.panel, filters, opts, list.el);
    list.render([]);
    F.status.textContent = '讀取班級紀事…';

    return loadAllPosts(store).then(function (docs) {
      var posts = docs.map(function (d) {
        var x = d.data || {};
        return { id: d.id, date: x.date, title: x.title, note: x.category, hidden: x.visible !== true, category: x.category,
          photoCount: x.photoCount || 0 };
      }).sort(byDateAsc);
      function refresh() {
        list.render([{ items: posts.filter(function (p) {
          return inRange(p.date, from.value, to.value) && (!cat.value || p.category === cat.value);
        }) }]);
        F.status.textContent = posts.length ? '' : '還沒有任何班級紀事。';
      }
      [from, to, cat].forEach(function (i) { i.addEventListener('change', refresh); });
      refresh();
      F.genBtn.addEventListener('click', function () {
        var chosen = list.selected();
        if (!chosen.length) { F.reset('至少勾一篇。'); return; }
        ctx.setTitle('班級紀事 ' + rangeText(from.value, to.value));
        generate(ctx, F, function (tracker) {
          var d = F.doc;
          d.appendChild(cover('班級紀事', [rangeText(from.value, to.value) + (cat.value ? '・' + cat.value : ''),
            '共 ' + chosen.length + ' 篇']));
          var toc = el('section', 'print-toc');
          toc.appendChild(el('h2', null, '目錄'));
          var ol = el('ol');
          chosen.forEach(function (p) {
            var li = el('li');
            li.appendChild(el('span', 'print-toc-date', p.date));
            li.appendChild(el('span', 'print-toc-title', p.title || ''));
            ol.appendChild(li);
          });
          toc.appendChild(ol);
          d.appendChild(toc);
          return Promise.all(chosen.map(function (p) {
            return store.get(C.paths.postContent(p.id)).then(function (c) { return c ? c.data.blocks : []; });
          })).then(function (bodies) {
            chosen.forEach(function (p, i) {
              var art = el('article', 'print-item' + (optBreak.box.checked ? ' print-item--break' : ''));
              art.appendChild(el('p', 'print-meta', p.date + (p.category ? '・' + p.category : '') + (p.hidden ? '・已下架' : '')));
              art.appendChild(el('h2', 'print-title', p.title || ''));
              art.appendChild(printBlocks(bodies[i], C.paths.post(p.id), store, tracker, optPhotos.box.checked));
              d.appendChild(art);
            });
            return { docs: chosen.length };
          });
        });
      });
    }, function (err) {
      F.status.textContent = '';
      F.panel.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };

  // ═══ 學生部落格 ══════════════════════════════════════════
  C.views['my-child-print'] = function (ctx) {
    if (!ctx.session.roles.teacher) return teacherOnly(ctx.main);
    var store = ctx.store;
    var F = frame(ctx, 'child');
    var mode = el('select', 'field field--small');
    mode.id = 'ex-mode';
    [['one', '一位學生（一人一份）'], ['all', '全班（一份，每位從新的一頁開始）']].forEach(function (m) {
      var o = el('option', null, m[1]);
      o.value = m[0];
      mode.appendChild(o);
    });
    var seatSel = el('select', 'field field--small');
    seatSel.id = 'ex-seat';
    var from = dateInput('ex-from');
    var to = dateInput('ex-to');
    var optPhotos = checkbox('ex-photos', '附上照片', true);
    var seatField = field('學生', seatSel);
    var filters = el('div', 'export-filters');
    C.dom.add(filters, field('匯出方式', mode), seatField, field('從', from), field('到', to));
    var opts = el('div', 'export-options');
    opts.appendChild(optPhotos.el);
    var list = checklist(function () { F.reset(''); });
    C.dom.add(F.panel, filters, opts, list.el);
    list.render([]);
    F.status.textContent = '讀取全班的部落格…';

    var entriesBySeat = {};
    function loadSeat(seat) {
      if (!entriesBySeat[seat]) {
        entriesBySeat[seat] = store.query('entries.bySeat.teacher', { seat: seat }).then(function (p) {
          return p.items.map(function (d) {
            var x = d.data || {};
            return { id: d.id, path: d.path, seat: seat, date: x.date, title: x.title, body: x.body, author: x.author,
              photos: Array.isArray(x.photos) ? x.photos : [], hidden: x.visible !== true,
              note: x.author === 'parent' ? '家長寫的' : '導師寫的' };
          }).sort(byDateAsc);
        });
      }
      return entriesBySeat[seat];
    }

    return store.query('blogs.all').then(function (page) {
      var blogs = page.items.map(function (d) {
        var x = d.data || {};
        return { seat: C.seats.valid(x.seat) ? x.seat : d.id, name: x.displayName || '' };
      }).filter(function (b) { return C.seats.valid(b.seat); }).sort(function (a, b) { return a.seat < b.seat ? -1 : 1; });
      if (!blogs.length) {
        F.status.textContent = '還沒有開任何孩子的部落格。';
        return null;
      }
      blogs.forEach(function (b) {
        var o = el('option', null, '座號 ' + b.seat + (b.name ? '・' + b.name : ''));
        o.value = b.seat;
        seatSel.appendChild(o);
      });
      var seq = 0;
      function chosenBlogs() {
        return mode.value === 'all' ? blogs : blogs.filter(function (b) { return b.seat === seatSel.value; });
      }
      function refresh() {
        var mine = ++seq;
        seatField.hidden = mode.value === 'all';
        var bl = chosenBlogs();
        F.status.textContent = '讀取文章…';
        return Promise.all(bl.map(function (b) { return loadSeat(b.seat); })).then(function (lists) {
          if (mine !== seq) return;
          list.render(bl.map(function (b, i) {
            return { title: mode.value === 'all' ? '座號 ' + b.seat + (b.name ? '・' + b.name : '') : '',
              items: lists[i].filter(function (e) { return inRange(e.date, from.value, to.value); }) };
          }));
          F.status.textContent = '';
        }, function (err) {
          if (mine !== seq) return;
          F.status.textContent = '';
          F.panel.appendChild(C.errors.box(err, { where: 'list' }));
        });
      }
      [mode, seatSel, from, to].forEach(function (i) { i.addEventListener('change', refresh); });
      F.genBtn.addEventListener('click', function () {
        var chosen = list.selected();
        if (!chosen.length) { F.reset('至少勾一篇。'); return; }
        var bl = chosenBlogs().filter(function (b) { return chosen.some(function (e) { return e.seat === b.seat; }); });
        var one = mode.value !== 'all' && bl.length === 1;
        ctx.setTitle(one ? '座號 ' + bl[0].seat + (bl[0].name ? ' ' + bl[0].name : '') + ' 的部落格' : '全班的部落格');
        generate(ctx, F, function (tracker) {
          var d = F.doc;
          d.appendChild(cover(one ? (bl[0].name || '座號 ' + bl[0].seat) + ' 的部落格' : '全班的部落格',
            [(one ? '座號 ' + bl[0].seat + '・' : '共 ' + bl.length + ' 位・') + rangeText(from.value, to.value),
              '共 ' + chosen.length + ' 篇']));
          bl.forEach(function (b) {
            var sec = el('section', 'print-student');
            if (!one) {
              sec.appendChild(el('h2', 'print-student-title', '座號 ' + b.seat + (b.name ? '・' + b.name : '')));
            }
            chosen.filter(function (e) { return e.seat === b.seat; }).forEach(function (e, i) {
              var art = el('article', 'print-item print-entry' + (i ? ' print-item--gap' : ''));
              art.appendChild(el('p', 'print-meta', e.date + '・' + e.note + (e.hidden ? '・已下架' : '')));
              art.appendChild(el('h3', 'print-title', e.title || ''));
              var body = el('div', 'print-body print-pre');
              body.appendChild(C.text.render(e.body || ''));
              art.appendChild(body);
              if (optPhotos.box.checked) {
                var photos = el('div', 'print-photos');
                e.photos.forEach(function (p) {
                  if (p && /^[0-2]$/.test(p.pid)) photos.appendChild(tracker.add(store, e.path, p.pid, p.caption || ''));
                });
                if (photos.firstChild) art.appendChild(photos);
              }
              sec.appendChild(art);
            });
            d.appendChild(sec);
          });
          return { docs: chosen.length };
        });
      });
      return refresh();
    }, function (err) {
      F.status.textContent = '';
      F.panel.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };

  C.printExport = { inRange: inRange, byDateAsc: byDateAsc, rangeText: rangeText };
})(typeof window !== 'undefined' ? window : globalThis);
