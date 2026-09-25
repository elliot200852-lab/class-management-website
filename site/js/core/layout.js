/* layout.js — 頁首、導覽、頁尾、導師浮鈕的唯一來源（docs/ARCHITECTURE.md §3.3）。

   NAV 是唯一一張導覽表；SITE_CONFIG.pages 的開關決定哪幾項出現。登入前頁首只有班名；
   Session 變成 ready 之後才依角色補上項目（導師會多一個「導師專用」分頁與右下角浮鈕）。
   頁尾只放班名與一句「內部網站、請勿轉傳」的提醒；導師稱呼登入後才從 config/site 讀。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var NAV = [
    { key: 'home', label: '首頁', page: 'home', flag: 'home', who: 'reader' },
    { key: 'blog', label: '班級紀事', page: 'blog', flag: 'class_posts', who: 'reader' },
    { key: 'gallery', label: '相簿', page: 'gallery', flag: 'gallery', who: 'reader' },
    { key: 'courses', label: '課程', page: 'courses', flag: 'courses', who: 'reader' },
    { key: 'my-child', label: '我的孩子', page: 'my-child', flag: 'my_child', who: 'seat' },
    { key: 'fun', label: '專題活動', page: 'page', params: { id: 'fun' }, flag: 'fun', who: 'reader' },
    { key: 'about', label: '關於我們', page: 'page', params: { id: 'about' }, flag: 'about', who: 'reader' },
    { key: 'poem', label: '每日一詩', page: 'poem', flag: 'poem', who: 'reader' },
    { key: 'teacher', label: '導師專用', page: 'teacher', flag: 'teacher_only', who: 'teacher' }
  ];

  // 導師右下角浮鈕（每一頁都掛，含單篇紀事與單本相簿）
  var FAB = [
    { label: '留言後台', page: 'admin' },
    { label: '我的孩子（全班）', page: 'my-child', sub: 'admin', flag: 'my_child' },
    { label: '導師專用', page: 'teacher', flag: 'teacher_only' },
    { label: '座位表', page: 'teacher', sub: 'seating', flag: 'teacher_only' },
    { label: '個人照', page: 'family-photos' },
    { label: '匯出 PDF', page: 'blog-print' }
  ];

  // 沒出現在導覽列的頁面，標題用這張表
  var PAGE_LABELS = {
    home: '首頁', blog: '班級紀事', category: '分類', post: '班級紀事', admin: '留言後台', page: '',
    gallery: '相簿', album: '相簿', 'private': '私密紀事', 'my-child': '我的孩子', teacher: '導師專用',
    courses: '課程', poem: '每日一詩', 'family-photos': '個人照', 'blog-print': '匯出 PDF',
    'my-child-print': '匯出 PDF'
  };

  function flagOn(flag) {
    var pages = C.config().pages;
    if (!pages || typeof pages !== 'object') return true;
    return pages[flag] !== false;
  }

  function visible(item, session) {
    if (!session || session.state !== 'ready') return false;
    if (item.flag && !flagOn(item.flag)) return false;
    var r = session.roles;
    if (item.who === 'teacher') return r.teacher;
    if (item.who === 'seat') return r.teacher || (r.seats && r.seats.length > 0);
    return true;
  }

  function isCurrent(item, route) {
    if (item.page !== route.page) return false;
    if (item.params && item.params.id) return route.params.get('id') === item.params.id;
    return true;
  }

  function className() {
    return C.config().className || '我的班級';
  }

  /** 頁首：班名＋（登入後）導覽 */
  function renderHeader(session, route) {
    var h = g.document.getElementById('site-header');
    if (!h) return;
    C.dom.clear(h);
    h.className = 'site-header';
    var mast = el('div', 'site-brand');
    var title = C.dom.link(C.route.href('home'), 'brand-title', className());
    title.appendChild(el('small', 'brand-tagline', 'our class notebook'));
    mast.appendChild(title);
    h.appendChild(mast);
    if (!session || session.state !== 'ready') return;
    var nav = el('nav', 'primary-nav');
    nav.setAttribute('aria-label', '主要導覽');
    var ul = el('ul');
    NAV.forEach(function (item) {
      if (!visible(item, session)) return;
      var li = el('li', 'nav-' + item.key);
      var a = C.dom.link(C.route.href(item.page, item.params), null, item.label);
      if (isCurrent(item, route)) {
        a.className = 'is-current';
        a.setAttribute('aria-current', 'page');
      }
      li.appendChild(a);
      ul.appendChild(li);
    });
    nav.appendChild(ul);
    h.appendChild(nav);
  }

  function renderFooter(session, siteInfo) {
    var f = g.document.getElementById('site-footer');
    if (!f) return;
    C.dom.clear(f);
    f.className = 'site-footer';
    var inner = el('div', 'footer-inner');
    inner.appendChild(el('p', 'footer-name', className()));
    inner.appendChild(el('p', 'footer-note', '班級內部網站・內容請勿轉傳'));
    if (siteInfo && siteInfo.teacherDisplayName) {
      inner.appendChild(el('p', 'footer-teacher', '導師：' + siteInfo.teacherDisplayName));
    }
    if (session && session.state === 'ready' && session.user) {
      var acct = el('p', 'footer-account');
      C.dom.add(acct, '目前登入：' + (session.user.email || ''));
      var store = C.getStore();
      if (!store.isDemo) {
        acct.appendChild(C.dom.button('btn-link', '登出', function () { store.signOut(); }));
      }
      inner.appendChild(acct);
    }
    var v = C.version();
    inner.appendChild(el('p', 'footer-version', (C.getStore().isDemo ? '示範版・' : '') + (v ? 'v' + v : '')));
    f.appendChild(inner);
  }

  var fabRoot = null;
  function renderFab(session) {
    if (fabRoot && fabRoot.parentNode) fabRoot.parentNode.removeChild(fabRoot);
    fabRoot = null;
    if (!session || session.state !== 'ready' || !session.roles.teacher) return;
    var d = g.document;
    var wrap = el('div', 'teacher-fab');
    var menu = el('ul', 'teacher-fab-menu');
    menu.id = 'teacher-fab-menu';
    menu.hidden = true;
    FAB.forEach(function (item) {
      if (item.flag && !flagOn(item.flag)) return;
      var li = el('li');
      li.appendChild(C.dom.link(C.route.href(item.page, null, item.sub), null, item.label));
      menu.appendChild(li);
    });
    var btn = C.dom.button('teacher-fab-btn', '導師', function () {
      var open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', 'teacher-fab-menu');
    btn.setAttribute('aria-label', '導師工具');
    wrap.appendChild(menu);
    wrap.appendChild(btn);
    d.body.appendChild(wrap);
    fabRoot = wrap;
  }

  function setTitle(label) {
    var n = className();
    g.document.title = label ? n + '｜' + label : n;
  }

  function pageLabel(route) {
    if (route.page === 'page') {
      var id = route.params.get('id');
      for (var i = 0; i < NAV.length; i++) {
        if (NAV[i].params && NAV[i].params.id === id) return NAV[i].label;
      }
      return '';
    }
    return PAGE_LABELS[route.page] || '';
  }

  /** 整組重畫（Session 或路由改變時） */
  function render(session, route, siteInfo) {
    renderHeader(session, route);
    renderFooter(session, siteInfo);
    renderFab(session);
    setTitle(session && session.state === 'ready' ? pageLabel(route) : '');
  }

  C.layout = {
    NAV: NAV,
    FAB: FAB,
    render: render,
    renderFooter: renderFooter,
    setTitle: setTitle,
    pageLabel: pageLabel,
    flagOn: flagOn
  };
})(typeof window !== 'undefined' ? window : globalThis);
