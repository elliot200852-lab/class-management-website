/* views/courses.js — 課程頁 courses.html（docs/ARCHITECTURE.md §3.1、docs/DATA-MODEL.md §2.11）。

   讀：pages.byKind（kind 'course' 與 'schedule'；導師用 .teacher 版，看得到下架的）。
   每一份 course 單頁畫成一段：
     · 正文（blocks）
     · 課程說明影片：data.videos，一律「點了才載入」——先畫一個預覽框，點了才建 youtube-nocookie 的播放器
       （示範模式點了只顯示說明，不連任何外部網站）
     · 各科課程大綱：data.cards（這一區是老師手動維護的：在 data/courses/ 加一張卡、重新發布就會出現）
   schedule 單頁畫成課表。資料都是登入後才讀得到，不烘成靜態 HTML。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function arr(v) { return Array.isArray(v) ? v : []; }

  function videoGrid(ctx, list) {
    var vids = arr(list).filter(function (v) { return v && typeof v.url === 'string'; });
    if (!vids.length) return null;
    var sec = el('div', 'course-part');
    sec.appendChild(el('h3', 'course-part-title', '課程說明影片'));
    var grid = el('div', 'video-grid');
    vids.forEach(function (v) {
      var block = { t: 'video', url: v.url };
      if (typeof v.title === 'string' && v.title) block.title = v.title;
      grid.appendChild(C.blocks.render([block], { demo: ctx.store.isDemo }));
    });
    sec.appendChild(grid);
    return sec;
  }

  function syllabusCards(ctx, list) {
    var cards = arr(list).filter(function (c) { return c && typeof c === 'object'; });
    var teacher = ctx.session.roles.teacher;
    if (!cards.length && !teacher) return null;
    var sec = el('div', 'course-part');
    sec.appendChild(el('h3', 'course-part-title', '各科課程大綱'));
    if (teacher) {
      sec.appendChild(el('p', 'course-manual-note',
        '這一區由老師手動維護：請 AI 助理在 data/courses/ 加一張卡（科目名稱、一段說明、大綱的網址），重新發布就會出現。（只有導師看得到這句提醒）'));
    }
    if (!cards.length) return sec;
    var grid = el('div', 'course-cards');
    cards.forEach(function (c, i) {
      var art = el('article', 'fun-card syllabus-card');
      art.setAttribute('data-n', String((i % 3) + 1));
      art.appendChild(el('h4', 'fun-title', c.title || ''));
      if (c.text) {
        var p = el('p', 'fun-text');
        p.appendChild(C.text.render(c.text));
        art.appendChild(p);
      }
      if (c.url) {
        var link = C.text.extLink(c.url, '看課程大綱');
        if (link.nodeType === 1) link.className = 'read-more';
        art.appendChild(link);
      }
      grid.appendChild(art);
    });
    sec.appendChild(grid);
    return sec;
  }

  function courseSection(ctx, doc) {
    var x = doc.data || {};
    var data = x.data && typeof x.data === 'object' ? x.data : {};
    var sec = el('section', 'course-section');
    var head = el('div', 'section-head');
    var titles = el('div', 'section-head-titles');
    titles.appendChild(el('h2', 'section-title', x.title || '課程'));
    head.appendChild(titles);
    if (x.visible === false) head.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
    sec.appendChild(head);
    if (Array.isArray(x.blocks) && x.blocks.length) {
      var body = el('div', 'post-body');
      body.appendChild(C.blocks.render(x.blocks, { store: ctx.store, owner: doc.path, demo: ctx.store.isDemo }));
      sec.appendChild(body);
    }
    var v = videoGrid(ctx, data.videos);
    if (v) sec.appendChild(v);
    var s = syllabusCards(ctx, data.cards);
    if (s) sec.appendChild(s);
    return sec;
  }

  function scheduleSection(doc) {
    var x = doc.data || {};
    var sec = el('section', 'course-section course-section--schedule');
    var head = el('div', 'section-head');
    var titles = el('div', 'section-head-titles');
    titles.appendChild(el('h2', 'section-title', x.title || '課表'));
    head.appendChild(titles);
    if (x.visible === false) head.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
    sec.appendChild(head);
    sec.appendChild(C.cards.schedule(x.data && typeof x.data === 'object' ? x.data : {}));
    return sec;
  }

  C.views.courses = function (ctx) {
    var container = el('div', 'container container--narrow');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Courses'));
    head.appendChild(el('h1', 'page-title', '課程'));
    head.appendChild(el('p', 'page-dek', '這學期的課程安排、課表與各科的課程大綱。'));
    container.appendChild(head);
    var body = el('div', 'courses');
    body.appendChild(C.dom.loading());
    container.appendChild(body);
    ctx.main.appendChild(container);
    var name = ctx.session.roles.teacher ? 'pages.byKind.teacher' : 'pages.byKind';
    return Promise.all([
      ctx.store.query(name, { kind: 'course' }),
      ctx.store.query(name, { kind: 'schedule' })
    ]).then(function (r) {
      C.dom.clear(body);
      r[0].items.forEach(function (doc) { body.appendChild(courseSection(ctx, doc)); });
      r[1].items.forEach(function (doc) { body.appendChild(scheduleSection(doc)); });
      if (!r[0].items.length && !r[1].items.length) body.appendChild(el('p', 'empty', '老師還沒有放課程資料。'));
    }, function (err) {
      C.dom.clear(body);
      body.appendChild(C.errors.box(err, { where: 'list' }));
    });
  };
})(typeof window !== 'undefined' ? window : globalThis);
