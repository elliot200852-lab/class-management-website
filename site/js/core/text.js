/* text.js — 純文字（留言、部落格文章、摘要、圖說）的渲染（docs/ARCHITECTURE.md §4.3）。

   逐行拆開；https:// 開頭的網址變成連結（結尾的標點不算進網址），其餘一律文字節點。
   換行變成 <br>。不解析任何 HTML：使用者打進來的 <script> 就只是字。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var MAX_URL = 500;
  var URL_RE = /https:\/\/[^\s<>"'`，。、！？；：「」『』（）【】《》]+/g;
  var TRAIL_RE = /[.,;:!?)\]}'"。，、！？；：）」』】》]+$/;

  /** 字串 → URL 物件（只收 https:，長度 ≤ 500）；不合回 null。
      javascript:、data:、http:、相對網址一律 null。 */
  function safeUrl(s) {
    if (typeof s !== 'string' || !s || s.length > MAX_URL) return null;
    var u;
    try { u = new URL(s); } catch (e) { return null; }
    if (u.protocol !== 'https:') return null;
    if (u.username || u.password) return null;
    return u;
  }

  /** 外部連結 <a>（固定 rel＝noopener noreferrer、另開分頁）。網址不合格就回文字節點。 */
  function extLink(href, text) {
    var d = g.document;
    var u = safeUrl(href);
    var label = text === undefined || text === null ? String(href) : String(text);
    if (!u) return d.createTextNode(label);
    var a = d.createElement('a');
    a.href = u.href;
    a.rel = 'noopener noreferrer';
    a.target = '_blank';
    a.textContent = label;
    return a;
  }

  function appendLine(frag, line) {
    var d = g.document;
    var last = 0;
    URL_RE.lastIndex = 0;
    var m;
    while ((m = URL_RE.exec(line)) !== null) {
      var raw = m[0];
      var trail = TRAIL_RE.exec(raw);
      var url = trail ? raw.slice(0, raw.length - trail[0].length) : raw;
      if (m.index > last) frag.appendChild(d.createTextNode(line.slice(last, m.index)));
      if (url.length > 'https://'.length) {
        frag.appendChild(extLink(url, url));
      } else {
        frag.appendChild(d.createTextNode(url));
      }
      last = m.index + url.length;
      URL_RE.lastIndex = last;
    }
    if (last < line.length) frag.appendChild(d.createTextNode(line.slice(last)));
  }

  /** 純文字 → DocumentFragment（網址變連結、換行變 <br>）。 */
  function render(str) {
    var d = g.document;
    var frag = d.createDocumentFragment();
    var lines = String(str === undefined || str === null ? '' : str).split('\n');
    for (var i = 0; i < lines.length; i++) {
      if (i > 0) frag.appendChild(d.createElement('br'));
      appendLine(frag, lines[i]);
    }
    return frag;
  }

  /** 摘要：去掉多餘空白、超過 max 字截斷加「…」 */
  function excerpt(str, max) {
    var s = String(str || '').replace(/\s+/g, ' ').trim();
    var chars = Array.from(s);
    if (chars.length <= max) return s;
    return chars.slice(0, max).join('') + '…';
  }

  C.text = { safeUrl: safeUrl, extLink: extLink, render: render, excerpt: excerpt, MAX_URL: MAX_URL };
})(typeof window !== 'undefined' ? window : globalThis);
