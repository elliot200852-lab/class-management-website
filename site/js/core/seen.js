/* seen.js — 導師端「我的孩子」的未讀提示（docs/DATA-MODEL.md §2.14）。

   v1 沒有任何背景程式替文章維護「最後留言時間」「未讀數」這類欄位，所以未讀是導師端網頁**當場算**的：
     · 家長新發的文：entries.recentParent（全班最新 100 篇家長文，集合群組查詢）
     · 家長新留的話：blogComments.recentParent（全班最新 200 則家長留言，落在導師的文章底下也算）
     · 「已經看到哪裡」：導師這台裝置的 localStorage（每個座號一個時間），打開那個座號的文章列表就算看過
   換一台裝置、清掉瀏覽器資料，舊的會再亮一次提示——這只是提醒，不影響任何資料。
   localStorage 每一次存取都包 try/catch：私密視窗、被封鎖時畫面照常，只是提示記不住。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var KEY = 'cmw-blog-seen-v1';
  var SEAT_PATH_RE = /^student_blogs\/([^/]+)\/entries\//;
  // 這一頁（同一次載入）裡，全班格算出來的「每個座號最新一筆家長動態」：打開座號時拿來標「看過了」
  var latestMemo = {};

  /** Date（或長得像 Date 的物件）→ 毫秒；伺服器時間還沒填上（null）→ 0 */
  function millis(d) {
    if (!d || typeof d.getTime !== 'function') return 0;
    var t = d.getTime();
    return typeof t === 'number' && isFinite(t) ? t : 0;
  }

  /** 文件路徑（student_blogs/{seat}/entries/…）→ 座號；認不得回 null */
  function seatOf(path) {
    var m = SEAT_PATH_RE.exec(String(path || ''));
    return m && C.seats.valid(m[1]) ? m[1] : null;
  }

  function load() {
    try {
      var raw = g.localStorage.getItem(KEY);
      var obj = raw ? JSON.parse(raw) : {};
      return obj && typeof obj === 'object' && !Array.isArray(obj) ? obj : {};
    } catch (e) {
      return {};
    }
  }

  function save(map) {
    try { g.localStorage.setItem(KEY, JSON.stringify(map)); } catch (e) { /* 記不住就下次再提示一次 */ }
  }

  /** 未讀的判準（全站只有這一份）。
      entries：entries.recentParent 的 items；comments：blogComments.recentParent 的 items；
      seenMap：{ 座號: 毫秒 }（沒有紀錄＝0，也就是全部算新的）。
      回傳 { bySeat: { 座號: { posts, replies } }（只列有未讀的座號）, latest: { 座號: 最新一筆家長動態的毫秒 } }。
      · 家長新文：author == 'parent'、沒有被導師下架、createdAt 晚於看過的時間
      · 家長新留言：role == 'parent'、狀態是顯示中（家長自己收起的不算）、createdAt 晚於看過的時間
      · 伺服器時間還沒填上（剛送出的那一瞬間）→ 不算，下一次讀取就有了 */
  function compute(entries, comments, seenMap) {
    var seen = seenMap || {};
    var bySeat = {};
    var latest = {};
    function bump(seat, field, t) {
      if (t > (latest[seat] || 0)) latest[seat] = t;
      if (t <= (Number(seen[seat]) || 0)) return;
      var row = bySeat[seat] || (bySeat[seat] = { posts: 0, replies: 0 });
      row[field]++;
    }
    (entries || []).forEach(function (d) {
      var x = d && d.data;
      var seat = d && seatOf(d.path);
      if (!x || !seat || x.author !== 'parent' || x.visible === false) return;
      var t = millis(x.createdAt);
      if (t) bump(seat, 'posts', t);
    });
    (comments || []).forEach(function (d) {
      var x = d && d.data;
      var seat = d && seatOf(d.path);
      if (!x || !seat || x.role !== 'parent' || x.status !== 'visible') return;
      var t = millis(x.createdAt);
      if (t) bump(seat, 'replies', t);
    });
    return { bySeat: bySeat, latest: latest };
  }

  /** 導師打開某個座號＝看過了：記到 upTo（毫秒，只會往後推）。回傳是否有改變。 */
  function markSeat(seat, upTo) {
    if (!C.seats.valid(seat) || !(upTo > 0)) return false;
    var map = load();
    if ((Number(map[seat]) || 0) >= upTo) return false;
    map[seat] = upTo;
    save(map);
    return true;
  }

  /** 全班格算完後記住每個座號最新的家長動態（同一頁內打開座號時用） */
  function remember(latest) {
    Object.keys(latest || {}).forEach(function (s) {
      if (latest[s] > (latestMemo[s] || 0)) latestMemo[s] = latest[s];
    });
  }

  function remembered(seat) {
    return latestMemo[seat] || 0;
  }

  C.seen = {
    KEY: KEY,
    millis: millis,
    seatOf: seatOf,
    load: load,
    compute: compute,
    markSeat: markSeat,
    remember: remember,
    remembered: remembered,
    _reset: function () { latestMemo = {}; }
  };
})(typeof window !== 'undefined' ? window : globalThis);
