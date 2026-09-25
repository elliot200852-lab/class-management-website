/* blocks.js — 正文結構化區塊的驗證與渲染（docs/ARCHITECTURE.md §4.1、§4.2）。

   正文不存 HTML，存一個區塊陣列：p、h、list、quote、img、video、hr。渲染規則：
     1. 只用 createElement、createTextNode、textContent、appendChild，以及固定幾個屬性
        （href、rel、target、alt、loading、class）。全站禁用任何會解析 HTML 字串的 API。
     2. 區塊型別不認得、欄位型別不對、超過上限 → 整個區塊跳過（不丟錯、不畫半個）。
     3. 連結只准 https:（CMW.text.safeUrl），一律 rel="noopener noreferrer"、另開分頁；
        javascript:、data:、http: 只剩文字。
     4. img 區塊：圖片來源由 Store.photoSrc 非同步填入；讀不到就畫灰框「這張照片讀不到」。
     5. video 區塊：YouTube 網址先畫「▶ 播放」鈕，點了才建 youtube-nocookie 的 iframe；
        其他 https 網址畫成連結卡。示範模式點了只顯示說明，不連任何外部網站。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var LIM = {
    blocks: 400,
    spans: 200,
    spanText: 5000,
    heading: 200,
    listItems: 100,
    caption: 300,
    url: 500,
    videoTitle: 80
  };

  var YT_HOSTS = ['www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'];
  var YT_ID = /^[A-Za-z0-9_-]{11}$/;
  var PID_RE = /^([0-9a-f]{16}|[0-2])$/;

  function isObj(v) { return !!v && typeof v === 'object' && !Array.isArray(v); }
  function isStr(v, max) { return typeof v === 'string' && v.length <= max; }

  function validSpan(s) {
    if (!isObj(s) || !isStr(s.text, LIM.spanText)) return false;
    if (s.b !== undefined && s.b !== true) return false;
    if (s.i !== undefined && s.i !== true) return false;
    if (s.href !== undefined && !isStr(s.href, LIM.url)) return false;
    return true;
  }

  function validSpans(arr) {
    if (!Array.isArray(arr) || arr.length > LIM.spans) return false;
    for (var i = 0; i < arr.length; i++) if (!validSpan(arr[i])) return false;
    return true;
  }

  /** 單一區塊合不合格式（§4.1）。 */
  function validBlock(b) {
    if (!isObj(b) || typeof b.t !== 'string') return false;
    switch (b.t) {
      case 'p':
      case 'quote':
        return validSpans(b.spans);
      case 'h':
        return (b.level === 2 || b.level === 3 || b.level === 4) && isStr(b.text, LIM.heading);
      case 'list':
        if (typeof b.ordered !== 'boolean' || !Array.isArray(b.items) || b.items.length > LIM.listItems) return false;
        for (var i = 0; i < b.items.length; i++) {
          if (!isObj(b.items[i]) || !validSpans(b.items[i].spans)) return false;
        }
        return true;
      case 'img':
        return typeof b.pid === 'string' && PID_RE.test(b.pid) &&
          (b.caption === undefined || isStr(b.caption, LIM.caption));
      case 'video':
        return isStr(b.url, LIM.url) && !!C.text.safeUrl(b.url) &&
          (b.title === undefined || isStr(b.title, LIM.videoTitle));
      case 'hr':
        return true;
      default:
        return false;
    }
  }

  /** YouTube 網址 → 11 碼影片 id；不是就回 null。 */
  function youtubeId(url) {
    var u = C.text.safeUrl(url);
    if (!u || YT_HOSTS.indexOf(u.hostname) < 0) return null;
    var id = null;
    if (u.hostname === 'youtu.be') {
      id = u.pathname.split('/')[1] || null;
    } else if (u.pathname === '/watch') {
      id = u.searchParams.get('v');
    } else {
      var m = /^\/(embed|shorts|live)\/([^/]+)/.exec(u.pathname);
      if (m) id = m[2];
    }
    return id && YT_ID.test(id) ? id : null;
  }

  function spans(d, parent, arr) {
    for (var i = 0; i < arr.length; i++) {
      var s = arr[i];
      var node;
      var lines = s.text.split('\n');
      var holder = d.createDocumentFragment();
      for (var k = 0; k < lines.length; k++) {
        if (k > 0) holder.appendChild(d.createElement('br'));
        if (lines[k]) holder.appendChild(d.createTextNode(lines[k]));
      }
      var u = s.href !== undefined ? C.text.safeUrl(s.href) : null;
      if (u) {
        node = d.createElement('a');
        node.href = u.href;
        node.rel = 'noopener noreferrer';
        node.target = '_blank';
        node.appendChild(holder);
      } else {
        node = holder;
      }
      if (s.i) { var em = d.createElement('em'); em.appendChild(node); node = em; }
      if (s.b) { var st = d.createElement('strong'); st.appendChild(node); node = st; }
      parent.appendChild(node);
    }
  }

  function missingPhoto(d) {
    var box = d.createElement('div');
    box.className = 'photo-missing';
    box.textContent = '這張照片讀不到';
    return box;
  }

  function renderImg(d, b, opts, gallery) {
    var fig = d.createElement('figure');
    fig.className = 'blk-figure';
    var holder = d.createElement('div');
    holder.className = 'blk-photo';
    var img = d.createElement('img');
    img.alt = b.caption !== undefined ? b.caption : '';
    img.loading = 'lazy';
    holder.appendChild(img);
    fig.appendChild(holder);
    if (b.caption) {
      var cap = d.createElement('figcaption');
      cap.textContent = b.caption;
      fig.appendChild(cap);
    }
    var index = gallery.length;
    gallery.push({ owner: opts.owner, pid: b.pid, caption: b.caption || '' });
    if (opts.store && opts.owner && C.photos) {
      C.photos.fill(img, opts.store, opts.owner, b.pid, 'image', function () {
        holder.replaceChild(missingPhoto(d), img);
      });
      if (C.lightbox) {
        img.className = 'zoomable';
        img.addEventListener('click', function () {
          C.lightbox.open(opts.store, gallery, index);
        });
      }
    } else if (!opts.store) {
      holder.replaceChild(missingPhoto(d), img);
    }
    return fig;
  }

  function renderVideo(d, b, opts) {
    var id = youtubeId(b.url);
    var wrap = d.createElement('div');
    wrap.className = 'blk-video';
    var title = b.title || '';
    if (id) {
      var btn = d.createElement('button');
      btn.type = 'button';
      btn.className = 'blk-video-play';
      btn.textContent = '▶ 播放' + (title ? '：' + title : '影片');
      btn.addEventListener('click', function () {
        if (opts.demo) {
          var note = d.createElement('p');
          note.className = 'blk-video-demo';
          note.textContent = '示範模式：實際網站會在這裡播放影片（示範站不連任何外部網站）。';
          wrap.replaceChild(note, btn);
          return;
        }
        var frame = d.createElement('iframe');
        frame.className = 'blk-video-frame';
        frame.src = 'https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1&rel=0';
        frame.title = title || '影片';
        frame.setAttribute('allow', 'autoplay; encrypted-media; picture-in-picture; fullscreen');
        frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
        frame.allowFullscreen = true;
        wrap.replaceChild(frame, btn);
      });
      wrap.appendChild(btn);
      return wrap;
    }
    wrap.className = 'blk-video blk-linkcard';
    var label = d.createElement('span');
    label.className = 'blk-linkcard-label';
    label.textContent = '影片連結';
    wrap.appendChild(label);
    wrap.appendChild(C.text.extLink(b.url, title || b.url));
    return wrap;
  }

  function renderBlock(d, b, opts, gallery) {
    var e;
    switch (b.t) {
      case 'p':
        e = d.createElement('p');
        spans(d, e, b.spans);
        return e;
      case 'quote':
        e = d.createElement('blockquote');
        var qp = d.createElement('p');
        spans(d, qp, b.spans);
        e.appendChild(qp);
        return e;
      case 'h':
        e = d.createElement('h' + b.level);
        e.textContent = b.text;
        return e;
      case 'list':
        e = d.createElement(b.ordered ? 'ol' : 'ul');
        for (var i = 0; i < b.items.length; i++) {
          var li = d.createElement('li');
          spans(d, li, b.items[i].spans);
          e.appendChild(li);
        }
        return e;
      case 'img':
        return renderImg(d, b, opts, gallery);
      case 'video':
        return renderVideo(d, b, opts);
      case 'hr':
        return d.createElement('hr');
    }
    return null;
  }

  /** blocks 陣列 → <div class="blocks">。opts：{ store, owner（照片主人文件路徑）, demo }。 */
  function render(blocks, opts) {
    opts = opts || {};
    var d = g.document;
    var root = d.createElement('div');
    root.className = 'blocks';
    if (!Array.isArray(blocks)) return root;
    var gallery = [];
    var n = Math.min(blocks.length, LIM.blocks);
    for (var i = 0; i < n; i++) {
      var b = blocks[i];
      if (!validBlock(b)) continue;
      var e = renderBlock(d, b, opts, gallery);
      if (e) root.appendChild(e);
    }
    return root;
  }

  C.blocks = { render: render, validBlock: validBlock, youtubeId: youtubeId, LIMITS: LIM };
})(typeof window !== 'undefined' ? window : globalThis);
