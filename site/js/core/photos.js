/* photos.js — 照片載入（docs/ARCHITECTURE.md §4.4）。

   照片存在資料庫裡，每張兩份：縮圖（thumb，格子與卡片用）與顯示圖（image，點開與正文用）。
   · 來源一律由 Store.photoSrc() 給（真站是 data:image/jpeg;base64,…，MIME 寫死；示範模式是程式畫的剪影）。
   · 卡片封面直接用摘要文件內嵌的 coverThumb，不另外讀；沒有內嵌時才讀一次縮圖。
   · 同一頁同一張只讀一次；顯示圖同時最多 4 張在讀；畫面外的照片等捲到附近才讀。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var B64_RE = /^[A-Za-z0-9+/]+={0,2}$/;
  var memo = {};
  var queue = [];
  var active = 0;
  var MAX_ACTIVE = 4;

  function isBase64(s, max) {
    return typeof s === 'string' && s.length > 0 && s.length <= max && B64_RE.test(s);
  }

  function pump() {
    while (active < MAX_ACTIVE && queue.length) {
      var job = queue.shift();
      active++;
      job();
    }
  }

  /** → Promise<字串或 null>。錯誤一律當 null（畫面顯示灰框）。 */
  function src(store, owner, pid, size) {
    var key = owner + '|' + pid + '|' + size;
    if (memo[key]) return memo[key];
    memo[key] = new Promise(function (resolve) {
      var run = function () {
        Promise.resolve()
          .then(function () { return store.photoSrc(owner, pid, size); })
          .then(function (u) { resolve(u || null); }, function () { resolve(null); })
          .then(function () { active--; pump(); });
      };
      if (size === 'image') { queue.push(run); pump(); } else { active++; run(); }
    });
    return memo[key];
  }

  var observer = null;
  function lazy(el, fn) {
    // 示範模式的剪影是當場畫的，不必等捲動（也讓整頁截圖看得到）
    var mode = C.detectMode();
    if (mode.demo || typeof g.IntersectionObserver !== 'function') { fn(); return; }
    if (!observer) {
      observer = new g.IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            observer.unobserve(en.target);
            var cb = en.target.cmwLoad;
            en.target.cmwLoad = null;
            if (cb) cb();
          }
        });
      }, { rootMargin: '300px 0px' });
    }
    el.cmwLoad = fn;
    observer.observe(el);
  }

  /** 把照片填進 <img>：捲到附近才讀；讀不到就呼叫 onFail（沒給就把 img 換成灰框）。 */
  function fill(img, store, owner, pid, size, onFail) {
    lazy(img, function () {
      src(store, owner, pid, size).then(function (u) {
        if (u) {
          img.src = u;
        } else if (onFail) {
          onFail();
        } else if (img.parentNode) {
          img.parentNode.replaceChild(missing(), img);
        }
      });
    });
  }

  /** 摘要文件（紀事、相簿、私密紀事）的封面 → Promise<字串或 null> */
  function cover(store, ownerPath, data) {
    var ct = data && data.coverThumb;
    if (ct && isBase64(ct.data, 32768)) {
      return Promise.resolve('data:image/jpeg;base64,' + ct.data);
    }
    if (data && typeof data.coverPid === 'string' && data.coverPid) {
      return src(store, ownerPath, data.coverPid, 'thumb');
    }
    return Promise.resolve(null);
  }

  function missing(text) {
    var box = g.document.createElement('div');
    box.className = 'photo-missing';
    box.textContent = text || '這張照片讀不到';
    return box;
  }

  /** 做一個封面框：有封面就放圖，沒有就放「沒有照片」的紙底。 */
  function coverBox(store, ownerPath, data, cls) {
    var d = g.document;
    var box = d.createElement('div');
    box.className = cls || 'entry-media';
    var img = d.createElement('img');
    img.alt = '';
    img.loading = 'lazy';
    box.appendChild(img);
    lazy(box, function () {
      cover(store, ownerPath, data).then(function (u) {
        if (u) {
          img.src = u;
        } else if (img.parentNode === box) {
          box.replaceChild(missing('沒有照片'), img);
          box.className += ' is-empty';
        }
      });
    });
    return box;
  }

  C.photos = {
    isBase64: isBase64,
    src: src,
    fill: fill,
    cover: cover,
    coverBox: coverBox,
    missing: missing,
    _reset: function () { memo = {}; queue = []; active = 0; }
  };
})(typeof window !== 'undefined' ? window : globalThis);
