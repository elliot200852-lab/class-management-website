/* session.js — 登入閘畫面（docs/ARCHITECTURE.md §3.4）。只負責畫面與呼叫 Store 的登入方法，
   不替任何資料放行：真正的門是安全規則。這裡**不做任何前端名單比對**（不放 email 雜湊清單）。

   · 未登入：主按鈕「用 Google 帳號登入」；次要連結「沒有 Google 帳號？寄登入連結到信箱」。
   · 在 LINE／Facebook／Instagram 這類 App 裡打開時不能用 Google 登入：畫面說明怎麼改用手機本身的瀏覽器；
     LINE 多給一顆按鈕，連到同一頁並加上 openExternalBrowser=1（LINE 認得這個參數，會離開 App、改用系統的瀏覽器打開）。
   · email 連結：Spark 方案全專案每天只能寄 5 封，額度用完照 errors.js 顯示白話說明。
   · 登入了但帳號還沒開通：顯示目前登入的信箱、請他把這個信箱告訴老師，並提供登出換帳號的按鈕。
   · 「這是共用電腦」勾選（CMW.sharedDevice，記在這個分頁）：勾了＝登入只保留到關掉分頁、資料不留在這台電腦（ARCHITECTURE §3.4）。
   · email 連結登入只能讀公開內容（留言、私密內容要 Google 登入，DATA-MODEL §1.1），寄信那一段先講清楚。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  function inAppBrowser() {
    var ua = '';
    try { ua = String(g.navigator.userAgent || ''); } catch (e) { ua = ''; }
    if (/\bLine\//i.test(ua)) return 'line';
    if (/FBAN|FBAV|FB_IAB/.test(ua)) return 'facebook';
    if (/Instagram/i.test(ua)) return 'instagram';
    return '';
  }

  function externalUrl() {
    try {
      var u = new URL(g.location.href);
      u.searchParams.set('openExternalBrowser', '1');
      return u.href;
    } catch (e) {
      return String(g.location.href);
    }
  }

  function card(title) {
    var box = el('section', 'gate');
    box.setAttribute('aria-labelledby', 'gate-title');
    var h = el('h1', 'gate-title', title);
    h.id = 'gate-title';
    box.appendChild(h);
    return box;
  }

  function note(parent, text, cls) {
    var p = el('p', cls || 'gate-note', text);
    parent.appendChild(p);
    return p;
  }

  /** 「這是共用電腦」勾選框：要在按登入之前勾（登入後才勾就來不及了） */
  function sharedToggle() {
    var wrap = el('label', 'gate-shared');
    var box = el('input', 'gate-shared-box');
    box.type = 'checkbox';
    box.id = 'gate-shared';
    box.checked = C.sharedDevice.get();
    box.addEventListener('change', function () { box.checked = C.sharedDevice.set(!!box.checked); });
    C.dom.add(wrap, box, ' 這是共用電腦（學校、圖書館等）：關掉分頁就登出，不在這台電腦留下資料');
    return wrap;
  }

  function emailForm(store, onDone, opts) {
    opts = opts || {};
    var form = el('form', 'gate-email');
    form.noValidate = true;
    var label = el('label', 'field-label', opts.label || '你的信箱');
    label.htmlFor = 'gate-email-input';
    var input = el('input', 'field');
    input.type = 'email';
    input.id = 'gate-email-input';
    input.autocomplete = 'email';
    input.required = true;
    input.placeholder = 'name@example.com';
    var submit = el('button', 'btn', opts.button || '寄登入連結給我');
    submit.type = 'submit';
    var msg = el('p', 'form-msg');
    msg.setAttribute('aria-live', 'polite');
    C.dom.add(form, label, input, submit, msg);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = String(input.value || '').trim();
      if (!C.emailKey.isValid(v)) {
        msg.textContent = '信箱格式不對，請再檢查一次。';
        return;
      }
      if (store.isDemo) {
        msg.textContent = '示範模式不寄信。請用上方的「示範身分」切換看看不同的畫面。';
        return;
      }
      submit.disabled = true;
      msg.textContent = '處理中…';
      onDone(v).then(function (text) {
        msg.textContent = text || '';
        submit.disabled = false;
      }, function (err) {
        submit.disabled = false;
        msg.textContent = C.errors.message(err, 'auth') || '沒有成功，請稍後再試。';
      });
    });
    return form;
  }

  /** 未登入的整頁登入閘 */
  function gate(main, store, opts) {
    opts = opts || {};
    var cfg = C.config();
    var box = card((cfg.className || '班級網站') + '・登入後瀏覽');
    note(box, '這裡是班級的內部網站，只有老師登記過信箱的家長與老師看得到。登入時請用當初登記的信箱。', 'gate-lead');

    if (opts.needEmail) {
      note(box, '這個登入連結是在另一台裝置上打開的。安全起見，請再填一次收信用的信箱。');
      box.appendChild(sharedToggle());
      box.appendChild(emailForm(store, function (v) {
        return store.completeSignInLink(v).then(function () { return '登入中…'; });
      }, { button: '確認並登入' }));
      main.appendChild(box);
      return;
    }

    var app = inAppBrowser();
    if (app && !store.isDemo) {
      note(box, 'LINE、Facebook 這類 App 裡內建的瀏覽器沒辦法用 Google 登入。請把這一頁改用手機本身的瀏覽器（例如 Safari、Chrome）打開。');
      if (app === 'line') {
        var a = C.dom.link(externalUrl(), 'btn btn--primary', '改用瀏覽器打開這一頁');
        box.appendChild(a);
      } else {
        note(box, '做法：按右上角的「⋯」（或分享圖示），找「在瀏覽器中開啟」這一類的選項。');
      }
      main.appendChild(box);
      return;
    }

    var google = C.dom.button('btn btn--primary btn--google', '用 Google 帳號登入', null);
    var gmsg = el('p', 'form-msg');
    gmsg.setAttribute('aria-live', 'polite');
    box.appendChild(sharedToggle());
    box.appendChild(google);
    box.appendChild(gmsg);

    if (store.isDemo) {
      var chooser = el('div', 'gate-demo-roles');
      chooser.hidden = true;
      note(chooser, '示範模式：選一個身分進站看看。');
      chooser.appendChild(C.dom.button('btn', '學生 A 家長', function () { store.demoSetRole('parent', { seat: '01' }); }));
      chooser.appendChild(C.dom.button('btn', '示範導師', function () { store.demoSetRole('teacher'); }));
      box.appendChild(chooser);
      google.addEventListener('click', function () { chooser.hidden = false; });
    } else {
      google.addEventListener('click', function () {
        gmsg.textContent = '';
        google.disabled = true;
        store.signInWithGoogle().then(function () { google.disabled = false; }, function (err) {
          google.disabled = false;
          gmsg.textContent = C.errors.message(err, 'auth');
        });
      });
    }

    var more = el('details', 'gate-more');
    var summary = el('summary', null, '沒有 Google 帳號？寄登入連結到信箱');
    more.appendChild(summary);
    note(more, '我們會寄一封信給你，點信裡的連結就登入了。一台裝置只需要登入一次。');
    note(more, '用信箱連結登入只能閱讀：留言、已讀回條、私密內容與「我的孩子」都要用 Google 帳號登入。');
    more.appendChild(emailForm(store, function (v) {
      return store.sendSignInLink(v).then(function () {
        return '登入連結已經寄出。請到信箱點信裡的連結（沒看到的話，找找垃圾郵件匣）。';
      });
    }));
    box.appendChild(more);
    if (opts.error) {
      var m = C.errors.message(opts.error, 'auth');
      if (m) note(box, m, 'form-msg');
    }
    main.appendChild(box);
  }

  /** 已經登入、但這個帳號沒有被加進名單 */
  function denied(main, store, session) {
    var box = card('這個帳號還沒有開通');
    var email = session && session.user ? session.user.email : '';
    var p = el('p', 'gate-lead');
    C.dom.add(p, '你現在登入的是 ');
    p.appendChild(el('strong', 'gate-email-shown', email || '（讀不到信箱）'));
    C.dom.add(p, '。');
    box.appendChild(p);
    note(box, '請把上面這個信箱告訴老師；老師登記好以後，重新整理這一頁就能看到內容。想用別的 Google 帳號的話，先登出再換一個登入。');
    box.appendChild(C.dom.button('btn btn--primary', '登出，換一個帳號', function () { store.signOut(); }));
    main.appendChild(box);
  }

  function loading(main) {
    var box = el('section', 'gate gate--loading');
    box.appendChild(C.dom.loading('確認登入中…'));
    main.appendChild(box);
  }

  C.session = { gate: gate, denied: denied, loading: loading, inAppBrowser: inAppBrowser };
})(typeof window !== 'undefined' ? window : globalThis);
