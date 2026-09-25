/* route.js — 頁面與網址的對照（一般網站＝一頁一個 HTML；單一 HTML 示範版＝#/ 路由）。

   頁面程式一律用 CMW.route.href(頁, 參數) 產生站內連結、用 CMW.route.current() 讀參數，
   這樣同一套 views 在「多檔網站」與「單一 HTML 示範版」都能跑，不必各寫一份。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var FILES = {
    home: 'index.html',
    blog: 'blog.html',
    category: 'category.html',
    post: 'post.html',
    admin: 'admin.html',
    page: 'page.html',
    gallery: 'gallery.html',
    album: 'album.html',
    'private': 'private.html',
    'my-child': 'my-child.html',
    teacher: 'teacher.html',
    courses: 'courses.html',
    poem: 'poem.html',
    'family-photos': 'family-photos.html',
    'blog-print': 'blog-print.html',
    'my-child-print': 'my-child-print.html'
  };

  function hashMode() {
    return C.config().singleFile === true;
  }

  function demoParam() {
    try {
      return /[?&]demo=1(&|$)/.test(String(g.location.search || '')) && C.config().demo !== true;
    } catch (e) {
      return false;
    }
  }

  function qs(params) {
    var sp = new URLSearchParams();
    Object.keys(params || {}).forEach(function (k) {
      var v = params[k];
      if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
    });
    var s = sp.toString();
    return s ? '?' + s : '';
  }

  /** 站內連結。page：FILES 的鍵；params：查詢參數；sub：my-child.html#/admin 這種子路由 */
  function href(page, params, sub) {
    if (!Object.prototype.hasOwnProperty.call(FILES, page)) page = 'home';
    if (hashMode()) {
      return '#/' + page + (sub ? '/' + sub : '') + qs(params);
    }
    var p = {};
    Object.keys(params || {}).forEach(function (k) { p[k] = params[k]; });
    if (demoParam()) p.demo = '1';
    return FILES[page] + qs(p) + (sub ? '#/' + sub : '');
  }

  /** 目前這一頁：{ page, params: URLSearchParams, sub } */
  function current() {
    if (hashMode()) {
      var h = String(g.location.hash || '').replace(/^#\/?/, '');
      var qi = h.indexOf('?');
      var pathPart = qi >= 0 ? h.slice(0, qi) : h;
      var query = qi >= 0 ? h.slice(qi + 1) : '';
      var segs = pathPart.split('/');
      var page = segs[0] || 'home';
      if (!Object.prototype.hasOwnProperty.call(FILES, page)) page = 'home';
      return { page: page, params: new URLSearchParams(query), sub: segs.slice(1).join('/') };
    }
    var body = g.document && g.document.body;
    var pg = (body && body.getAttribute('data-page')) || 'home';
    if (!Object.prototype.hasOwnProperty.call(FILES, pg)) pg = 'home';
    var sub = String(g.location.hash || '').replace(/^#\/?/, '');
    return { page: pg, params: new URLSearchParams(g.location.search || ''), sub: sub };
  }

  /** 分享用的完整網址（真站用正式網址；示範或本機用目前網址） */
  function absolute(page, params) {
    var cfg = C.config();
    if (!hashMode() && cfg.siteUrl && !C.detectMode().demo) {
      return String(cfg.siteUrl).replace(/\/+$/, '') + '/' + href(page, params);
    }
    try { return new URL(href(page, params), g.location.href).href; } catch (e) { return href(page, params); }
  }

  C.route = { FILES: FILES, href: href, current: current, hashMode: hashMode, absolute: absolute };
})(typeof window !== 'undefined' ? window : globalThis);
