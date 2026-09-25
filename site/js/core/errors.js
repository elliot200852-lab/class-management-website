/* errors.js — StoreError 與「錯誤碼 → 給人看的話」（docs/ARCHITECTURE.md §2.6）。

   頁面只認這幾個碼：unauthenticated、denied、index、quota、unavailable、invalid、cancelled。
   兩種 Store 都把自己的錯誤轉成 StoreError，頁面不直接看 Firebase 的錯誤碼。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var CODES = ['unauthenticated', 'denied', 'index', 'quota', 'unavailable', 'invalid', 'cancelled'];

  function StoreError(code, message, cause) {
    if (CODES.indexOf(code) < 0) code = 'unavailable';
    this.name = 'StoreError';
    this.code = code;
    this.message = message || code;
    this.cause = cause;
    // source：'auth' 代表是登入流程出的錯（額度訊息不一樣）
    this.source = (cause && cause.cmwSource) || '';
  }
  StoreError.prototype = Object.create(Error.prototype);
  StoreError.prototype.constructor = StoreError;

  var FIREBASE_MAP = {
    'permission-denied': 'denied',
    'unauthenticated': 'unauthenticated',
    'failed-precondition': 'index',
    'resource-exhausted': 'quota',
    'unavailable': 'unavailable',
    'deadline-exceeded': 'unavailable',
    'cancelled': 'unavailable',
    'invalid-argument': 'invalid',
    'not-found': 'invalid',
    'auth/quota-exceeded': 'quota',
    'auth/too-many-requests': 'quota',
    'auth/network-request-failed': 'unavailable',
    'auth/internal-error': 'unavailable',
    'auth/popup-closed-by-user': 'cancelled',
    'auth/cancelled-popup-request': 'cancelled',
    'auth/user-cancelled': 'cancelled',
    'auth/invalid-email': 'invalid',
    'auth/invalid-action-code': 'invalid',
    'auth/expired-action-code': 'invalid'
  };

  /** 任何錯誤 → StoreError。已經是 StoreError 就原樣回傳。 */
  function from(err) {
    if (err instanceof StoreError) return err;
    var raw = err && err.code ? String(err.code) : '';
    var code = FIREBASE_MAP[raw] || 'unavailable';
    var e = new StoreError(code, raw || (err && err.message) || 'error', err);
    if (raw.indexOf('auth/') === 0) e.source = 'auth';
    return e;
  }

  /** 錯誤碼 → 一句白話。where：'single'（單篇）｜'list'（列表）｜'auth'（登入）｜'form'（表單）。
      回傳空字串代表「不用顯示」。 */
  function message(err, where) {
    var e = from(err);
    switch (e.code) {
      case 'unauthenticated':
        return '要先登入才看得到。';
      case 'denied':
        if (where === 'single') return '這篇找不到（可能已下架）。';
        if (where === 'list') return '目前登入的帳號沒有權限看這裡。可以先登出，再換一個帳號。';
        return '';
      case 'index':
        return '網站剛更新，資料庫還在準備，請幾分鐘後再試。';
      case 'quota':
        if (e.source === 'auth' || where === 'auth') {
          return '今天的登入信額度用完了，請改用 Google 帳號登入，或明天再試。';
        }
        return '今天的免費額度用完了，台灣時間下午 4 點左右恢復。老師可以升級方案，不用改任何設定。';
      case 'unavailable':
        return '可能是網路不穩，請稍後再試。';
      case 'invalid':
        return where === 'form' && e.message && e.message !== 'invalid' ? e.message : '資料格式不對。';
      case 'cancelled':
        return '';
      default:
        return '發生了問題，請稍後再試。';
    }
  }

  /** 畫一個錯誤框（只用 DOM API）。opts.retry：重試函式；opts.where：同 message()。 */
  function box(err, opts) {
    opts = opts || {};
    var d = g.document;
    var wrap = d.createElement('div');
    wrap.className = 'notice notice--error';
    wrap.setAttribute('role', 'alert');
    var p = d.createElement('p');
    p.textContent = message(err, opts.where) || '發生了問題，請稍後再試。';
    wrap.appendChild(p);
    var code = from(err).code;
    if (opts.retry && (code === 'index' || code === 'unavailable' || code === 'quota')) {
      var b = d.createElement('button');
      b.type = 'button';
      b.className = 'btn btn--small';
      b.textContent = '重試';
      b.addEventListener('click', function () { opts.retry(); });
      wrap.appendChild(b);
    }
    if (opts.extra) wrap.appendChild(opts.extra);
    return wrap;
  }

  C.StoreError = StoreError;
  C.errors = { CODES: CODES.slice(), from: from, message: message, box: box };
})(typeof window !== 'undefined' ? window : globalThis);
