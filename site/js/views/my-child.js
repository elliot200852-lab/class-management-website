/* views/my-child.js — 「我的孩子」：每位孩子一個部落格 my-child.html#/…（docs/ARCHITECTURE.md §3.1、docs/DATA-MODEL.md §2.13–§2.15）。

   子路由（網址 # 後面；單一 HTML 示範版是 #/my-child/…）：
     （空白）            家長／同仁：只有一個座號就直接進去；有兩個以上先選。導師：全班格
     admin               導師：全班格（views/my-child-admin.js）
     seat/<座號>          某個座號的文章列表
     entry/<座號>/<id>    單篇文章＋底下的對話串（導師與這位孩子的家長）
     new/<座號>           寫一篇（該座號的家長、導師）
   誰看得到什麼（畫面只是體驗，真正的門是安全規則）：
     · 座號家長：只看自己孩子的座號；發文最多 3 張照片（照片先在瀏覽器重新編碼、清掉 EXIF／GPS）；
       在對話串留言；把自己的留言收起（收起後不能復原）。家長發的文不能改也不能刪。
     · 同仁（逐座號閱讀）：只讀被授權座號的文章，**不進對話串**（連查都不查）。
     · 導師：任何座號；下架／重新上架文章；收起或還原任何一則對話；作者代號對回「學生 A 家長（母）」。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var ROLE_LABEL = { teacher: '導師', parent: '家長' };
  var flash = '';

  // ── 路由與身分 ───────────────────────────────────────
  function parseSub(sub) {
    var parts = String(sub || '').split('/').filter(function (s) { return s; });
    var kind = parts[0] || '';
    if (!kind) return { view: 'home' };
    if (kind === 'admin') return { view: 'admin' };
    if (kind === 'seat' && C.seats.valid(parts[1])) return { view: 'seat', seat: parts[1] };
    if (kind === 'new' && C.seats.valid(parts[1])) return { view: 'new', seat: parts[1] };
    if (kind === 'entry' && C.seats.valid(parts[1]) && C.paths.RE.postId.test(parts[2] || '')) {
      return { view: 'entry', seat: parts[1], postId: parts[2] };
    }
    return { view: 'bad' };
  }

  function href(sub) { return C.route.href('my-child', null, sub); }
  function go(sub) {
    var h = href(sub);
    var i = h.indexOf('#');
    g.location.hash = i >= 0 ? h.slice(i) : '#/' + sub;
  }

  function roles(ctx) { return ctx.session.roles; }
  function isTeacher(ctx) { return !!roles(ctx).teacher; }
  function mySeats(ctx) { return (roles(ctx).seats || []).filter(C.seats.valid); }
  function canSee(ctx, seat) { return isTeacher(ctx) || mySeats(ctx).indexOf(seat) >= 0; }
  function isParentOf(ctx, seat) {
    return !isTeacher(ctx) && roles(ctx).seatKind === 'parent' && mySeats(ctx).indexOf(seat) >= 0;
  }
  /** 看得到對話串：導師，或這個座號的家長（同仁不行） */
  function inThread(ctx, seat) { return isTeacher(ctx) || isParentOf(ctx, seat); }

  // ── 小元件 ───────────────────────────────────────────
  function container(narrow) { return el('div', 'container' + (narrow ? ' container--narrow' : '')); }

  function notice(ctx, text, linkHref, linkText) {
    var box = container(true);
    var n = el('div', 'notice');
    n.appendChild(el('p', null, text));
    if (linkHref) n.appendChild(C.dom.link(linkHref, 'section-link', linkText));
    box.appendChild(n);
    ctx.main.appendChild(box);
    return null;
  }

  function avatar(blog, size) {
    var box = el('span', 'mc-avatar' + (size ? ' mc-avatar--' + size : ''));
    var av = blog && blog.avatar;
    if (av && C.photos.isBase64(av.data, 32768)) {
      var img = el('img');
      img.alt = '';
      img.src = 'data:image/jpeg;base64,' + av.data;
      box.appendChild(img);
    } else {
      var name = String((blog && blog.displayName) || '').replace(/^學生\s*/, '');
      box.appendChild(el('span', 'mc-avatar-letter', Array.from(name)[0] || '？'));
    }
    return box;
  }

  function stamp(date) {
    var t = el('time', 'stamp-date', C.util.fmtStamp(date));
    t.dateTime = String(date || '');
    return t;
  }

  function authorChip(author) {
    return el('span', 'chip chip--author chip--author-' + (author === 'teacher' ? 'teacher' : 'parent'),
      author === 'teacher' ? '導師寫的' : '家長寫的');
  }

  /** 導師看的身分對照：作者代號 → 「學生 A 家長（母）」（代號 → 名單 → 座號與稱謂 → 名冊稱呼） */
  function identity(ctx) {
    return ctx.shared('mcIdentity', function () {
      return Promise.all([
        ctx.store.query('allowlist.all').then(function (p) { return p.items; }, function () { return []; }),
        C.cards.parentMapItems(ctx).catch(function () { return []; }),
        ctx.store.get(C.paths.rosterStudents()).then(function (d) { return d && d.data ? d.data.students || [] : []; },
          function () { return []; })
      ]).then(function (r) {
        var byAlias = {};
        r[0].forEach(function (a) { if (a.data && a.data.alias) byAlias[a.data.alias] = { key: a.id, kind: a.data.kind }; });
        var mapByKey = {};
        r[1].forEach(function (m) { mapByKey[m.id] = m.data || {}; });
        var nameBySeat = {};
        r[2].forEach(function (s) { if (s && s.seat) nameBySeat[s.seat] = s.displayName || s.name || ''; });
        return function (alias, seat) {
          var a = byAlias[alias];
          if (!a) return '（已不在名單）';
          if (a.kind === 'teacher') return '導師';
          if (a.kind === 'staff') return '同仁';
          var m = mapByKey[a.key];
          var seats = m && Array.isArray(m.seats) ? m.seats : [];
          var s = seats.indexOf(seat) >= 0 ? seat : seats[0];
          if (!s) return '家長（沒有對應座號）';
          var who = nameBySeat[s] || ('座號 ' + s);
          return who + ' 家長' + (m.relation ? '（' + m.relation + '）' : '');
        };
      });
    });
  }

  function blogDoc(ctx, seat) {
    return ctx.shared('blog:' + seat, function () {
      return ctx.store.get(C.paths.blog(seat)).then(function (d) { return d ? d.data : null; }, function (err) {
        var e = C.errors.from(err);
        if (e.code === 'denied') return null;
        throw e;
      });
    });
  }

  function flashBox(parent) {
    if (!flash) return;
    var p = el('p', 'notice notice--ok', flash);
    p.setAttribute('role', 'status');
    parent.appendChild(p);
    flash = '';
  }

  // ── 首頁（沒有子路由） ─────────────────────────────────
  function home(ctx) {
    if (isTeacher(ctx)) return C.myChild.admin(ctx);
    var seats = mySeats(ctx);
    if (!seats.length && C.readOnlyLogin(ctx.session)) {
      return notice(ctx, C.READ_ONLY_LOGIN_MSG + '「我的孩子」只給對應到孩子座號、用 Google 帳號登入的家長。',
        C.route.href('home'), '回首頁');
    }
    if (!seats.length) {
      return notice(ctx, '「我的孩子」只給對應到孩子座號的家長，而且要用 Google 帳號登入。' +
        '如果你是家長卻看到這一句，請把目前登入的信箱（頁尾看得到）傳給老師。', C.route.href('home'), '回首頁');
    }
    if (seats.length === 1) return seatView(ctx, seats[0]);
    var box = container(true);
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'Family blog'));
    head.appendChild(el('h1', 'page-title', '我的孩子'));
    head.appendChild(el('p', 'page-dek', '選一位孩子。'));
    box.appendChild(head);
    var grid = el('div', 'mc-grid');
    box.appendChild(grid);
    ctx.main.appendChild(box);
    return Promise.all(seats.map(function (s) {
      return blogDoc(ctx, s).catch(function () { return null; });
    })).then(function (docs) {
      seats.forEach(function (s, i) {
        var a = C.dom.link(href('seat/' + s), 'mc-card');
        a.appendChild(avatar(docs[i]));
        var label = el('span', 'mc-card-label');
        label.appendChild(el('span', 'mc-card-seat', '座號 ' + s));
        label.appendChild(el('span', 'mc-card-name', (docs[i] && docs[i].displayName) || '（部落格還沒開好）'));
        a.appendChild(label);
        grid.appendChild(a);
      });
    });
  }

  // ── 某個座號的文章列表 ─────────────────────────────────
  function seatHeader(ctx, seat, blog) {
    var head = el('header', 'page-header mc-head');
    var row = el('div', 'mc-head-row');
    row.appendChild(avatar(blog, 'large'));
    var titles = el('div', 'mc-head-titles');
    titles.appendChild(el('p', 'eyebrow', 'My child・座號 ' + seat));
    titles.appendChild(el('h1', 'page-title', ((blog && blog.displayName) || '座號 ' + seat) + ' 的部落格'));
    row.appendChild(titles);
    head.appendChild(row);
    if (blog && blog.intro) {
      var intro = el('p', 'page-dek mc-intro');
      intro.appendChild(C.text.render(blog.intro));
      head.appendChild(intro);
    }
    return head;
  }

  function seatNav(ctx, seat) {
    var seats = mySeats(ctx);
    if (isTeacher(ctx) || seats.length < 2) return null;
    var nav = el('nav', 'cat-chips');
    nav.setAttribute('aria-label', '選孩子');
    seats.forEach(function (s) {
      nav.appendChild(C.dom.link(href('seat/' + s), 'chip' + (s === seat ? ' is-current' : ''), '座號 ' + s));
    });
    return nav;
  }

  function entryCard(ctx, seat, doc, who) {
    var x = doc.data || {};
    var link = href('entry/' + seat + '/' + doc.id);
    var art = el('article', 'blog-entry' + (x.visible === false ? ' is-hidden' : ''));
    var photos = Array.isArray(x.photos) ? x.photos.filter(function (p) { return p && /^[0-2]$/.test(p.pid); }) : [];
    if (photos.length) {
      var media = C.dom.link(link, 'blog-entry-media');
      media.setAttribute('aria-hidden', 'true');
      media.tabIndex = -1;
      var img = el('img');
      img.alt = '';
      img.loading = 'lazy';
      media.appendChild(img);
      C.photos.fill(img, ctx.store, doc.path, photos[0].pid, 'thumb', function () {
        media.replaceChild(C.photos.missing('沒有照片'), img);
      });
      art.appendChild(media);
    }
    var body = el('div', 'blog-entry-text');
    var meta = el('div', 'entry-meta');
    meta.appendChild(stamp(x.date));
    meta.appendChild(authorChip(x.author));
    if (who && x.author === 'parent') meta.appendChild(el('span', 'mc-identity', who(x.authorAlias, seat)));
    if (x.visible === false) meta.appendChild(el('span', 'chip chip--hidden', '已下架（家長看不到）'));
    if (photos.length > 1) meta.appendChild(el('span', 'badge', photos.length + ' 張照片'));
    if (inThread(ctx, seat)) {
      var badge = el('span', 'badge badge--comments');
      badge.hidden = true;
      meta.appendChild(badge);
      ctx.track(ctx.store.count('blogComments.count', { entry: doc.path }).then(function (n) {
        if (n > 0) { badge.textContent = '對話 ' + n; badge.hidden = false; }
      }, function () { /* 附加資訊，讀不到就不顯示 */ }));
    }
    body.appendChild(meta);
    var h = el('h2', 'entry-title');
    h.appendChild(C.dom.link(link, null, x.title || '（沒有標題）'));
    body.appendChild(h);
    if (x.body) body.appendChild(el('p', 'entry-excerpt', C.text.excerpt(x.body, 110)));
    art.appendChild(body);
    return art;
  }

  function seatView(ctx, seat) {
    if (!canSee(ctx, seat)) {
      return notice(ctx, '這個座號不在你的帳號底下，所以看不到。', href(''), '回我的孩子');
    }
    var teacher = isTeacher(ctx);
    var box = container(true);
    ctx.main.appendChild(box);
    if (teacher) {
      var crumb = el('p', 'breadcrumb');
      crumb.appendChild(C.dom.link(href('admin'), null, '← 全班'));
      box.appendChild(crumb);
    }
    flashBox(box);
    var listName = teacher ? 'entries.bySeat.teacher' : 'entries.bySeat';
    return Promise.all([
      blogDoc(ctx, seat),
      ctx.store.query(listName, { seat: seat }),
      teacher ? identity(ctx) : Promise.resolve(null)
    ]).then(function (r) {
      var blog = r[0];
      var page = r[1];
      var who = r[2];
      box.appendChild(seatHeader(ctx, seat, blog));
      var nav = seatNav(ctx, seat);
      if (nav) box.appendChild(nav);
      if (!blog && !teacher) {
        box.appendChild(el('p', 'notice', '孩子的部落格還在準備中，老師開好之後這裡就看得到。'));
        return;
      }
      var actions = el('div', 'mc-actions');
      if (isParentOf(ctx, seat)) {
        actions.appendChild(C.dom.link(href('new/' + seat), 'btn btn--primary', '寫一篇'));
      } else if (teacher) {
        actions.appendChild(C.dom.link(href('new/' + seat), 'btn', '以導師身分寫一篇'));
      }
      if (!inThread(ctx, seat)) {
        actions.appendChild(el('p', 'mc-note', '你是以同仁身分閱讀：看得到文章，看不到老師與家長之間的對話。'));
      }
      box.appendChild(actions);
      var list = el('div', 'blog-entry-list');
      box.appendChild(list);
      if (!page.items.length) {
        list.appendChild(el('p', 'empty', isParentOf(ctx, seat)
          ? '還沒有文章。按「寫一篇」分享孩子在家的點滴，老師會在文章底下回覆你。'
          : '還沒有文章。'));
      }
      var newest = 0;
      page.items.forEach(function (doc) {
        list.appendChild(entryCard(ctx, seat, doc, who));
        if (doc.data && doc.data.author === 'parent') newest = Math.max(newest, C.seen.millis(doc.data.createdAt));
      });
      if (teacher) C.seen.markSeat(seat, Math.max(newest, C.seen.remembered(seat)));
    }, function (err) {
      box.appendChild(C.errors.box(err, { where: 'list' }));
    });
  }

  // ── 單篇文章＋對話串 ───────────────────────────────────
  function photoGallery(ctx, entryPath, photos) {
    var items = photos.map(function (p) { return { owner: entryPath, pid: p.pid, caption: p.caption || '' }; });
    var wrap = el('div', 'blog-photos blog-photos--n' + items.length);
    items.forEach(function (it, i) {
      var fig = el('figure', 'blog-photo');
      var b = el('button', 'blog-photo-btn');
      b.type = 'button';
      b.setAttribute('aria-label', '看大圖' + (it.caption ? '：' + it.caption : ''));
      var img = el('img');
      img.alt = it.caption;
      img.loading = 'lazy';
      b.appendChild(img);
      C.photos.fill(img, ctx.store, entryPath, it.pid, 'image', function () {
        b.replaceChild(C.photos.missing(), img);
      });
      b.addEventListener('click', function () { C.lightbox.open(ctx.store, items, i); });
      fig.appendChild(b);
      if (it.caption) fig.appendChild(el('figcaption', null, it.caption));
      wrap.appendChild(fig);
    });
    return wrap;
  }

  function visibilityToggle(ctx, entryPath, x, meta) {
    var hidden = x.visible === false;
    var chip = el('span', 'chip chip--hidden', '已下架（家長看不到）');
    chip.hidden = !hidden;
    meta.appendChild(chip);
    var msg = el('span', 'form-msg');
    var btn = C.dom.button('btn btn--small', hidden ? '重新上架' : '下架這一篇', function () {
      btn.disabled = true;
      var next = hidden;
      ctx.store.update(entryPath, { visible: next, updatedAt: C.SERVER_TIME }).then(function () {
        hidden = !next;
        chip.hidden = !hidden;
        btn.textContent = hidden ? '重新上架' : '下架這一篇';
        msg.textContent = hidden ? '已下架：家長與同仁看不到這一篇了（可以隨時重新上架）。' : '已重新上架。';
        btn.disabled = false;
      }, function (err) {
        btn.disabled = false;
        msg.textContent = C.errors.message(err, 'form') || '沒有成功，請稍後再試。';
      });
    });
    var row = el('div', 'mc-teacher-tools');
    C.dom.add(row, btn, msg);
    return row;
  }

  function thread(ctx, seat, entryPath) {
    var teacher = isTeacher(ctx);
    var myAlias = roles(ctx).alias;
    var sec = el('section', 'comments blog-thread');
    var h = el('h2', 'comments-title', teacher ? '和家長的對話' : '和老師的對話');
    sec.appendChild(h);
    sec.appendChild(el('p', 'mc-note', teacher
      ? '這裡只有你和這位孩子的家長會看到。'
      : '只有你和老師看得到這裡（同仁與其他家長都看不到）。'));
    var listBox = el('div', 'comment-list');
    sec.appendChild(listBox);
    var who = teacher ? identity(ctx) : Promise.resolve(null);

    function renderItem(d, whoFn) {
      var x = d.data || {};
      var mine = !!myAlias && x.authorAlias === myAlias;
      var item = el('article', 'comment bc-item bc-item--' + (x.role === 'teacher' ? 'teacher' : 'parent') +
        (x.status === 'hidden' ? ' is-hidden' : '') + (mine ? ' is-mine' : ''));
      var head = el('header', 'comment-head');
      head.appendChild(el('strong', 'comment-name', ROLE_LABEL[x.role] || '？'));
      if (whoFn && x.role === 'parent') head.appendChild(el('span', 'mc-identity', whoFn(x.authorAlias, seat)));
      if (mine) head.appendChild(el('span', 'comment-mine', '我'));
      head.appendChild(el('time', 'comment-time', C.util.fmtTime(x.createdAt)));
      item.appendChild(head);
      var body = el('p', 'comment-body');
      body.appendChild(C.text.render(x.body || ''));
      item.appendChild(body);
      if (x.status === 'hidden') {
        item.appendChild(el('p', 'comment-hidden-note', teacher ? '已收起：家長看不到這一則。' : '已收起。'));
      }
      var actions = el('div', 'comment-actions');
      var cpath = C.paths.blogComment(entryPath, d.id);
      if (teacher) {
        var hidden = x.status === 'hidden';
        var toggle = C.dom.button('btn-link', hidden ? '還原顯示' : '收起', function () {
          toggle.disabled = true;
          ctx.store.update(cpath, { status: hidden ? 'visible' : 'hidden' }).then(reload, function (err) {
            toggle.disabled = false;
            actions.appendChild(el('span', 'form-msg', C.errors.message(err, 'form') || '沒有成功'));
          });
        });
        actions.appendChild(toggle);
      } else if (mine && x.status === 'visible') {
        var armed = null;
        var hide = C.dom.button('btn-link', '收起我的這一則', function () {
          if (!armed) {
            hide.textContent = '確定收起？收起後不能復原（再按一次）';
            armed = g.setTimeout(function () { armed = null; hide.textContent = '收起我的這一則'; }, 5000);
            return;
          }
          g.clearTimeout(armed);
          armed = null;
          hide.disabled = true;
          ctx.store.update(cpath, { status: 'hidden' }).then(reload, function (err) {
            hide.disabled = false;
            hide.textContent = '收起我的這一則';
            actions.appendChild(el('span', 'form-msg', C.errors.message(err, 'form') || '沒有成功'));
          });
        });
        actions.appendChild(hide);
      }
      item.appendChild(actions);
      return item;
    }

    function reload() {
      var name = teacher ? 'blogComments.thread.teacher' : 'blogComments.thread';
      return Promise.all([ctx.store.query(name, { entry: entryPath }), who]).then(function (r) {
        if (!ctx.isCurrent()) return;
        C.dom.clear(listBox);
        if (!r[0].items.length) {
          listBox.appendChild(el('p', 'empty', teacher ? '還沒有對話。' : '還沒有對話。想跟老師說什麼，寫在下面。'));
          return;
        }
        r[0].items.forEach(function (d) { listBox.appendChild(renderItem(d, r[1])); });
      }, function (err) {
        C.dom.clear(listBox);
        listBox.appendChild(C.errors.box(err, { where: 'list' }));
      });
    }

    // 表單
    var f = el('form', 'comment-form');
    f.noValidate = true;
    var label = el('label', 'field-label', teacher ? '回覆家長' : '寫給老師');
    label.htmlFor = 'bc-body';
    var ta = el('textarea', 'field field--area');
    ta.id = 'bc-body';
    ta.rows = 3;
    ta.maxLength = 500;
    var counter = el('span', 'field-counter', '0 / 500');
    ta.addEventListener('input', function () { counter.textContent = C.validate.len(ta.value) + ' / 500'; });
    var submit = el('button', 'btn btn--primary', '送出');
    submit.type = 'submit';
    var msg = el('p', 'form-msg');
    msg.setAttribute('aria-live', 'polite');
    C.dom.add(f, label, ta, counter, submit, msg);
    if (!myAlias) {
      submit.disabled = true;
      msg.textContent = '這個帳號的名單資料還沒準備好，暫時不能留言。';
    }
    f.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = {
        body: String(ta.value || '').trim(),
        role: teacher ? 'teacher' : 'parent',
        authorAlias: myAlias,
        status: 'visible',
        createdAt: C.SERVER_TIME
      };
      var coll = C.paths.blogComments(entryPath);
      try {
        C.validate.write('add', coll, data);
      } catch (err) {
        msg.textContent = C.errors.message(err, 'form');
        return;
      }
      submit.disabled = true;
      msg.textContent = '送出中…';
      ctx.store.add(coll, data).then(function () {
        ta.value = '';
        counter.textContent = '0 / 500';
        submit.disabled = false;
        msg.textContent = '已送出。';
        return reload();
      }, function (err) {
        submit.disabled = false;
        msg.textContent = C.errors.message(err, 'form') || '沒有送出，請稍後再試。';
      });
    });
    sec.appendChild(f);
    return { section: sec, ready: reload() };
  }

  function entryView(ctx, seat, postId) {
    if (!canSee(ctx, seat)) {
      return notice(ctx, '這個座號不在你的帳號底下，所以看不到。', href(''), '回我的孩子');
    }
    var teacher = isTeacher(ctx);
    var entryPath = C.paths.entry(seat, postId);
    var box = container(true);
    ctx.main.appendChild(box);
    return Promise.all([
      ctx.store.get(entryPath),
      blogDoc(ctx, seat).catch(function () { return null; }),
      teacher ? identity(ctx) : Promise.resolve(null)
    ]).then(function (r) {
      var doc = r[0];
      var blog = r[1];
      var who = r[2];
      var crumb = el('p', 'breadcrumb');
      crumb.appendChild(C.dom.link(href('seat/' + seat), null, '← ' + ((blog && blog.displayName) || '座號 ' + seat) + ' 的部落格'));
      box.appendChild(crumb);
      flashBox(box);
      if (!doc) {
        box.appendChild(el('p', 'notice', '這篇找不到（可能已下架或網址打錯了）。'));
        return null;
      }
      var x = doc.data || {};
      var art = el('article', 'post blog-post');
      var head = el('header', 'post-head');
      var meta = el('div', 'entry-meta');
      meta.appendChild(stamp(x.date));
      meta.appendChild(authorChip(x.author));
      if (who && x.author === 'parent') meta.appendChild(el('span', 'mc-identity', who(x.authorAlias, seat)));
      head.appendChild(meta);
      head.appendChild(el('h1', 'post-title', x.title || '（沒有標題）'));
      if (teacher) head.appendChild(visibilityToggle(ctx, entryPath, x, meta));
      art.appendChild(head);
      var photos = Array.isArray(x.photos) ? x.photos.filter(function (p) { return p && /^[0-2]$/.test(p.pid); }) : [];
      if (photos.length) art.appendChild(photoGallery(ctx, entryPath, photos));
      var body = el('div', 'blog-body');
      body.appendChild(C.text.render(x.body || ''));
      art.appendChild(body);
      box.appendChild(art);
      if (inThread(ctx, seat)) {
        var t = thread(ctx, seat, entryPath);
        box.appendChild(t.section);
        return t.ready;
      }
      box.appendChild(el('p', 'notice mc-note', '這篇文章底下老師與家長的對話，只有他們兩方看得到。'));
      return null;
    }, function (err) {
      var e = C.errors.from(err);
      if (e.code === 'denied' || e.code === 'invalid') {
        box.appendChild(el('p', 'notice', '這篇找不到（可能已下架或網址打錯了）。'));
        box.appendChild(C.dom.link(href('seat/' + seat), 'section-link', '回文章列表'));
        return null;
      }
      throw e;
    });
  }

  // ── 寫一篇 ───────────────────────────────────────────
  function composeView(ctx, seat) {
    var teacher = isTeacher(ctx);
    if (!teacher && !isParentOf(ctx, seat)) {
      return notice(ctx, '只有這位孩子的家長（和老師）可以在這裡寫文章。', href(''), '回我的孩子');
    }
    var box = container(true);
    ctx.main.appendChild(box);
    var crumb = el('p', 'breadcrumb');
    crumb.appendChild(C.dom.link(href('seat/' + seat), null, '← 回文章列表'));
    box.appendChild(crumb);
    var head = el('header', 'page-header');
    head.appendChild(el('p', 'eyebrow', 'New post・座號 ' + seat));
    head.appendChild(el('h1', 'page-title', teacher ? '以導師身分寫一篇' : '寫一篇'));
    box.appendChild(head);

    var f = el('form', 'compose-form');
    f.noValidate = true;
    var tl = el('label', 'field-label', '標題');
    tl.htmlFor = 'mc-title';
    var title = el('input', 'field');
    title.id = 'mc-title';
    title.maxLength = 200;
    title.placeholder = '例如：週末一起做的點心';
    var bl = el('label', 'field-label', '內文');
    bl.htmlFor = 'mc-body';
    var body = el('textarea', 'field field--area field--tall');
    body.id = 'mc-body';
    body.rows = 8;
    body.maxLength = 10000;
    var counter = el('span', 'field-counter', '0 / 10000');
    body.addEventListener('input', function () { counter.textContent = C.validate.len(body.value) + ' / 10000'; });

    var pl = el('label', 'field-label', '照片（最多 3 張，可以不放）');
    pl.htmlFor = 'mc-photos';
    var input = el('input', 'field field--file');
    input.id = 'mc-photos';
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;
    var slots = el('div', 'photo-slots');
    var privacy = el('p', 'mc-note', '照片會先在你的裝置上縮小，並去掉拍攝時間、地點（GPS）等資訊才上傳；原始照片檔不會上傳。');
    var submit = el('button', 'btn btn--primary', '發出');
    submit.type = 'submit';
    var msg = el('p', 'form-msg');
    msg.setAttribute('aria-live', 'polite');
    C.dom.add(f, tl, title, bl, body, counter, pl, input, slots, privacy);
    if (!teacher) f.appendChild(el('p', 'mc-note', '發出之後不能修改或刪除；需要修改的話，請跟老師說。'));
    C.dom.add(f, submit, msg);
    box.appendChild(f);

    var photos = []; // [{ id, image, thumb, caption: <input>, slot }]
    var busy = 0;
    var seq = 0;
    function refresh() {
      submit.disabled = busy > 0;
      input.disabled = photos.length >= C.photoEncode.MAX_PHOTOS;
    }

    function addFile(file) {
      if (photos.length >= C.photoEncode.MAX_PHOTOS) return Promise.resolve();
      var item = { id: ++seq, image: null, thumb: null, caption: null, slot: el('div', 'photo-slot is-busy') };
      photos.push(item);
      var status = el('p', 'photo-slot-status', '照片處理中…');
      item.slot.appendChild(status);
      slots.appendChild(item.slot);
      busy++;
      refresh();
      return C.photoEncode.encodeFile(file).then(function (r) {
        item.image = r.image;
        item.thumb = r.thumb;
        C.dom.clear(item.slot);
        item.slot.className = 'photo-slot';
        var img = el('img');
        img.alt = '';
        img.src = 'data:image/jpeg;base64,' + r.thumb.data;
        var cap = el('input', 'field field--small');
        cap.maxLength = 300;
        cap.placeholder = '圖說（可以不寫）';
        cap.setAttribute('aria-label', '這張照片的圖說');
        item.caption = cap;
        var remove = C.dom.button('btn-link', '移除', function () {
          photos = photos.filter(function (p) { return p !== item; });
          if (item.slot.parentNode) item.slot.parentNode.removeChild(item.slot);
          refresh();
        });
        C.dom.add(item.slot, img, cap, remove);
      }, function (err) {
        photos = photos.filter(function (p) { return p !== item; });
        C.dom.clear(item.slot);
        item.slot.className = 'photo-slot is-error';
        item.slot.appendChild(el('p', 'photo-slot-status', C.errors.message(err, 'form') || '這張照片處理不了，請換一張。'));
        var dismiss = C.dom.button('btn-link', '知道了', function () {
          if (item.slot.parentNode) item.slot.parentNode.removeChild(item.slot);
        });
        item.slot.appendChild(dismiss);
      }).then(function () {
        busy--;
        refresh();
      });
    }

    input.addEventListener('change', function () {
      var files = Array.prototype.slice.call(input.files || []);
      var room = C.photoEncode.MAX_PHOTOS - photos.length;
      if (files.length > room) msg.textContent = '照片最多 3 張，多的沒有放進來。';
      // 一張一張處理（手機記憶體有限）
      files.slice(0, Math.max(0, room)).reduce(function (p, file) {
        return p.then(function () { return addFile(file); });
      }, Promise.resolve());
      try { input.value = ''; } catch (e) { /* 舊瀏覽器清不掉也沒關係 */ }
    });

    f.addEventListener('submit', function (e) {
      e.preventDefault();
      if (busy) { msg.textContent = '照片還在處理中，請等一下。'; return; }
      var input2 = {
        seat: seat,
        title: title.value,
        body: body.value,
        photos: photos.map(function (p) { return { image: p.image, thumb: p.thumb, caption: p.caption ? p.caption.value : '' }; })
      };
      try {
        C.blogCompose.check(input2);
      } catch (err) {
        msg.textContent = C.errors.message(err, 'form');
        return;
      }
      submit.disabled = true;
      msg.textContent = '發出中…';
      C.blogCompose.submit(ctx.store, ctx.session, input2).then(function (postId) {
        flash = teacher ? '已經發出。' : '已經發出，老師會看到。';
        go('entry/' + seat + '/' + postId);
      }, function (err) {
        submit.disabled = false;
        // 表單內容留著；再按一次會換新的文章編號重送（批次是一次成功或一次失敗，不會留下半篇）
        msg.textContent = (C.errors.message(err, 'form') || '沒有發出去。') + ' 內容都還在，可以再按一次「發出」。';
      });
    });
    refresh();
    return null;
  }

  C.views['my-child'] = function (ctx) {
    var r = parseSub(ctx.route.sub);
    switch (r.view) {
      case 'home': return home(ctx);
      case 'admin':
        if (!isTeacher(ctx)) return home(ctx);
        return C.myChild.admin(ctx);
      case 'seat': return seatView(ctx, r.seat);
      case 'entry': return entryView(ctx, r.seat, r.postId);
      case 'new': return composeView(ctx, r.seat);
      default:
        return notice(ctx, '這個網址認不得。', href(''), '回我的孩子');
    }
  };

  C.myChild = C.myChild || {};
  C.myChild.parseSub = parseSub;
  C.myChild.href = href;
  C.myChild.avatar = avatar;
  C.myChild.identity = identity;
})(typeof window !== 'undefined' ? window : globalThis);
