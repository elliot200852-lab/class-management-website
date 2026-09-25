/* validate.js — 瀏覽器寫入前的欄位檢查（docs/ARCHITECTURE.md §2.5，上限照 docs/DATA-MODEL.md）。

   這一層只為了使用體驗：寫入前先檢查，免得白送一個會被規則擋下的請求，也能在表單旁說清楚哪裡要改。
   真正的邊界永遠是安全規則。瀏覽器只准寫下表這幾種路徑，其他一律 StoreError('invalid')。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var LIMITS = {
    commentName: [1, 20],
    commentBody: [1, 500],
    entryTitle: [1, 200],
    entryBody: [1, 10000],
    caption: 300,
    thumbData: 49152,
    imageData: 716800,
    thumbSide: 480,
    imageSide: 1600,
    photosPerEntry: 3,
    batchOps: 7
  };

  var SLUG = '[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[a-z0-9]+)+';
  var CID = '[A-Za-z0-9]{1,64}';
  var KEY = '[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}';
  var SEAT = '(?:0[1-9]|[1-3][0-9]|40)';
  var POSTID = '[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}';
  var ENTRY = 'student_blogs/' + SEAT + '/entries/' + POSTID;

  function re(s) { return new RegExp('^' + s + '$'); }

  function fail(msg) { throw new C.StoreError('invalid', msg); }

  function len(s) { return Array.from(String(s)).length; }

  function str(data, field, min, max, label) {
    var v = data[field];
    if (typeof v !== 'string') fail((label || field) + ' 必須是文字');
    var n = len(v);
    if (n < min) fail(min <= 1 ? (label || field) + ' 不能是空的' : (label || field) + ' 至少 ' + min + ' 字');
    if (n > max) fail((label || field) + ' 最多 ' + max + ' 字（現在 ' + n + ' 字）');
    return v;
  }

  function onlyKeys(data, allowed) {
    Object.keys(data).forEach(function (k) {
      if (allowed.indexOf(k) < 0) fail('不准寫入的欄位：' + k);
    });
  }

  function requireKeys(data, required) {
    required.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(data, k)) fail('少了欄位：' + k);
    });
  }

  function serverTime(data, field) {
    if (!C.isServerTime(data[field])) fail(field + ' 必須是伺服器時間');
  }

  function alias(v) {
    if (typeof v !== 'string' || !/^[a-z0-9]{12}$/.test(v)) fail('作者代號格式不對');
  }

  function base64(v, max, label) {
    if (typeof v !== 'string' || !v || v.length > max || !/^[A-Za-z0-9+/]+={0,2}$/.test(v)) {
      fail(label + ' 的照片資料格式不對或太大');
    }
  }

  function intIn(v, min, max, label) {
    if (typeof v !== 'number' || Math.floor(v) !== v || v < min || v > max) fail(label + ' 必須是 ' + min + '–' + max + ' 的整數');
  }

  // ── 各種寫入的欄位契約 ─────────────────────────────
  function commentCreate(path, data) {
    requireKeys(data, ['authorName', 'body', 'role', 'authorAlias', 'status', 'createdAt']);
    onlyKeys(data, ['authorName', 'body', 'role', 'authorAlias', 'status', 'createdAt', 'replyTo']);
    str(data, 'authorName', LIMITS.commentName[0], LIMITS.commentName[1], '署名');
    str(data, 'body', LIMITS.commentBody[0], LIMITS.commentBody[1], '留言');
    if (['teacher', 'parent', 'staff'].indexOf(data.role) < 0) fail('身分標籤不對');
    alias(data.authorAlias);
    if (data.status !== 'visible') fail('新留言必須是顯示狀態');
    serverTime(data, 'createdAt');
    if (data.replyTo !== undefined && (typeof data.replyTo !== 'string' || !re(CID).test(data.replyTo))) fail('回覆對象格式不對');
  }

  function statusOnly(path, data) {
    onlyKeys(data, ['status']);
    if (data.status !== 'visible' && data.status !== 'hidden') fail('狀態只能是顯示或收起');
  }

  function receipt(path, data) {
    requireKeys(data, ['kind', 'readAt']);
    onlyKeys(data, ['kind', 'readAt']);
    if (data.kind !== 'parent' && data.kind !== 'staff') fail('回條身分不對');
    serverTime(data, 'readAt');
  }

  function entryCreate(path, data) {
    var keys = ['title', 'body', 'date', 'author', 'authorAlias', 'photos', 'visible', 'createdAt'];
    requireKeys(data, keys);
    onlyKeys(data, keys);
    str(data, 'title', LIMITS.entryTitle[0], LIMITS.entryTitle[1], '標題');
    str(data, 'body', LIMITS.entryBody[0], LIMITS.entryBody[1], '內文');
    if (typeof data.date !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(data.date)) fail('日期格式不對');
    if (data.author !== 'parent' && data.author !== 'teacher') fail('作者身分不對');
    alias(data.authorAlias);
    if (!Array.isArray(data.photos) || data.photos.length > LIMITS.photosPerEntry) fail('照片最多 3 張');
    data.photos.forEach(function (p, i) {
      if (!p || typeof p !== 'object') fail('照片資料不對');
      onlyKeys(p, ['pid', 'w', 'h', 'caption']);
      if (p.pid !== String(i)) fail('照片編號不對');
      intIn(p.w, 1, LIMITS.imageSide, '照片寬度');
      intIn(p.h, 1, LIMITS.imageSide, '照片高度');
      if (p.caption !== undefined && (typeof p.caption !== 'string' || len(p.caption) > LIMITS.caption)) fail('圖說最多 300 字');
    });
    if (data.visible !== true) fail('新文章必須是顯示狀態');
    serverTime(data, 'createdAt');
  }

  function entryUpdate(path, data) {
    onlyKeys(data, ['title', 'body', 'visible', 'updatedAt']);
    if (data.title !== undefined) str(data, 'title', LIMITS.entryTitle[0], LIMITS.entryTitle[1], '標題');
    if (data.body !== undefined) str(data, 'body', LIMITS.entryBody[0], LIMITS.entryBody[1], '內文');
    if (data.visible !== undefined && typeof data.visible !== 'boolean') fail('顯示狀態不對');
    serverTime(data, 'updatedAt');
  }

  function thumbCreate(path, data) {
    requireKeys(data, ['data', 'w', 'h', 'order']);
    onlyKeys(data, ['data', 'w', 'h', 'order']);
    base64(data.data, LIMITS.thumbData, '縮圖');
    intIn(data.w, 1, LIMITS.thumbSide, '縮圖寬度');
    intIn(data.h, 1, LIMITS.thumbSide, '縮圖高度');
    var pidNum = parseInt(path.charAt(path.length - 1), 10);
    if (data.order !== pidNum) fail('縮圖順序不對');
  }

  function imageCreate(path, data) {
    requireKeys(data, ['data', 'w', 'h']);
    onlyKeys(data, ['data', 'w', 'h']);
    base64(data.data, LIMITS.imageData, '顯示圖');
    intIn(data.w, 1, LIMITS.imageSide, '顯示圖寬度');
    intIn(data.h, 1, LIMITS.imageSide, '顯示圖高度');
  }

  function blogCommentCreate(path, data) {
    var keys = ['body', 'role', 'authorAlias', 'status', 'createdAt'];
    requireKeys(data, keys);
    onlyKeys(data, keys);
    str(data, 'body', 1, 500, '留言');
    if (data.role !== 'parent' && data.role !== 'teacher') fail('身分標籤不對');
    alias(data.authorAlias);
    if (data.status !== 'visible') fail('新留言必須是顯示狀態');
    serverTime(data, 'createdAt');
  }

  var RULES = [
    { op: 'add', re: re('(?:posts|albums|private_posts)/' + SLUG + '/comments'), check: commentCreate },
    { op: 'update', re: re('(?:posts|albums|private_posts)/' + SLUG + '/comments/' + CID), check: statusOnly },
    { op: 'set', re: re('(?:posts|private_posts)/' + SLUG + '/reads/' + KEY), check: receipt },
    { op: 'set', re: re(ENTRY), check: entryCreate },
    { op: 'set', re: re(ENTRY + '/thumbs/[0-2]'), check: thumbCreate },
    { op: 'set', re: re(ENTRY + '/images/[0-2]'), check: imageCreate },
    { op: 'update', re: re(ENTRY), check: entryUpdate },
    { op: 'add', re: re(ENTRY + '/blog_comments'), check: blogCommentCreate },
    { op: 'update', re: re(ENTRY + '/blog_comments/' + CID), check: statusOnly }
  ];

  /** op：'add'（path 是集合）｜'set'｜'update'（path 是文件）。不合就丟 StoreError('invalid')。 */
  function write(op, path, data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) fail('寫入的資料必須是物件');
    for (var i = 0; i < RULES.length; i++) {
      var r = RULES[i];
      if (r.op === op && r.re.test(String(path))) {
        r.check(String(path), data);
        return true;
      }
    }
    return fail('瀏覽器不能寫這個位置');
  }

  /** 批次：1–7 個 { op: 'set'|'update', path, data } */
  function batch(ops) {
    if (!Array.isArray(ops) || ops.length < 1 || ops.length > LIMITS.batchOps) fail('一次最多 7 個寫入');
    ops.forEach(function (o) {
      if (!o || (o.op !== 'set' && o.op !== 'update')) fail('批次只收 set／update');
      write(o.op, o.path, o.data);
    });
    return true;
  }

  C.validate = { LIMITS: LIMITS, write: write, batch: batch, len: len };
})(typeof window !== 'undefined' ? window : globalThis);
