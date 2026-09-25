/* paths.js — 全前端「唯一」組 Firestore 路徑的地方（docs/ARCHITECTURE.md §2.4）。

   每個函式先驗參數格式（docs/DATA-MODEL.md §0.4），不合就丟 StoreError('invalid')。
   網址參數（post.html?s=…）一律先經過這裡才用；像 s=../x 這種值會直接被當成「找不到」。
   頁面程式（views/）不准自己拼路徑字串。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var RE = {
    slug: /^[0-9]{4}-[0-9]{2}-[0-9]{2}(-[a-z0-9]+)+$/,
    pageId: /^[a-z][a-z0-9-]{0,39}$/,
    pid: /^([0-9a-f]{16}|[0-2])$/,
    postId: /^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}$/,
    cid: /^[A-Za-z0-9]{1,64}$/,
    seat: /^(0[1-9]|[1-3][0-9]|40)$/,
    // 已經正規化過的 email 鍵（小寫、剛好一個 @）
    key: /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/
  };

  var THREAD_KINDS = { post: 'posts', album: 'albums', 'private': 'private_posts' };

  function bad(what) {
    throw new C.StoreError('invalid', '路徑參數格式不對：' + what);
  }

  function slug(s) {
    if (typeof s !== 'string' || s.length > 80 || !RE.slug.test(s)) bad('slug');
    return s;
  }
  function pageId(s) {
    if (typeof s !== 'string' || !RE.pageId.test(s)) bad('pageId');
    return s;
  }
  function pid(s) {
    if (typeof s !== 'string' || !RE.pid.test(s)) bad('pid');
    return s;
  }
  function cid(s) {
    if (typeof s !== 'string' || !RE.cid.test(s)) bad('cid');
    return s;
  }
  function seat(s) {
    if (typeof s !== 'string' || !RE.seat.test(s)) bad('seat');
    return s;
  }
  function postId(s) {
    if (typeof s !== 'string' || !RE.postId.test(s)) bad('postId');
    return s;
  }
  function key(s) {
    if (typeof s !== 'string' || !RE.key.test(s) || s.split('@').length !== 2) bad('emailKey');
    return s;
  }

  var THREAD_RE = /^(posts|albums|private_posts)\/([^/]+)$/;
  var ENTRY_RE = /^student_blogs\/([^/]+)\/entries\/([^/]+)$/;

  function threadPath(p) {
    var m = typeof p === 'string' ? THREAD_RE.exec(p) : null;
    if (!m) bad('thread');
    slug(m[2]);
    return p;
  }
  function entryPath(p) {
    var m = typeof p === 'string' ? ENTRY_RE.exec(p) : null;
    if (!m) bad('entry');
    seat(m[1]);
    postId(m[2]);
    return p;
  }
  var MONTH_RE = /^[0-9]{4}-(0[1-9]|1[0-2])$/;
  function month(s) {
    if (typeof s !== 'string' || !MONTH_RE.test(s)) bad('month');
    return s;
  }

  /** 照片的主人文件：紀事、相簿、私密紀事、單頁、部落格文章；v1.1 導師限定的個人照與家長合照 */
  function ownerPath(p) {
    if (typeof p !== 'string') bad('owner');
    if (THREAD_RE.test(p)) return threadPath(p);
    var m = /^pages\/([^/]+)$/.exec(p);
    if (m) { pageId(m[1]); return p; }
    if (ENTRY_RE.test(p)) return entryPath(p);
    m = /^(personal_photos|parent_photo_display)\/([^/]+)$/.exec(p);
    if (m) { seat(m[2]); return p; }
    return bad('owner');
  }

  var P = {
    RE: RE,
    post: function (s) { return 'posts/' + slug(s); },
    postContent: function (s) { return 'posts/' + slug(s) + '/content/main'; },
    album: function (s) { return 'albums/' + slug(s); },
    privatePost: function (s) { return 'private_posts/' + slug(s); },
    page: function (id) { return 'pages/' + pageId(id); },
    thread: function (kind, s) {
      if (!Object.prototype.hasOwnProperty.call(THREAD_KINDS, kind)) bad('thread kind');
      return THREAD_KINDS[kind] + '/' + slug(s);
    },
    comment: function (thread, id) { return threadPath(thread) + '/comments/' + cid(id); },
    receipt: function (thread, k) { return threadPath(thread) + '/reads/' + key(k); },
    blog: function (s) { return 'student_blogs/' + seat(s); },
    entry: function (s, id) { return 'student_blogs/' + seat(s) + '/entries/' + postId(id); },
    blogComment: function (entry, id) { return entryPath(entry) + '/blog_comments/' + cid(id); },
    /** 部落格文章底下的對話串（集合路徑，給 store.add 用） */
    blogComments: function (entry) { return entryPath(entry) + '/blog_comments'; },
    /** 留言串（集合路徑，給 store.add 用） */
    comments: function (thread) { return threadPath(thread) + '/comments'; },
    thumb: function (owner, p) { return ownerPath(owner) + '/thumbs/' + pid(p); },
    image: function (owner, p) { return ownerPath(owner) + '/images/' + pid(p); },
    allow: function (k) { return 'allowlist/' + key(k); },
    privateAllow: function (k) { return 'private_allowlist/' + key(k); },
    parentMap: function (k) { return 'parent_child_map/' + key(k); },
    teacherProbe: function () { return 'site_access/teacher'; },
    configSite: function () { return 'config/site'; },
    rosterStudents: function () { return 'roster/students'; },
    rosterLinks: function () { return 'roster/links'; },
    opsBackup: function () { return 'ops/backup_status'; },
    /** v1.1：導師限定的個人照、家長合照（照片的主人文件）；每日一詩（一個月一份單頁） */
    personalPhoto: function (s) { return 'personal_photos/' + seat(s); },
    parentPhoto: function (s) { return 'parent_photo_display/' + seat(s); },
    poemMonth: function (ym) { return 'pages/poems-' + month(ym); },
    isMonth: function (s) { return typeof s === 'string' && MONTH_RE.test(s); },

    // 驗證用（Store 與 views 共用）
    isSlug: function (s) { return typeof s === 'string' && s.length <= 80 && RE.slug.test(s); },
    isPageId: function (s) { return typeof s === 'string' && RE.pageId.test(s); },
    checkThread: threadPath,
    checkOwner: ownerPath,
    checkEntry: entryPath,

    /** 留言文件路徑 → { kind: 'post'|'album'|'private', slug, thread }（留言後台用）；認不得回 null。 */
    parseComment: function (p) {
      var m = /^(posts|albums|private_posts)\/([^/]+)\/comments\/([^/]+)$/.exec(String(p || ''));
      if (!m || !RE.slug.test(m[2])) return null;
      var kind = m[1] === 'posts' ? 'post' : (m[1] === 'albums' ? 'album' : 'private');
      return { kind: kind, slug: m[2], thread: m[1] + '/' + m[2], cid: m[3] };
    },

    /** 文件路徑的基本安全檢查：段數、空段、. 與 ..（Store 的 get／set 用） */
    isDocPath: function (p) {
      if (typeof p !== 'string' || !p || p.length > 700) return false;
      var segs = p.split('/');
      if (segs.length % 2 !== 0) return false;
      for (var i = 0; i < segs.length; i++) {
        if (!segs[i] || segs[i] === '.' || segs[i] === '..' || /^__.*__$/.test(segs[i])) return false;
      }
      return true;
    },
    isCollectionPath: function (p) {
      if (typeof p !== 'string' || !p || p.length > 700) return false;
      var segs = p.split('/');
      if (segs.length % 2 !== 1) return false;
      for (var i = 0; i < segs.length; i++) {
        if (!segs[i] || segs[i] === '.' || segs[i] === '..' || /^__.*__$/.test(segs[i])) return false;
      }
      return true;
    }
  };

  C.paths = P;
})(typeof window !== 'undefined' ? window : globalThis);
