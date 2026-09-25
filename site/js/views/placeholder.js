/* views/placeholder.js — 還沒做好的頁面先顯示「建置中」（app.js 找不到某一頁的 view 時用它）。
   v1.1 的每日一詩、個人照、匯出 PDF 都已經有自己的 view；這一支留著當後備，導覽連到還沒做的頁面也不會壞。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  C.views.placeholder = function (ctx) {
    var label = C.layout.pageLabel(ctx.route) || '這一頁';
    var box = el('div', 'container container--narrow');
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Coming soon'));
    head.appendChild(el('h1', 'page-title', label));
    box.appendChild(head);
    var n = el('div', 'notice notice--building');
    n.appendChild(el('p', 'building-stamp', '建置中'));
    n.appendChild(el('p', null, '這一頁還在建置中，下一個版本就會完成。'));
    n.appendChild(C.dom.link(C.route.href('home'), 'section-link', '回首頁'));
    box.appendChild(n);
    ctx.main.appendChild(box);
    return null;
  };

})(typeof window !== 'undefined' ? window : globalThis);
