/* ns.js — 建立 window.CMW 命名空間，並判斷這一頁要用真站還是示範模式。

   前端每一支檔都用 IIFE 包起來、掛在 CMW 底下，用傳統 <script> 依序載入（不用 ES module），
   所以示範站可以把全部檔案串成一個 HTML（docs/ARCHITECTURE.md §1）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  C.views = C.views || {};

  /** 公開設定（scripts/build_config.py 或 build_site.py 產生的 SITE_CONFIG）；沒有就回空物件。 */
  C.config = function () {
    return g.SITE_CONFIG || {};
  };

  C.version = function () {
    return String(C.config().version || '');
  };

  /** 寫入資料裡代表「伺服器時間」的記號。真站換成 serverTimestamp()，示範模式換成 new Date()。 */
  C.SERVER_TIME = Object.freeze({ cmwServerTime: true });

  C.isServerTime = function (v) {
    return !!(v && typeof v === 'object' && v.cmwServerTime === true);
  };

  function looksUnset(v) {
    var s = String(v || '').trim();
    return !s || s.indexOf('請填入') >= 0 || /^your-/i.test(s);
  }

  /** 決定這一頁用哪一種 Store（ARCHITECTURE §2.1）。回傳 { demo, reason }：
      reason ＝ 'demo'（示範站）｜'param'（網址帶 ?demo=1）｜'unconfigured'（還沒填 Firebase 設定）｜
               'emulator'（本機模擬器）｜'live'（正式網站）。 */
  C.detectMode = function () {
    var cfg = C.config();
    if (cfg.demo === true) return { demo: true, reason: 'demo' };
    var search = '';
    try { search = g.location ? String(g.location.search || '') : ''; } catch (e) { search = ''; }
    if (/[?&]demo=1(&|$)/.test(search)) return { demo: true, reason: 'param' };
    var fb = cfg.firebase || {};
    if (looksUnset(fb.apiKey) || looksUnset(fb.projectId)) return { demo: true, reason: 'unconfigured' };
    return { demo: false, reason: cfg.emulator === true ? 'emulator' : 'live' };
  };
})(typeof window !== 'undefined' ? window : globalThis);
