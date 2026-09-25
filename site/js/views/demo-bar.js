/* demo-bar.js — 示範模式頂部固定橫幅：「示範模式・資料只存在你的瀏覽器」、切換示範身分、清除示範資料。

   切換身分只改「畫面長什麼樣」（導覽多幾項、導師工具出不出現、家長看到哪個座號），不模擬權限。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var ROLES = [
    { value: 'signed-out', label: '訪客（未登入）' },
    { value: 'parent', label: '家長' },
    { value: 'staff', label: '同仁（座號 03）' },
    { value: 'teacher', label: '導師' }
  ];

  function mount(store, mode) {
    var d = g.document;
    var bar = el('div', 'demo-bar' + (mode.reason === 'unconfigured' ? ' demo-bar--warn' : ''));
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', '示範模式');
    var msg = el('p', 'demo-bar-msg', mode.reason === 'unconfigured'
      ? '網站尚未設定完成・目前顯示的是示範資料'
      : '示範模式・資料只存在你的瀏覽器');
    bar.appendChild(msg);

    var controls = el('div', 'demo-bar-controls');
    var roleLabel = el('label', 'demo-bar-label', '身分');
    roleLabel.htmlFor = 'demo-role';
    var role = el('select', 'demo-select');
    role.id = 'demo-role';
    ROLES.forEach(function (r) {
      var o = el('option', null, r.label);
      o.value = r.value;
      role.appendChild(o);
    });
    var seatLabel = el('label', 'demo-bar-label', '座號');
    seatLabel.htmlFor = 'demo-seat';
    var seat = el('select', 'demo-select');
    seat.id = 'demo-seat';
    for (var i = 1; i <= C.demoData.STUDENTS; i++) {
      var s = C.seats.key(i);
      var o = el('option', null, s + '（' + C.demoData.parentLabel(s) + '）');
      o.value = s;
      seat.appendChild(o);
    }
    var reset = C.dom.button('btn btn--small demo-reset', '清除示範資料', null);
    var armed = null;
    reset.addEventListener('click', function () {
      if (!armed) {
        reset.textContent = '再按一次確認清除';
        armed = g.setTimeout(function () { armed = null; reset.textContent = '清除示範資料'; }, 3000);
        return;
      }
      g.clearTimeout(armed);
      armed = null;
      reset.textContent = '清除示範資料';
      store.demoReset();
    });

    function sync() {
      var r = store.demoRole ? store.demoRole() : { role: 'parent', seat: '01' };
      var shown = r.role === 'teacher' || r.role === 'signed-out' || r.role === 'staff' ? r.role : 'parent';
      role.value = shown;
      seat.value = C.seats.valid(r.seat) ? r.seat : '01';
      var isParent = shown === 'parent';
      seatLabel.hidden = !isParent;
      seat.hidden = !isParent;
    }

    role.addEventListener('change', function () {
      if (role.value === 'parent') store.demoSetRole('parent', { seat: seat.value || '01' });
      else store.demoSetRole(role.value);
    });
    seat.addEventListener('change', function () {
      store.demoSetRole('parent', { seat: seat.value });
    });
    store.onSession(function () { sync(); });

    C.dom.add(controls, roleLabel, role, seatLabel, seat, reset);
    bar.appendChild(controls);
    d.body.insertBefore(bar, d.body.firstChild);
    d.documentElement.classList.add('is-demo');
    sync();
  }

  C.demoBar = { mount: mount };
})(typeof window !== 'undefined' ? window : globalThis);
