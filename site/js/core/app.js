/* app.js — 啟動：網址正規化 → 頁首頁尾 → 登入閘 → 該頁 view（docs/ARCHITECTURE.md §3.4）。

   每一頁（或單一 HTML 示範版的每一次換頁）都照這個順序：
     1. 真站的主機名稱不是正式網址（例如開了 .web.app）→ 轉到正式網址（登入網域要同一個）
     2. 依 Session 畫頁首、頁尾、導師浮鈕
     3. 未登入 → 登入閘；不在名單 → 「這個帳號還沒有開通」；ready → 這一頁的 view
   畫完（含卡片上的附加資訊）會在 <html> 標上 data-cmw-ready="1"，驗收工具靠它判斷可以截圖了。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var cleanups = [];
  var renderSeq = 0;
  var siteInfoPromise = null;
  var siteInfoFor = null;
  var needEmail = false;

  function markReady(v) {
    g.document.documentElement.setAttribute('data-cmw-ready', v ? '1' : '0');
  }

  function runCleanups() {
    var list = cleanups;
    cleanups = [];
    list.forEach(function (fn) { try { fn(); } catch (e) { /* 忽略 */ } });
  }

  function normalizeHost(mode) {
    var cfg = C.config();
    if (mode.demo || !cfg.siteUrl) return false;
    var host = String(g.location.hostname || '');
    if (host === 'localhost' || host === '127.0.0.1' || !host) return false;
    var u;
    try { u = new URL(cfg.siteUrl); } catch (e) { return false; }
    if (host === u.hostname) return false;
    g.location.replace(u.origin + g.location.pathname + g.location.search + g.location.hash);
    return true;
  }

  /** config/site（導師稱呼、行事曆網址）：同一個登入身分只讀一次 */
  function siteInfo(store, session) {
    var who = session && session.user ? session.user.uid : '';
    if (!siteInfoPromise || siteInfoFor !== who) {
      siteInfoFor = who;
      siteInfoPromise = store.get(C.paths.configSite()).then(function (d) { return d ? d.data : {}; }, function () { return {}; });
    }
    return siteInfoPromise;
  }

  function render(store, session) {
    var seq = ++renderSeq;
    runCleanups();
    markReady(false);
    var d = g.document;
    var route = C.route.current();
    C.layout.render(session, route, null);
    var main = d.getElementById('app');
    C.dom.clear(main);
    main.className = 'app-main page-' + route.page;
    if (C.lightbox) C.lightbox.close();

    if (!session || session.state === 'loading') {
      C.session.loading(main);
      return;
    }
    if (session.state === 'signed-out') {
      C.session.gate(main, store, { needEmail: needEmail, error: session.error });
      markReady(true);
      return;
    }
    if (session.state === 'denied') {
      C.session.denied(main, store, session);
      markReady(true);
      return;
    }

    var info = siteInfo(store, session);
    info.then(function (x) { if (seq === renderSeq) C.layout.renderFooter(session, x); });

    var pending = [];
    var sharedMemo = {};
    var ctx = {
      store: store,
      session: session,
      route: route,
      params: route.params,
      main: main,
      siteInfo: function () { return info; },
      onCleanup: function (fn) { cleanups.push(fn); },
      /** 附加的非同步工作（卡片的留言數之類）：全部結束才算畫完 */
      track: function (p) { pending.push(Promise.resolve(p).catch(function () {})); return p; },
      shared: function (key, fn) {
        if (!sharedMemo[key]) sharedMemo[key] = Promise.resolve().then(fn);
        return sharedMemo[key];
      },
      isCurrent: function () { return seq === renderSeq; },
      setTitle: function (label) { C.layout.setTitle(label); }
    };
    var view = C.views[route.page] || C.views.placeholder;
    var result;
    try {
      result = Promise.resolve(view(ctx));
    } catch (e) {
      result = Promise.reject(e);
    }
    result.catch(function (err) {
      if (seq !== renderSeq) return;
      C.dom.clear(main);
      main.appendChild(C.errors.box(err, { where: 'list', retry: function () { render(store, store.getSession()); } }));
    }).then(function () {
      // 等附加工作一起結束（最多等到沒有新的工作加進來）
      var waitAll = function () {
        var n = pending.length;
        return Promise.all(pending.slice()).then(function () {
          if (pending.length !== n) return waitAll();
          return null;
        });
      };
      return waitAll();
    }).then(function () {
      if (seq === renderSeq) markReady(true);
    });
  }

  function start() {
    var mode = C.detectMode();
    if (normalizeHost(mode)) return;
    var store;
    try {
      store = C.getStore();
    } catch (e) {
      var main = g.document.getElementById('app');
      if (main) main.appendChild(C.errors.box(e));
      return;
    }
    if (mode.demo && C.demoBar) C.demoBar.mount(store, mode);
    C.layout.render(C.loadingSession(), C.route.current(), null);
    if (!store.isDemo) {
      store.completeSignInLink().catch(function (err) {
        if (err && err.message === 'need-email') {
          needEmail = true;
          var s = store.getSession();
          if (s && s.state === 'signed-out') render(store, s);
        }
      });
    }
    var last = null;
    store.onSession(function (s) {
      last = s;
      if (s && s.state === 'ready') needEmail = false;
      render(store, s);
    });
    // 單一 HTML 示範版整站都用 #/ 換頁；一般網站的「我的孩子」也用 # 後面的子路由（my-child.html#/seat/03）
    g.addEventListener('hashchange', function () {
      render(store, last || store.getSession());
      g.scrollTo(0, 0);
    });
  }

  C.app = { start: start, render: render };
})(typeof window !== 'undefined' ? window : globalThis);
