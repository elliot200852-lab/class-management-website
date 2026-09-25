/* views/gallery.js — 相簿列表 gallery.html 與單本相簿 album.html?a=<slug>（docs/ARCHITECTURE.md §3.1）。

   · 列表：albums.list（導師 albums.list.teacher，看得到下架的），依 order、日期排好。
   · 單本：albums/{slug}；格子用 photos.thumbs（一次 60 張、往下捲再載入；查詢結果本身就帶縮圖資料），
     點開才讀顯示圖（燈箱）；影片一律是外部連結（YouTube 點了才載入 youtube-nocookie）；相簿留言。
   · 沒有照片、也沒有外部連結的相簿 → 「尚未設定相簿連結」。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function header(eyebrow, title, dek) {
    var h = el('header', 'page-header');
    h.appendChild(el('p', 'eyebrow', eyebrow));
    h.appendChild(el('h1', 'page-title', title));
    if (dek) h.appendChild(el('p', 'page-dek', dek));
    return h;
  }

  function notFound(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這本相簿找不到（可能已下架或網址打錯了）。'));
    n.appendChild(C.dom.link(C.route.href('gallery'), 'section-link', '回相簿'));
    box.appendChild(n);
    main.appendChild(box);
  }

  C.views.gallery = function (ctx) {
    var container = el('div', 'container');
    container.appendChild(header('Albums', '相簿', '班上活動的照片與影片。點進相簿看大圖。'));
    var grid = el('div', 'album-grid');
    container.appendChild(grid);
    ctx.main.appendChild(container);
    var name = ctx.session.roles.teacher ? 'albums.list.teacher' : 'albums.list';
    return ctx.store.query(name).then(function (page) {
      if (!page.items.length) {
        grid.appendChild(el('p', 'empty', '還沒有相簿。'));
        return;
      }
      page.items.forEach(function (doc) { grid.appendChild(C.cards.album(ctx, doc)); });
    }, function (err) {
      grid.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };

  /** 縮圖格（往下捲再載入）。回傳 { section, ready }。 */
  function thumbGrid(ctx, owner, total) {
    var sec = el('section', 'album-photos');
    sec.setAttribute('aria-label', '照片');
    var grid = el('div', 'thumb-grid thumb-grid--album');
    var more = C.dom.button('btn load-more', '再載入 60 張', null);
    more.hidden = true;
    C.dom.add(sec, grid, more);
    var items = [];
    var cursor = null;

    function addThumb(t) {
      var it = { owner: owner, pid: t.id, caption: (t.data && t.data.caption) || '' };
      var index = items.length;
      items.push(it);
      var b = el('button', 'thumb');
      b.type = 'button';
      b.setAttribute('aria-label', '看大圖' + (it.caption ? '：' + it.caption : '（第 ' + (index + 1) + ' 張）'));
      var img = el('img');
      img.alt = it.caption;
      img.loading = 'lazy';
      b.appendChild(img);
      var data = t.data && t.data.data;
      if (C.photos.isBase64(data, 49152)) {
        img.src = 'data:image/jpeg;base64,' + data; // 查詢結果已經帶著縮圖，不必再讀一次
      } else {
        C.photos.fill(img, ctx.store, owner, it.pid, 'thumb');
      }
      b.addEventListener('click', function () { C.lightbox.open(ctx.store, items, index); });
      grid.appendChild(b);
    }

    function loadPage() {
      more.disabled = true;
      return ctx.store.query('photos.thumbs', { owner: owner }, cursor ? { after: cursor } : undefined).then(function (page) {
        page.items.forEach(addThumb);
        cursor = page.next;
        more.hidden = !cursor;
        more.disabled = false;
        if (!items.length) sec.hidden = true;
      });
    }
    more.addEventListener('click', function () {
      loadPage().catch(function (err) {
        more.disabled = false;
        sec.appendChild(C.errors.box(err, { where: 'list' }));
      });
    });
    if (!(total > 0)) {
      sec.hidden = true;
      return { section: sec, ready: Promise.resolve() };
    }
    var ready = loadPage().catch(function (err) {
      sec.appendChild(C.errors.box(err, { where: 'list' }));
    });
    return { section: sec, ready: ready };
  }

  /** 影片：外部連結（YouTube 畫成「點了才載入」的預覽框；其他網址畫成連結卡） */
  function videos(ctx, list) {
    var arr = Array.isArray(list) ? list.filter(function (v) { return v && typeof v.url === 'string'; }) : [];
    if (!arr.length) return null;
    var sec = el('section', 'album-videos');
    sec.appendChild(el('h2', 'section-title section-title--small', '影片'));
    var grid = el('div', 'video-grid');
    arr.forEach(function (v) {
      var block = { t: 'video', url: v.url };
      if (typeof v.title === 'string' && v.title) block.title = v.title;
      grid.appendChild(C.blocks.render([block], { demo: ctx.store.isDemo }));
    });
    sec.appendChild(grid);
    return sec;
  }

  C.views.album = function (ctx) {
    var main = ctx.main;
    var slug = ctx.params.get('a') || '';
    if (!C.paths.isSlug(slug)) { notFound(main); return null; }
    var path = C.paths.album(slug);
    return ctx.store.get(path).then(function (doc) {
      if (!doc) { notFound(main); return null; }
      var x = doc.data || {};
      ctx.setTitle(x.title || '相簿');
      var art = el('article', 'album-page container');
      var crumb = el('p', 'breadcrumb');
      crumb.appendChild(C.dom.link(C.route.href('gallery'), null, '← 相簿'));
      art.appendChild(crumb);
      var head = el('header', 'post-head');
      var meta = el('div', 'entry-meta');
      var t = el('time', 'stamp-date', C.util.fmtDate(x.date));
      t.dateTime = String(x.date || '');
      meta.appendChild(t);
      if (x.photoCount > 0) meta.appendChild(el('span', 'chip', x.photoCount + ' 張照片'));
      if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
      head.appendChild(meta);
      head.appendChild(el('h1', 'post-title', x.title || '（沒有標題）'));
      if (x.description) {
        var desc = el('p', 'album-desc');
        desc.appendChild(C.text.render(x.description));
        head.appendChild(desc);
      }
      art.appendChild(head);

      var link = C.text.safeUrl(x.linkUrl);
      var vids = videos(ctx, x.videos);
      if (!(x.photoCount > 0) && !link && !vids) {
        var empty = el('div', 'notice album-empty');
        empty.appendChild(el('p', 'album-empty-title', '尚未設定相簿連結'));
        empty.appendChild(el('p', null, '老師還沒有把照片放進這本相簿。放好之後，這裡會出現照片的縮圖。'));
        art.appendChild(empty);
      }
      if (link) {
        var card = el('div', 'blk-linkcard album-link');
        card.appendChild(el('span', 'blk-linkcard-label', '外部相簿'));
        card.appendChild(C.text.extLink(link.href, '打開完整相簿（另開新分頁）'));
        art.appendChild(card);
      }
      var tg = thumbGrid(ctx, path, x.photoCount);
      art.appendChild(tg.section);
      ctx.track(tg.ready);
      if (vids) art.appendChild(vids);
      C.comments.mount(ctx, art, C.paths.thread('album', slug));
      main.appendChild(art);
      return tg.ready;
    }, function (err) {
      var e = C.errors.from(err);
      if (e.code === 'denied' || e.code === 'invalid') { notFound(main); return null; }
      throw e;
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
