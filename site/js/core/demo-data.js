/* demo-data.js — 示範模式的內建資料（docs/ARCHITECTURE.md §2.8）。

   全部虛構：學生 A～Y 共 25 位（座號 01–25，每位的部落格至少一篇）、家長「學生 A 家長」＋ @example.com 信箱、
   一位示範同仁、一位示範導師。日期在執行時從「今天」往前推算。文字只是通用的班級生活佔位字，
   不描述任何真實的人、事件、地點、學校或課程。照片沒有檔案，由 demo-art.js 當場畫剪影。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var STUDENTS = 25;

  function letter(i) { return String.fromCharCode(65 + i); }       // 0 → A
  function seatOf(i) { return (i + 1 < 10 ? '0' : '') + (i + 1); } // 0 → 01
  function parentEmail(i) { return 'parent-' + letter(i).toLowerCase() + '@example.com'; }
  function parentAlias(i) { return 'demoalias' + letter(i).toLowerCase() + seatOf(i); }

  var TEACHER = { email: 'teacher@example.com', alias: 'demoteacher1', name: '示範導師' };
  var STAFF = { email: 'staff-1@example.com', alias: 'demostaff001', name: '示範同仁', seat: '03' };

  // ── 區塊小幫手 ────────────────────────────────────
  function sp(text, extra) {
    var s = { text: text };
    if (extra) Object.keys(extra).forEach(function (k) { s[k] = extra[k]; });
    return s;
  }
  function P() { return { t: 'p', spans: Array.prototype.slice.call(arguments) }; }
  function H(level, text) { return { t: 'h', level: level, text: text }; }
  function L(ordered, items) {
    return { t: 'list', ordered: ordered, items: items.map(function (x) { return { spans: [sp(x)] }; }) };
  }
  function Q(text) { return { t: 'quote', spans: [sp(text)] }; }
  function IMG(pid, caption) { return caption ? { t: 'img', pid: pid, caption: caption } : { t: 'img', pid: pid }; }
  function VIDEO(url, title) { return title ? { t: 'video', url: url, title: title } : { t: 'video', url: url }; }
  var HR = { t: 'hr' };

  function pid(n) {
    var h = n.toString(16);
    return 'de' + '00000000000000'.slice(h.length) + h;
  }

  /** 產生全部示範文件：回傳 { docs: [[路徑, 資料], …], info }。today：'YYYY-MM-DD' */
  function build(today) {
    var U = C.util;
    today = today || U.today();
    var docs = [];
    function put(path, data) { docs.push([path, data]); }
    function day(n) { return U.addDays(today, -n); }
    function at(n, hh, mm) {
      var d = U.parseYmd(day(n));
      d.setHours(hh, mm || 0, 0, 0);
      return d;
    }
    function photos(owner, list) {
      list.forEach(function (p, i) {
        var thumb = { w: 320, h: 240, order: i };
        if (p.caption) thumb.caption = p.caption;
        put(owner + '/thumbs/' + p.pid, thumb);
        put(owner + '/images/' + p.pid, { w: 1280, h: 960 });
      });
    }

    var cats = (C.config().categories && C.config().categories.length) ? C.config().categories : ['班級生活', '課堂', '活動'];
    function cat(i) { return cats[Math.min(i, cats.length - 1)]; }

    // ── 名單（allowlist／private_allowlist／parent_child_map）與名冊 ──
    var rosterList = [];
    for (var i = 0; i < STUDENTS; i++) {
      var key = C.emailKey(parentEmail(i));
      put('allowlist/' + key, { kind: 'parent', alias: parentAlias(i), updatedAt: at(30, 8) });
      put('parent_child_map/' + key, {
        seats: [seatOf(i)], kind: 'parent', active: true, relation: i % 2 === 0 ? '母' : '父',
        label: '座號 ' + seatOf(i) + ' 家長', updatedAt: at(30, 8)
      });
      rosterList.push({ seat: seatOf(i), name: '學生 ' + letter(i), displayName: '學生 ' + letter(i) });
      put('student_blogs/' + seatOf(i), {
        seat: seatOf(i), displayName: '學生 ' + letter(i),
        intro: i === 0 ? '（在這裡可以寫一段孩子的介紹：喜歡什麼、最近在忙什麼。）' : '',
        avatar: null, updatedAt: at(30, 8)
      });
    }
    put('allowlist/' + TEACHER.email, { kind: 'teacher', alias: TEACHER.alias, updatedAt: at(30, 8) });
    put('allowlist/' + STAFF.email, { kind: 'staff', alias: STAFF.alias, updatedAt: at(30, 8) });
    put('private_allowlist/' + TEACHER.email, { updatedAt: at(30, 8) });
    put('private_allowlist/' + C.emailKey(parentEmail(0)), { updatedAt: at(30, 8) });
    put('parent_child_map/' + STAFF.email, {
      seats: [STAFF.seat], kind: 'staff', active: true, label: '座號 ' + STAFF.seat + ' 同仁', updatedAt: at(30, 8)
    });
    put('roster/students', { students: rosterList, updatedAt: at(30, 8) });
    put('roster/links', { recordsKitUrl: '', classDocsIndexUrl: '', updatedAt: at(30, 8) });
    put('ops/backup_status', {
      nightly: { lastRunAt: at(0, 2), ok: true },
      weekly: { lastRunAt: at(3, 2), ok: true }
    });
    put('config/site', {
      teacherDisplayName: TEACHER.name,
      schoolName: '',
      studentsCount: STUDENTS,
      calendarIcsUrl: 'https://example.com/calendar/public/basic.ics',
      updatedAt: at(30, 8)
    });

    // ── 班級紀事 3 篇（每種區塊至少出現一次） ──
    var p1 = day(2) + '-morning-time';
    var p2 = day(5) + '-class-notes';
    var p3 = day(9) + '-outdoor-walk';

    var p1Photos = [{ pid: pid(1), caption: '（示範照片：這裡會放上課時拍的照片）' }, { pid: pid(2) }];
    photos('posts/' + p1, p1Photos);
    put('posts/' + p1, {
      title: '第一週的晨間時光', date: day(2), category: cat(0),
      excerpt: '新的學期開始了。這一週，孩子們慢慢熟悉每天早上的節奏：問早、整理書包，然後一起安靜下來準備上課。',
      coverPid: p1Photos[0].pid, coverThumb: null, photoCount: 2, visible: true,
      publishedAt: at(2, 18), updatedAt: at(2, 18)
    });
    put('posts/' + p1 + '/content/main', {
      blocks: [
        P(sp('新的學期開始了。這一週，孩子們慢慢熟悉每天早上的節奏：進教室先跟同學問早，把書包整理好，然後一起安靜下來，準備開始一天的學習。')),
        H(2, '早上的三件小事'),
        L(true, ['進教室先問早', '整理自己的桌面與書包', '一起深呼吸，準備上課']),
        IMG(p1Photos[0].pid, p1Photos[0].caption),
        P(sp('每天早上的時間不長，但'), sp('固定的節奏', { b: true }), sp('會讓孩子比較安心。'), sp('（這一段是示範文字。）', { i: true })),
        Q('孩子說：「早上先坐好，心就不會亂跑。」（示範引言）'),
        IMG(p1Photos[1].pid),
        HR,
        P(sp('想知道這個網站還能做什麼，可以看'), sp('使用說明（示範連結）', { href: 'https://example.com/' }), sp('。\n這一行是段落裡的換行。'))
      ],
      updatedAt: at(2, 18)
    });

    var p2Photos = [{ pid: pid(3), caption: '（示範照片：大家一起完成的作品）' }, { pid: pid(4) }, { pid: pid(5) }];
    photos('posts/' + p2, p2Photos);
    put('posts/' + p2, {
      title: '這一週的課堂小紀錄', date: day(5), category: cat(1),
      excerpt: '這一週大家分工合作，完成了一份共同的作品。完成之後，孩子們輪流說說自己負責的部分。',
      coverPid: p2Photos[0].pid, coverThumb: null, photoCount: 3, visible: true,
      publishedAt: at(5, 17), updatedAt: at(5, 17)
    });
    put('posts/' + p2 + '/content/main', {
      blocks: [
        P(sp('這一週大家分工合作，完成了一份共同的作品。完成之後，孩子們輪流說說自己負責的部分，也聽聽別人是怎麼想的。')),
        H(3, '大家一起完成的作品'),
        L(false, ['先想一想要做什麼', '分工合作，每個人負責一小部分', '完成後互相欣賞']),
        IMG(p2Photos[0].pid, p2Photos[0].caption),
        IMG(p2Photos[1].pid, '（示範照片）'),
        VIDEO('https://www.youtube.com/watch?v=DEMO0000001', '示範影片'),
        P(sp('（這裡可以寫下老師的觀察，或是想跟家長分享的一句話。）', { i: true }))
      ],
      updatedAt: at(5, 17)
    });

    var p3Photos = [{ pid: pid(6), caption: '（示範照片：出發前的集合）' }];
    photos('posts/' + p3, p3Photos);
    put('posts/' + p3, {
      title: '一起到戶外走走', date: day(9), category: cat(2),
      excerpt: '天氣很好的一天，我們到戶外走了一小段路，孩子們一路觀察身邊的花草與天空的顏色。',
      coverPid: p3Photos[0].pid, coverThumb: null, photoCount: 1, visible: true,
      publishedAt: at(9, 16), updatedAt: at(9, 16)
    });
    put('posts/' + p3 + '/content/main', {
      blocks: [
        P(sp('天氣很好的一天，我們到戶外走了一小段路。孩子們一路觀察身邊的花草，也抬頭看看天空的顏色。')),
        H(4, '出發前的小提醒'),
        L(false, ['穿方便走路的鞋子', '帶一瓶水', '跟著隊伍，不脫隊']),
        IMG(p3Photos[0].pid, p3Photos[0].caption),
        Q('回到教室後，有孩子說：「原來走慢一點，會看到更多東西。」（示範引言）'),
        VIDEO('https://example.com/video', '示範影片連結（外部網站）'),
        P(sp('（示範文字）'), sp('下次想再去走走。', { b: true, i: true }))
      ],
      updatedAt: at(9, 16)
    });

    // ── 留言（作者代號 alias；一則被老師收起） ──
    var c1 = 'demoComment000000001';
    put('posts/' + p1 + '/comments/' + c1, {
      authorName: '學生 A 家長', body: '讀完很有畫面，孩子回家也有說早上的事。',
      role: 'parent', authorAlias: parentAlias(0), status: 'visible', createdAt: at(2, 20, 5)
    });
    put('posts/' + p1 + '/comments/demoComment000000002', {
      authorName: TEACHER.name, body: '謝謝您的回饋，我們會繼續保持這個節奏。',
      role: 'teacher', authorAlias: TEACHER.alias, status: 'visible', createdAt: at(2, 21, 12), replyTo: c1
    });
    put('posts/' + p1 + '/comments/demoComment000000003', {
      authorName: '學生 C 家長', body: '（這則留言已經被老師收起，只有老師看得到。）',
      role: 'parent', authorAlias: parentAlias(2), status: 'hidden', createdAt: at(1, 7, 40)
    });
    put('posts/' + p1 + '/comments/demoComment000000004', {
      authorName: '學生 E 家長', body: '照片好可愛。更多說明可以看 https://example.com/help 。',
      role: 'parent', authorAlias: parentAlias(4), status: 'visible', createdAt: at(1, 12, 30)
    });
    put('posts/' + p2 + '/comments/demoComment000000005', {
      authorName: STAFF.name, body: '作品很用心！',
      role: 'staff', authorAlias: STAFF.alias, status: 'visible', createdAt: at(4, 9, 15)
    });

    // ── 已讀回條（doc id＝email 鍵；只有導師讀得到） ──
    function reads(slug, count, n) {
      for (var r = 0; r < count; r++) {
        put('posts/' + slug + '/reads/' + C.emailKey(parentEmail(r)), { kind: 'parent', readAt: at(n, 20, r) });
      }
      put('posts/' + slug + '/reads/' + STAFF.email, { kind: 'staff', readAt: at(n, 21) });
    }
    reads(p1, 16, 1);
    reads(p2, 9, 4);
    reads(p3, 5, 8);

    // ── 私密紀事 1 篇 ──
    var pv = day(4) + '-note-for-families';
    put('private_posts/' + pv, {
      title: '給家長的悄悄話（示範）', date: day(4),
      excerpt: '這是一篇只有私密名單裡的家長與老師看得到的示範紀事。',
      blocks: [
        P(sp('這裡的內容只有老師與私密名單裡的家長看得到。實際使用時，適合放需要比較小心的班級消息。')),
        IMG(pid(21), '（示範照片）'),
        P(sp('（示範文字）', { i: true }))
      ],
      coverPid: pid(21), coverThumb: null, photoCount: 1, visible: true,
      publishedAt: at(4, 19), updatedAt: at(4, 19)
    });
    photos('private_posts/' + pv, [{ pid: pid(21), caption: '（示範照片）' }]);
    put('private_posts/' + pv + '/reads/' + C.emailKey(parentEmail(0)), { kind: 'parent', readAt: at(3, 7) });
    put('private_posts/' + pv + '/comments/demoComment000000006', {
      authorName: '學生 A 家長', body: '收到，謝謝老師。',
      role: 'parent', authorAlias: parentAlias(0), status: 'visible', createdAt: at(3, 7, 5)
    });

    // ── 相簿 2 本空卡（尚未設定相簿連結） ──
    var a1 = day(3) + '-album-daily';
    var a2 = day(12) + '-album-works';
    put('albums/' + a1, {
      title: '班級生活剪影（示範）', date: day(3), order: 1,
      description: '（這本相簿還是空的。老師上傳照片後，這裡會出現縮圖。）',
      coverPid: null, coverThumb: null, photoCount: 0, videos: [], visible: true, updatedAt: at(3, 18)
    });
    put('albums/' + a2, {
      title: '一起做的作品（示範）', date: day(12), order: 2,
      description: '（這本相簿還是空的。）',
      coverPid: null, coverThumb: null, photoCount: 0, videos: [], visible: true, updatedAt: at(12, 18)
    });
    // 第三本有照片（程式畫的佔位圖）、兩支影片連結、一個外部相簿連結
    var a3 = day(6) + '-album-together';
    var a3Photos = [];
    for (var k = 0; k < 9; k++) {
      a3Photos.push(k % 3 === 0 ? { pid: pid(32 + k), caption: '（示範照片 ' + (k + 1) + '）' } : { pid: pid(32 + k) });
    }
    photos('albums/' + a3, a3Photos);
    put('albums/' + a3, {
      title: '大家一起的時光（示範）', date: day(6), order: 0,
      description: '（示範相簿：照片是程式畫的佔位圖。點一張照片就能看大圖，左右滑動換下一張。）',
      coverPid: a3Photos[0].pid, coverThumb: null, photoCount: a3Photos.length,
      videos: [
        { title: '示範影片（YouTube，點了才載入）', url: 'https://www.youtube.com/watch?v=DEMO0000002' },
        { title: '示範影片（其他網站的連結）', url: 'https://example.com/video/demo' }
      ],
      linkUrl: 'https://example.com/album/demo', visible: true, updatedAt: at(6, 18)
    });
    put('albums/' + a3 + '/comments/demoComment000000008', {
      authorName: '學生 D 家長', body: '照片好多，謝謝老師整理！',
      role: 'parent', authorAlias: parentAlias(3), status: 'visible', createdAt: at(5, 21)
    });
    put('albums/' + a1 + '/comments/demoComment000000007', {
      authorName: '學生 B 家長', body: '期待看到照片！',
      role: 'parent', authorAlias: parentAlias(1), status: 'visible', createdAt: at(2, 8)
    });

    // ── 單頁：首頁橫幅、關於我們、專題活動、課程、課表、獨立單頁 ──
    var banner = pid(16);
    put('pages/home/images/' + banner, { w: 1280, h: 960 });
    put('pages/home', {
      title: '首頁', kind: 'home', order: 0, visible: true, updatedAt: at(30, 8),
      data: { bannerText: '歡迎來到我們的班級網站。這裡記錄孩子們在學校的日常。（在這裡寫一句歡迎的話…）', bannerPid: banner }
    });
    var aboutPhotos = [{ pid: pid(17), caption: '（示範照片：教室的一角）' }, { pid: pid(18), caption: '（示範照片）' }];
    photos('pages/about', aboutPhotos);
    put('pages/about', {
      title: '關於我們', kind: 'about', order: 0, visible: true, updatedAt: at(30, 8),
      blocks: [
        H(2, '我們的班級'),
        P(sp('（在這裡寫班級的介紹：班上有幾位孩子、老師想怎麼陪伴他們……）')),
        H(3, '給家長的話'),
        P(sp('（在這裡寫想對家長說的話。）')),
        L(false, ['（聯絡老師的方式）', '（每週的固定作息）', '（需要家長協助的事）'])
      ]
    });
    put('pages/fun', {
      title: '專題活動', kind: 'fun', order: 0, visible: true, updatedAt: at(30, 8),
      blocks: [P(sp('（在這裡寫班上正在進行的有趣活動。）'))],
      data: {
        cards: [
          { title: '（活動名稱一）', text: '（在這裡寫一段介紹：大家在做什麼、做到哪裡了。）', pid: pid(19) },
          { title: '（活動名稱二）', text: '（在這裡寫一段介紹。）', pid: pid(20) },
          { title: '（活動名稱三）', text: '（還在找幫手的活動，也可以寫在這裡。）' }
        ]
      }
    });
    photos('pages/fun', [{ pid: pid(19) }, { pid: pid(20) }]);
    put('pages/course-sample', {
      title: '課程（示範）', kind: 'course', order: 0, visible: true, updatedAt: at(30, 8),
      blocks: [
        P(sp('（在這裡寫這學期的課程介紹：這學期大家會學什麼、用什麼方式學。）')),
        L(false, ['（第一段時間的安排）', '（第二段時間的安排）', '（學期末的分享）'])
      ],
      data: {
        videos: [{ title: '課程說明（示範影片）', url: 'https://www.youtube.com/watch?v=DEMO0000003' }],
        cards: [
          { title: '（科目一）', text: '（一段課程說明：這個科目這學期的重點。）', url: 'https://example.com/syllabus/demo-1' },
          { title: '（科目二）', text: '（一段課程說明。）' },
          { title: '（科目三）', text: '（課程大綱可以放雲端硬碟的分享連結。）', url: 'https://example.com/syllabus/demo-3' }
        ]
      }
    });
    put('pages/schedule-sample', {
      title: '課表（示範）', kind: 'schedule', order: 1, visible: true, updatedAt: at(30, 8),
      data: { rows: [
        { cells: ['', '一', '二', '三', '四', '五'] },
        { cells: ['第一節', '（科目）', '（科目）', '（科目）', '（科目）', '（科目）'] },
        { cells: ['第二節', '（科目）', '（科目）', '（科目）', '（科目）', '（科目）'] }
      ] }
    });
    put('pages/family-notes', {
      title: '給家長的小提醒（示範單頁）', kind: 'standalone', order: 0, visible: true, updatedAt: at(30, 8),
      blocks: [
        H(2, '這是一個獨立單頁'),
        P(sp('老師可以用獨立單頁放不常更新、但常被問到的資訊。')),
        L(true, ['（第一個提醒）', '（第二個提醒）']),
        P(sp('連結只會畫成安全的外部連結：'), sp('範例網站', { href: 'https://example.com/' }), sp('；不是 https 的連結只會剩下文字：'), sp('這一段', { href: 'http://example.com/' }), sp('。'))
      ]
    });

    // ── 部落格：座號 01 有一篇家長文、一篇導師文，導師文底下兩則對話（P2b 的頁面會用到） ──
    var e1 = day(3) + '-demo0001';
    var e2 = day(1) + '-demo0002';
    put('student_blogs/01/entries/' + e1, {
      title: '在家裡的一個下午（示範）', body: '（這是一篇家長寫的示範文章。）\n孩子回家後分享了學校的事。',
      date: day(3), author: 'parent', authorAlias: parentAlias(0),
      photos: [{ pid: '0', w: 1280, h: 960 }], visible: true, createdAt: at(3, 20)
    });
    put('student_blogs/01/entries/' + e1 + '/thumbs/0', { w: 320, h: 240, order: 0 });
    put('student_blogs/01/entries/' + e1 + '/images/0', { w: 1280, h: 960 });
    put('student_blogs/01/entries/' + e2, {
      title: '這一週在學校（示範）', body: '（這是一篇導師寫的示範文章。）',
      date: day(1), author: 'teacher', authorAlias: TEACHER.alias,
      photos: [], visible: true, createdAt: at(1, 17)
    });
    put('student_blogs/01/entries/' + e2 + '/blog_comments/demoBlogComment00001', {
      body: '謝謝老師！', role: 'parent', authorAlias: parentAlias(0), status: 'visible', createdAt: at(1, 19)
    });
    put('student_blogs/01/entries/' + e2 + '/blog_comments/demoBlogComment00002', {
      body: '不客氣，下週見。', role: 'teacher', authorAlias: TEACHER.alias, status: 'visible', createdAt: at(1, 20)
    });

    // 其他 24 個座號各一篇：三篇裡有兩篇是家長寫的（有的附一張照片），一篇是導師寫的
    var PARENT_TITLES = ['在家裡的一個下午（示範）', '週末一起做的小點心（示範）', '孩子今天分享的一件事（示範）', '一起散步的傍晚（示範）'];
    var TEACHER_TITLES = ['這一週在學校（示範）', '最近的小進步（示範）'];
    var firstEntries = { '01': e1 };
    for (var n = 1; n < STUDENTS; n++) {
      var seat = seatOf(n);
      var ago = 1 + (n % 9);
      var byTeacher = n % 3 === 0;
      var eid = day(ago) + '-demo' + (n < 10 ? '0' : '') + n + 'aa';
      var epath = 'student_blogs/' + seat + '/entries/' + eid;
      var withPhoto = !byTeacher && n % 2 === 1;
      put(epath, {
        title: byTeacher ? TEACHER_TITLES[n % TEACHER_TITLES.length] : PARENT_TITLES[n % PARENT_TITLES.length],
        body: byTeacher
          ? '（這是一篇導師寫的示範文章。）\n在這裡寫孩子最近在學校的樣子。'
          : '（這是一篇家長寫的示範文章。）\n在這裡寫孩子在家的點滴。\n\n  空白與換行都會照原樣保留。',
        date: day(ago), author: byTeacher ? 'teacher' : 'parent',
        authorAlias: byTeacher ? TEACHER.alias : parentAlias(n),
        photos: withPhoto ? [{ pid: '0', w: 1280, h: 960, caption: '（示範照片）' }] : [],
        visible: true, createdAt: at(ago, 19, n)
      });
      if (withPhoto) {
        put(epath + '/thumbs/0', { w: 320, h: 240, order: 0 });
        put(epath + '/images/0', { w: 1280, h: 960 });
      }
      if (n % 4 === 2) {
        put(epath + '/blog_comments/demoBlogComment' + (n < 10 ? '0' : '') + n + 'p', {
          body: '（示範）謝謝老師！', role: 'parent', authorAlias: parentAlias(n), status: 'visible', createdAt: at(ago, 21, n)
        });
      }
      firstEntries[seat] = eid;
    }

    // ── v1.1：座位表兩個方案（雲端只存座號；名字由名冊的稱呼當場補上） ──
    var straight = [];
    for (var sr = 0; sr < 5; sr++) {
      var srow = [];
      for (var sc = 0; sc < 5; sc++) srow.push(seatOf(sr * 5 + sc));
      straight.push(srow);
    }
    var pairs = [];
    for (var pr = 0; pr < 4; pr++) {
      var b0 = pr * 6;
      pairs.push([seatOf(b0), seatOf(b0 + 1), '-', seatOf(b0 + 2), seatOf(b0 + 3), '-', seatOf(b0 + 4), seatOf(b0 + 5)]);
    }
    pairs.push([seatOf(24), '']);
    var plan1 = day(20);
    var plan2 = day(3);
    put('seating/' + plan1, { title: '（示範）開學的座位', date: plan1, rows: straight.map(function (r) { return { seats: r }; }),
      note: '（示範備註：第一排最靠黑板。這段備註只有導師看得到。）', updatedAt: at(20, 8) });
    put('seating/' + plan2, { title: '（示範）兩兩一組', date: plan2, rows: pairs.map(function (r) { return { seats: r }; }),
      note: '', updatedAt: at(3, 8) });

    // ── v1.1：導師限定的個人照（程式畫的直式剪影；最後兩號還沒有照片）與家長合照（稱謂，不存姓名） ──
    for (var pp = 0; pp < STUDENTS - 2; pp++) {
      var ppid = pid(100 + pp);
      var powner = 'personal_photos/' + seatOf(pp);
      put(powner, { photoPids: [ppid], updatedAt: at(15, 8) });
      put(powner + '/thumbs/' + ppid, { w: 240, h: 320, order: 0 });
      put(powner + '/images/' + ppid, { w: 960, h: 1280 });
    }
    for (var fp = 0; fp < 8; fp++) {
      var fpid = pid(200 + fp);
      var fowner = 'parent_photo_display/' + seatOf(fp);
      put(fowner, {
        relations: fp === 0 ? ['母', '父'] : [fp % 2 === 0 ? '母' : '父'],
        note: fp === 0 ? '（示範備註：只有導師看得到。）' : '',
        photoPids: [fpid], updatedAt: at(15, 8)
      });
      put(fowner + '/thumbs/' + fpid, { w: 320, h: 240, order: 0 });
      put(fowner + '/images/' + fpid, { w: 1280, h: 960 });
    }

    // ── v1.1：每日一詩（示範文字：全部是為示範而寫的短句，不是任何作家的作品） ──
    var POEMS = [
      ['早晨', '窗外的光慢慢走進來\n落在桌上，也落在你的肩上\n\n今天，從一個深呼吸開始。', '（示範導讀：早上先停一下，看看光從哪裡來。）'],
      ['雨', '雨點敲著屋簷\n像在數數\n一、二、三，數到晴天。', ''],
      ['種子', '小小的種子躲在土裡\n不說話\n  它在等一個會發芽的日子。', '（示範導讀：等待也是一種長大。）'],
      ['風', '風翻開樹葉的書頁\n沙沙沙\n讀給路過的人聽。', ''],
      ['月亮', '月亮是夜晚的燈\n不太亮\n剛好照得見回家的路。', ''],
      ['影子', '我走，它也走\n我停，它也停\n原來它一直陪著我。', '（示範導讀：可以問問孩子，影子什麼時候最長？）'],
      ['石頭', '河邊的石頭圓圓的\n被水摸了很久很久\n才變得這麼溫和。', ''],
      ['麵包', '烤箱裡的麵包慢慢長大\n整間屋子\n都聞得到等待的味道。', ''],
      ['腳印', '沙灘上的腳印\n一個接著一個\n浪來了，又把它們收回去。', ''],
      ['星星', '星星不會說話\n可是每天晚上\n都準時出來打招呼。', '']
    ];
    var poemMonths = {};
    POEMS.forEach(function (x, k) {
      var pd = day(k);
      var it = { date: pd, title: x[0] + '（示範）', author: '示範文字', text: x[1], source: '示範用自寫短句' };
      if (x[2]) it.guide = x[2];
      (poemMonths[pd.slice(0, 7)] = poemMonths[pd.slice(0, 7)] || []).push(it);
    });
    Object.keys(poemMonths).forEach(function (ym) {
      var items = poemMonths[ym].sort(function (a, b) { return a.date < b.date ? -1 : 1; });
      put('pages/poems-' + ym, {
        title: '每日一詩（' + ym.slice(0, 4) + ' 年 ' + parseInt(ym.slice(5, 7), 10) + ' 月）', kind: 'poem', order: 0,
        visible: true, updatedAt: at(10, 8), data: { month: ym, items: items }
      });
    });

    return {
      docs: docs,
      info: {
        posts: [p1, p2, p3], privatePost: pv, albums: [a3, a1, a2], albumWithPhotos: a3,
        pages: ['about', 'fun', 'family-notes'], entries: firstEntries, teacherEntry: e2,
        seatingPlans: [plan2, plan1], poemMonths: Object.keys(poemMonths).sort(),
        poemDays: POEMS.map(function (x, k) { return day(k); })
      }
    };
  }

  /** 示範角色 → Session（只決定畫面長什麼樣，不模擬權限） */
  function session(role, seat) {
    var roles = C.emptyRoles();
    if (role === 'signed-out' || !role) return { state: 'signed-out', user: null, roles: roles };
    var user;
    if (role === 'teacher') {
      user = { uid: 'demo-teacher', email: TEACHER.email, emailKey: TEACHER.email, provider: 'google.com' };
      roles = { teacher: true, reader: true, privateReader: true, kind: 'teacher', alias: TEACHER.alias, seats: [], seatKind: null };
    } else if (role === 'staff') {
      user = { uid: 'demo-staff', email: STAFF.email, emailKey: STAFF.email, provider: 'google.com' };
      roles = { teacher: false, reader: true, privateReader: false, kind: 'staff', alias: STAFF.alias, seats: [STAFF.seat], seatKind: 'staff' };
    } else if (role === 'reader') {
      // 用 email 連結登入的家長：只是班網讀者，沒有座號
      user = { uid: 'demo-reader', email: parentEmail(1), emailKey: parentEmail(1), provider: 'emailLink' };
      roles = { teacher: false, reader: true, privateReader: false, kind: 'parent', alias: parentAlias(1), seats: [], seatKind: null };
    } else {
      // 'parent'（選座號）與 'private'（學生 A 家長，也是私密讀者）
      var s = role === 'private' ? '01' : (C.seats.valid(seat) && parseInt(seat, 10) <= STUDENTS ? seat : '01');
      var i = parseInt(s, 10) - 1;
      user = { uid: 'demo-parent-' + s, email: parentEmail(i), emailKey: C.emailKey(parentEmail(i)), provider: 'google.com' };
      roles = { teacher: false, reader: true, privateReader: i === 0, kind: 'parent', alias: parentAlias(i), seats: [s], seatKind: 'parent' };
    }
    return { state: 'ready', user: user, roles: roles };
  }

  C.demoData = {
    STUDENTS: STUDENTS,
    TEACHER: TEACHER,
    STAFF: STAFF,
    build: build,
    session: session,
    parentLabel: function (seat) { return '學生 ' + C.seats.letter(seat) + ' 家長'; }
  };
})(typeof window !== 'undefined' ? window : globalThis);
