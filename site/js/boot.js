/* boot.js — 每一頁唯一的程式入口：依 <body data-page> 依序載入共用程式與這一頁的畫面程式。

   載入清單只寫在下面 FILES 這一段（scripts/build_site.py 做「單一 HTML 示範版」時也讀這一段，
   所以兩邊不會分岔）。先載 ns.js 判斷是真站還是示範模式，再決定載 store-firestore.js 還是示範那幾支：
   示範模式完全不碰 Firebase SDK。每支檔的網址帶 ?v=版本，更新網站後不會新舊檔混用。 */
(function (g) {
  'use strict';

  var FILES = /* files:begin */ {
    "first": ["js/core/ns.js"],
    "core": [
      "js/core/queries.js",
      "js/core/errors.js",
      "js/core/util.js",
      "js/core/emailkey.js",
      "js/core/paths.js",
      "js/core/validate.js",
      "js/core/text.js",
      "js/core/blocks.js",
      "js/core/read-stats.js",
      "js/core/seen.js",
      "js/core/route.js",
      "js/core/photos.js",
      "js/core/lightbox.js",
      "js/core/query-eval.js",
      "js/core/store.js",
      "js/core/cards.js",
      "js/core/comments.js",
      "js/core/session.js",
      "js/core/layout.js",
      "js/core/app.js"
    ],
    "live": ["js/core/store-firestore.js"],
    "demo": [
      "js/core/demo-art.js",
      "js/core/demo-data.js",
      "js/core/store-demo.js",
      "js/views/demo-bar.js"
    ],
    "views": {
      "home": ["js/views/home.js"],
      "blog": ["js/views/blog.js"],
      "category": ["js/views/blog.js"],
      "post": ["js/views/post.js"],
      "admin": ["js/views/admin.js"],
      "page": ["js/views/page.js"],
      "gallery": ["js/views/gallery.js"],
      "album": ["js/views/gallery.js"],
      "private": ["js/views/private.js"],
      "my-child": [
        "js/core/photo-encode.js",
        "js/core/blog-compose.js",
        "js/views/my-child.js",
        "js/views/my-child-admin.js"
      ],
      "courses": ["js/views/courses.js"],
      "teacher": ["js/views/seating.js", "js/views/teacher.js"],
      "family-photos": ["js/views/family-photos.js"],
      "blog-print": ["js/views/print.js"],
      "my-child-print": ["js/views/print.js"],
      "poem": ["js/views/poem.js"]
    },
    "always": ["js/views/placeholder.js"]
  } /* files:end */;

  var d = g.document;
  var cfg = g.SITE_CONFIG || {};
  var ver = encodeURIComponent(String(cfg.version || '0'));

  function load(list, done) {
    var left = list.length;
    if (!left) { done(); return; }
    list.forEach(function (src) {
      var s = d.createElement('script');
      s.src = src + '?v=' + ver;
      s.async = false; // 依加入順序執行
      s.onload = function () { left--; if (!left) done(); };
      s.onerror = function () {
        var main = d.getElementById('app');
        if (main) {
          var p = d.createElement('p');
          p.className = 'notice notice--error';
          p.textContent = '網站的程式沒有載入完整（' + src + '），請重新整理一次；還是不行的話，可能是網路不穩。';
          main.appendChild(p);
        }
      };
      d.body.appendChild(s);
    });
  }

  load(FILES.first, function () {
    var C = g.CMW;
    var mode = C.detectMode();
    var page = (d.body && d.body.getAttribute('data-page')) || 'home';
    var list = FILES.core.slice();
    list = list.concat(mode.demo ? FILES.demo : FILES.live);
    var views = FILES.views[page] || [];
    views.forEach(function (v) { if (list.indexOf(v) < 0) list.push(v); });
    list = list.concat(FILES.always);
    load(list, function () { C.app.start(); });
  });
})(typeof window !== 'undefined' ? window : globalThis);
