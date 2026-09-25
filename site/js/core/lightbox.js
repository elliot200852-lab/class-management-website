/* lightbox.js — 點開照片看大圖（燈箱）。

   只在點開時才讀顯示圖（image），左右切換、Esc 關閉、手機可左右滑。
   圖說一律 textContent。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var state = null;

  function close() {
    if (!state) return;
    var s = state;
    state = null;
    g.document.removeEventListener('keydown', s.onKey);
    if (s.root.parentNode) s.root.parentNode.removeChild(s.root);
    g.document.documentElement.classList.remove('has-lightbox');
    if (s.returnFocus && typeof s.returnFocus.focus === 'function') s.returnFocus.focus();
  }

  function show(i) {
    var s = state;
    if (!s) return;
    var n = s.items.length;
    s.index = (i + n) % n;
    var item = s.items[s.index];
    var d = g.document;
    C.dom.clear(s.stage);
    var wait = C.dom.el('p', 'lightbox-wait', '讀取中…');
    s.stage.appendChild(wait);
    s.caption.textContent = item.caption || '';
    s.counter.textContent = (s.index + 1) + ' / ' + n;
    var myIndex = s.index;
    C.photos.src(s.store, item.owner, item.pid, 'image').then(function (u) {
      if (!state || state.index !== myIndex) return;
      C.dom.clear(s.stage);
      if (!u) {
        s.stage.appendChild(C.photos.missing());
        return;
      }
      var img = d.createElement('img');
      img.alt = item.caption || '';
      img.src = u;
      s.stage.appendChild(img);
    });
  }

  /** items：[{ owner, pid, caption }]；index：從第幾張開始 */
  function open(store, items, index) {
    if (!items || !items.length) return;
    close();
    var d = g.document;
    var root = C.dom.el('div', 'lightbox');
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', '看大圖');
    var stage = C.dom.el('div', 'lightbox-stage');
    var caption = C.dom.el('p', 'lightbox-caption');
    var counter = C.dom.el('p', 'lightbox-counter');
    var btnClose = C.dom.button('lightbox-btn lightbox-close', '✕', close);
    btnClose.setAttribute('aria-label', '關閉');
    var btnPrev = C.dom.button('lightbox-btn lightbox-prev', '‹', function () { show(state.index - 1); });
    btnPrev.setAttribute('aria-label', '上一張');
    var btnNext = C.dom.button('lightbox-btn lightbox-next', '›', function () { show(state.index + 1); });
    btnNext.setAttribute('aria-label', '下一張');
    if (items.length < 2) { btnPrev.hidden = true; btnNext.hidden = true; }
    C.dom.add(root, btnClose, stage, btnPrev, btnNext, caption, counter);
    root.addEventListener('click', function (e) {
      if (e.target === root || e.target === stage) close();
    });
    var x0 = null;
    root.addEventListener('touchstart', function (e) {
      x0 = e.touches && e.touches[0] ? e.touches[0].clientX : null;
    }, { passive: true });
    root.addEventListener('touchend', function (e) {
      if (x0 === null || !e.changedTouches || !e.changedTouches[0]) return;
      var dx = e.changedTouches[0].clientX - x0;
      x0 = null;
      if (Math.abs(dx) > 50 && items.length > 1) show(state.index + (dx < 0 ? 1 : -1));
    });
    var onKey = function (e) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') show(state.index - 1);
      else if (e.key === 'ArrowRight') show(state.index + 1);
    };
    state = {
      store: store, items: items, index: 0, root: root, stage: stage, caption: caption,
      counter: counter, onKey: onKey, returnFocus: d.activeElement
    };
    d.addEventListener('keydown', onKey);
    d.body.appendChild(root);
    d.documentElement.classList.add('has-lightbox');
    show(index || 0);
    btnClose.focus();
  }

  C.lightbox = { open: open, close: close };
})(typeof window !== 'undefined' ? window : globalThis);
