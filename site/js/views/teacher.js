/* views/teacher.js — 導師專用頁 teacher.html（docs/ARCHITECTURE.md §3.1、docs/DATA-MODEL.md §2.16–§2.18、§2.21）。

   兩個分頁：「工具」（teacher.html）與「座位表」（teacher.html#/seating，畫法在 views/seating.js）。
   工具分頁的入口卡片：
     · 學生觀察與課程紀錄 → teacher-records-kit（另一個開源工具、另一個 Firebase 專案）。網址在 roster/links
       （只有導師讀得到）；沒設就說明「尚未安裝」並附官方頁面連結。本頁不讀、不寫 kit 的任何資料。
     · 班級文件 → 雲端硬碟同步夾裡的文件索引（roster/links.classDocsIndexUrl；沒設就說明怎麼設）。
     · 網站管理捷徑（留言後台、全班部落格、座位表、個人照、匯出 PDF、每日一詩……）。
     · 備份狀態（ops/backup_status；DATA-MODEL §2.17）：v1 沒有排程，備份是老師叫 AI 助理跑的，
       所以門檻跟 scripts/status.py 一樣（正本 scripts/lib/thresholds.py）——7 天沒成功才提醒、14 天加重語氣
       （tests/test_v11_site.py 比對兩邊的數字）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var KIT_REPO = 'https://github.com/elliot200852-lab/teacher-records-kit';
  // 跟 scripts/lib/thresholds.py（status.py 讀的那一份）同一組數字：備份是手動的，不是每夜排程
  var BACKUP_REMIND_DAYS = 7;
  var BACKUP_URGENT_DAYS = 14;
  // ops/backup_status 的兩條心跳：欄位名沿用 nightly／weekly，實際是這兩個指令寫的（DATA-MODEL §2.17）
  var BACKUP_LINES = [
    { key: 'nightly', label: '學生部落格備份', cmd: 'backup.py blogs' },
    { key: 'weekly', label: '網站資料庫備份', cmd: 'backup.py firestore' }
  ];

  function teacherOnly(main) {
    var box = el('div', 'container container--narrow');
    var n = el('div', 'notice');
    n.appendChild(el('p', null, '這一頁只有導師能用。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    main.appendChild(box);
  }

  function card(cls, title, eyebrow) {
    var art = el('article', 'tool-card ' + (cls || ''));
    if (eyebrow) art.appendChild(el('p', 'eyebrow', eyebrow));
    art.appendChild(el('h2', 'tool-title', title));
    return art;
  }

  function linkButton(url, text) {
    var a = C.text.extLink(url, text);
    if (a.nodeType === 1) a.className = 'btn btn--primary';
    return a;
  }

  function recordsCard(links) {
    var c = card('tool-card--records', '學生觀察與課程紀錄', 'Records');
    var url = C.text.safeUrl(links && links.recordsKitUrl);
    if (url) {
      c.appendChild(el('p', 'tool-text', '學生個別觀察、全班觀察與課程紀錄都在 teacher-records-kit 裡（另開新分頁）。'));
      c.appendChild(linkButton(url.href, '打開學生觀察與課程紀錄'));
      return c;
    }
    c.appendChild(el('p', 'tool-status', '尚未安裝 teacher-records-kit'));
    c.appendChild(el('p', 'tool-text',
      '學生個別觀察、全班觀察與課程紀錄不放在這個網站；需要的話，可以另外用免費的開源紀錄工具 teacher-records-kit。' +
      '想用的話，把它的官方頁面交給你的 AI 助理請它安裝；裝好之後請 AI 助理把網址設定進來，這裡就會出現入口。'));
    c.appendChild(C.text.extLink(KIT_REPO, 'teacher-records-kit 官方頁面（GitHub）'));
    return c;
  }

  function docsCard(links) {
    var c = card('tool-card--docs', '班級文件', 'Documents');
    var url = C.text.safeUrl(links && links.classDocsIndexUrl);
    c.appendChild(el('p', 'tool-text',
      '班級文件放在你電腦裡的 Google 雲端硬碟同步夾：「01_機密（只有導師）／班級文件」。' +
      'AI 助理每次幫你歸檔文件時，會順便更新那裡的文件索引（index.md），一眼看到全部文件放在哪裡。'));
    if (url) {
      c.appendChild(linkButton(url.href, '打開班級文件索引'));
    } else {
      c.appendChild(el('p', 'tool-status', '還沒有設定入口'));
      c.appendChild(el('p', 'tool-text',
        '在雲端硬碟網頁版打開那份文件索引、複製網址，交給 AI 助理設定進來，這裡就會出現按鈕。只有你看得到這張卡片。'));
    }
    return c;
  }

  function shortcutsCard() {
    var c = card('tool-card--shortcuts', '網站管理捷徑', 'Shortcuts');
    var ul = el('ul', 'tool-links');
    var items = [
      ['留言後台（顯示／收起留言）', C.route.href('admin')],
      ['我的孩子（全班部落格、未讀）', C.route.href('my-child', null, 'admin')],
      ['座位表', C.route.href('teacher', null, 'seating')],
      ['個人照與家長合照（只有你看得到）', C.route.href('family-photos')],
      ['匯出 PDF：班級紀事', C.route.href('blog-print')],
      ['匯出 PDF：學生部落格', C.route.href('my-child-print')],
      ['每日一詩', C.route.href('poem')],
      ['私密紀事', C.route.href('private')],
      ['相簿', C.route.href('gallery')],
      ['班級紀事', C.route.href('blog')]
    ];
    items.forEach(function (it) {
      var li = el('li');
      li.appendChild(C.dom.link(it[1], null, it[0]));
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  /** 一條備份線的狀態：{ level: 'ok'|'warn'|'urgent', text }。now 給測試用。 */
  function lineStatus(line, label, now) {
    var last = line && line.lastRunAt;
    var t = C.seen.millis(last);
    if (!t) return { level: 'warn', text: label + '：還沒有紀錄（第一次備份跑完後這裡會顯示時間）' };
    var days = Math.floor(((now || Date.now()) - t) / 86400000);
    var when = C.util.fmtTime(last);
    if (line.ok === false) return { level: 'warn', text: label + '：上一次（' + when + '）沒有成功，請 AI 助理看一下備份' };
    if (days >= BACKUP_URGENT_DAYS) return { level: 'urgent', text: label + '：已經 ' + days + ' 天沒有備份了（上一次 ' + when + '），今天就請 AI 助理跑一次' };
    if (days >= BACKUP_REMIND_DAYS) return { level: 'warn', text: label + '：' + days + ' 天沒有備份了（上一次 ' + when + '）' };
    return { level: 'ok', text: label + '：正常（上一次 ' + when + '）' };
  }

  function backupCard(status) {
    var c = card('tool-card--backup', '備份狀態', 'Backup');
    var ul = el('ul', 'backup-list');
    BACKUP_LINES.forEach(function (b) {
      var r = lineStatus(status && status[b.key], b.label);
      ul.appendChild(el('li', r.level === 'ok' ? 'is-ok' : 'is-warn', (r.level === 'ok' ? '✓ ' : '！ ') + r.text));
    });
    c.appendChild(ul);
    c.appendChild(el('p', 'tool-text', '備份不會自動跑：跟 AI 助理說「備份」，它會寫進你電腦裡的 Google 雲端硬碟同步夾（05_全站備份）。' +
      '超過 ' + BACKUP_REMIND_DAYS + ' 天沒備份，這裡和 AI 助理每次開工的檢查都會提醒你。'));
    return c;
  }

  function tabs(sub) {
    var nav = el('nav', 'tabs no-print');
    nav.setAttribute('aria-label', '導師專用的分頁');
    [['', '工具'], ['seating', '座位表']].forEach(function (t) {
      var a = C.dom.link(C.route.href('teacher', null, t[0] || null), 'tab' + (sub === t[0] ? ' is-current' : ''), t[1]);
      if (sub === t[0]) a.setAttribute('aria-current', 'page');
      nav.appendChild(a);
    });
    return nav;
  }

  C.views.teacher = function (ctx) {
    var main = ctx.main;
    if (!ctx.session.roles.teacher) { teacherOnly(main); return null; }
    var store = ctx.store;
    var sub = ctx.route.sub === 'seating' ? 'seating' : '';
    var container = el('div', 'container');
    var head = el('header', 'page-header no-print');
    head.appendChild(el('p', 'eyebrow', 'Teacher only'));
    head.appendChild(el('h1', 'page-title', sub === 'seating' ? '座位表' : '導師專用'));
    head.appendChild(el('p', 'page-dek', sub === 'seating'
      ? '只有導師看得到。名字用名冊上的稱呼當場補上；點一個座位可以標記起來。'
      : '只有導師看得到這一頁。常用的工具入口都在這裡。'));
    container.appendChild(head);
    container.appendChild(tabs(sub));
    main.appendChild(container);
    if (sub === 'seating') {
      ctx.setTitle('座位表');
      return C.seating.render(ctx, container);
    }
    var grid = el('div', 'tool-grid');
    container.appendChild(grid);
    function orNull(p) { return p.then(function (d) { return d ? d.data : null; }, function () { return null; }); }
    return Promise.all([
      orNull(store.get(C.paths.rosterLinks())),
      orNull(store.get(C.paths.opsBackup()))
    ]).then(function (r) {
      grid.appendChild(recordsCard(r[0]));
      grid.appendChild(docsCard(r[0]));
      grid.appendChild(shortcutsCard());
      grid.appendChild(backupCard(r[1]));
    });
  };

  C.teacherTools = { lineStatus: lineStatus, BACKUP_REMIND_DAYS: BACKUP_REMIND_DAYS, BACKUP_URGENT_DAYS: BACKUP_URGENT_DAYS };
})(typeof window !== 'undefined' ? window : globalThis);
