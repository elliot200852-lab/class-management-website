/* util.js — 小工具：日期、座號（CMW.seats）、DOM 小幫手（CMW.dom）、隨機 id。

   座號只有一種寫法：兩位數字字串 "01"–"40"（docs/DATA-MODEL.md §0.4），
   跟 Python 的 scripts/lib/seats.py 同一套規則；前端一律經 CMW.seats，不自己補零。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  // ── 座號 ─────────────────────────────────────────────
  var SEAT_RE = /^(0[1-9]|[1-3][0-9]|40)$/;

  function seatKey(n) {
    if (typeof n === 'boolean') throw new Error('座號不能是布林值');
    var i = typeof n === 'number' ? n : (typeof n === 'string' && /^\s*\d+\s*$/.test(n) ? parseInt(n, 10) : NaN);
    if (typeof n !== 'number' && typeof n !== 'string') throw new Error('座號型別不對');
    if (!isFinite(i) || Math.floor(i) !== i) throw new Error('座號必須是整數');
    if (i < 1 || i > 40) throw new Error('座號超出範圍（1–40）');
    return (i < 10 ? '0' : '') + i;
  }

  function parseSeat(v) {
    if (typeof v === 'boolean') throw new Error('座號不能是布林值');
    if (typeof v === 'number') return seatKey(v);
    if (typeof v === 'string') {
      var s = v.trim();
      if (!/^\d{1,2}$/.test(s)) throw new Error('座號格式不對，只能是 1～2 位數字');
      return seatKey(parseInt(s, 10));
    }
    throw new Error('座號型別不對');
  }

  C.seats = {
    RE: SEAT_RE,
    key: seatKey,
    parse: parseSeat,
    valid: function (s) { return typeof s === 'string' && SEAT_RE.test(s); },
    /** 座號 → 示範／名冊用的字母（01 → A）。只在示範資料與顯示「學生 A」這類稱呼時用。 */
    letter: function (s) { return String.fromCharCode(64 + parseInt(s, 10)); }
  };

  // ── 日期 ─────────────────────────────────────────────
  var WEEK = ['日', '一', '二', '三', '四', '五', '六'];

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function ymd(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function parseYmd(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''));
    if (!m) return null;
    return new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10));
  }

  C.util = {
    ymd: ymd,
    parseYmd: parseYmd,
    today: function () { return ymd(new Date()); },
    addDays: function (s, n) {
      var d = parseYmd(s) || new Date();
      d.setDate(d.getDate() + n);
      return ymd(d);
    },
    /** '2026-09-23' → '2026 年 9 月 23 日（三）' */
    fmtDate: function (s) {
      var d = parseYmd(s);
      if (!d) return String(s || '');
      return d.getFullYear() + ' 年 ' + (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日（' + WEEK[d.getDay()] + '）';
    },
    /** '2026-09-23' → '2026.09.23'（卡片上的日期印章） */
    fmtStamp: function (s) {
      return String(s || '').replace(/-/g, '.');
    },
    /** Date → '9/23 14:05'；null（伺服器時間還沒填上）→ '剛剛' */
    fmtTime: function (d) {
      if (!(d instanceof Date) || isNaN(d.getTime())) return '剛剛';
      return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },
    /** 部落格文章 id：YYYY-MM-DD- ＋ 8 碼小寫英數。每次送出（含重試）都要重新叫一次。 */
    newPostId: function (date) {
      var day = typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : ymd(date instanceof Date ? date : new Date());
      return day + '-' + randomId(8, 'abcdefghijklmnopqrstuvwxyz0123456789');
    },
    randomId: function (n) {
      return randomId(n || 20, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789');
    },
    /** 字數（以 Unicode 字元算，不是 UTF-16 單位） */
    len: function (s) { return Array.from(String(s)).length; }
  };

  function randomId(n, alphabet) {
    var out = '';
    var cryptoObj = g.crypto;
    var buf = new Uint8Array(n);
    if (cryptoObj && typeof cryptoObj.getRandomValues === 'function') {
      cryptoObj.getRandomValues(buf);
    } else {
      throw new Error('這個瀏覽器不支援安全的亂數（crypto.getRandomValues）');
    }
    for (var i = 0; i < n; i++) out += alphabet.charAt(buf[i] % alphabet.length);
    return out;
  }

  // ── DOM 小幫手（只用 createElement／textContent，不碰任何會解析 HTML 字串的 API） ──
  function el(tag, cls, text) {
    var e = g.document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  C.dom = {
    el: el,
    /** 依序把子節點（字串會變成文字節點）接到 parent 底下，回傳 parent。 */
    add: function (parent) {
      for (var i = 1; i < arguments.length; i++) {
        var c = arguments[i];
        if (c === null || c === undefined || c === false) continue;
        parent.appendChild(typeof c === 'string' ? g.document.createTextNode(c) : c);
      }
      return parent;
    },
    clear: function (node) {
      while (node && node.firstChild) node.removeChild(node.firstChild);
      return node;
    },
    /** 站內連結（href 由 CMW.route.href 產生，不是資料） */
    link: function (href, cls, text) {
      var a = el('a', cls, text);
      a.href = href;
      return a;
    },
    button: function (cls, text, onClick) {
      var b = el('button', cls || 'btn', text);
      b.type = 'button';
      if (onClick) b.addEventListener('click', onClick);
      return b;
    },
    /** 可見的載入中提示 */
    loading: function (text) {
      var p = el('p', 'loading', text || '讀取中…');
      p.setAttribute('aria-live', 'polite');
      return p;
    }
  };
})(typeof window !== 'undefined' ? window : globalThis);
