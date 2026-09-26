/* comments.js — 留言區（班級紀事、相簿、私密紀事三處共用；docs/DATA-MODEL.md §2.7）。

   · 讀：comments.thread（即時；導師用 comments.thread.teacher，看得到收起的留言）。
   · 寫：store.add(串/comments)，欄位只放 authorName、body、role、authorAlias、status、createdAt、replyTo；
     role 與 authorAlias 由規則強制等於名單上的值，這裡只是照 Session 帶上去。
   · 署名是本人自填的，可以亂寫；旁邊固定畫「導師／家長／同仁」標籤，標籤假冒不了。
     再畫作者代號的前 4 碼（authorAlias 由規則綁名單）：兩則署名一樣、代號不一樣＝不是同一個帳號寫的。
   · email 連結登入的讀者只能讀（規則不准留言，DATA-MODEL §1.1）：表單停用並說明要改用 Google 登入。
   · 導師可以把任何一則收起（hidden）或還原。留言一律當純文字畫（CMW.text）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};
  var el = function (t, c, x) { return C.dom.el(t, c, x); };

  var ROLE_LABEL = { teacher: '導師', parent: '家長', staff: '同仁' };
  var NAME_KEY = 'cmw-comment-name';

  function lsGet(k) { try { return g.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { g.localStorage.setItem(k, v); } catch (e) { /* 忽略 */ } }

  function roleTag(role) {
    return el('span', 'role-tag role-tag--' + (ROLE_LABEL[role] ? role : 'unknown'), ROLE_LABEL[role] || '？');
  }

  /** 作者代號短碼（前 4 碼）；代號格式不對就不畫 */
  function aliasTag(alias) {
    if (typeof alias !== 'string' || !/^[a-z0-9]{12}$/.test(alias)) return null;
    var t = el('span', 'comment-alias', '#' + alias.slice(0, 4));
    t.setAttribute('title', '帳號代號：同一個帳號留言，這 4 碼都一樣。署名是本人自己填的，看不出是誰時以代號為準。');
    return t;
  }

  /** 依 replyTo 排成「主留言＋底下的回覆」，時間由舊到新 */
  function threadify(items) {
    var asc = items.slice().sort(function (a, b) {
      var ta = a.data.createdAt instanceof Date ? a.data.createdAt.getTime() : Infinity;
      var tb = b.data.createdAt instanceof Date ? b.data.createdAt.getTime() : Infinity;
      return ta - tb;
    });
    var byId = {};
    asc.forEach(function (d) { byId[d.id] = { doc: d, replies: [] }; });
    var roots = [];
    asc.forEach(function (d) {
      var parent = d.data.replyTo && byId[d.data.replyTo] && d.data.replyTo !== d.id ? byId[d.data.replyTo] : null;
      if (parent && !parent.doc.data.replyTo) parent.replies.push(byId[d.id]);
      else roots.push(byId[d.id]);
    });
    return roots;
  }

  function mount(ctx, container, threadPath, opts) {
    opts = opts || {};
    var session = ctx.session;
    var teacher = session.roles.teacher;
    var readOnly = C.readOnlyLogin(session);
    var sec = el('section', 'comments');
    sec.setAttribute('aria-labelledby', 'comments-title');
    var h = el('h2', 'comments-title', '留言');
    h.id = 'comments-title';
    sec.appendChild(h);
    var listBox = el('div', 'comment-list');
    listBox.appendChild(C.dom.loading('讀取留言中…'));
    sec.appendChild(listBox);

    var replyTo = null;
    var formParts = form();
    sec.appendChild(formParts.form);
    container.appendChild(sec);

    function renderOne(node, isReply) {
      var d = node.doc;
      var x = d.data;
      var item = el('article', 'comment' + (isReply ? ' comment--reply' : '') + (x.status === 'hidden' ? ' is-hidden' : ''));
      var head = el('header', 'comment-head');
      head.appendChild(el('strong', 'comment-name', x.authorName || '（沒有署名）'));
      head.appendChild(roleTag(x.role));
      var at = aliasTag(x.authorAlias);
      if (at) head.appendChild(at);
      if (session.roles.alias && x.authorAlias === session.roles.alias) head.appendChild(el('span', 'comment-mine', '我'));
      var t = el('time', 'comment-time', C.util.fmtTime(x.createdAt));
      head.appendChild(t);
      item.appendChild(head);
      var body = el('p', 'comment-body');
      body.appendChild(C.text.render(x.body || ''));
      item.appendChild(body);
      if (x.status === 'hidden') item.appendChild(el('p', 'comment-hidden-note', '已收起：只有導師看得到這則留言。'));
      var actions = el('div', 'comment-actions');
      if (!isReply && x.status !== 'hidden' && !readOnly) {
        actions.appendChild(C.dom.button('btn-link', '回覆', function () {
          replyTo = { id: d.id, name: x.authorName || '' };
          formParts.showReply();
          formParts.body.focus();
        }));
      }
      if (teacher) {
        var hidden = x.status === 'hidden';
        var toggle = C.dom.button('btn-link', hidden ? '還原顯示' : '收起', function () {
          toggle.disabled = true;
          ctx.store.update(C.paths.comment(threadPath, d.id), { status: hidden ? 'visible' : 'hidden' }).then(function () {
            toggle.disabled = false;
          }, function (err) {
            toggle.disabled = false;
            actions.appendChild(el('span', 'form-msg', C.errors.message(err, 'form') || '沒有成功'));
          });
        });
        actions.appendChild(toggle);
      }
      item.appendChild(actions);
      return item;
    }

    function renderList(page, err) {
      C.dom.clear(listBox);
      if (err) {
        listBox.appendChild(C.errors.box(err, { where: 'list' }));
        return;
      }
      var roots = threadify(page.items);
      if (!roots.length) {
        listBox.appendChild(el('p', 'empty', '還沒有留言。說一句話給老師與大家吧。'));
        return;
      }
      h.textContent = '留言（' + page.items.filter(function (d) { return d.data.status !== 'hidden'; }).length + '）';
      roots.forEach(function (node) {
        var wrap = el('div', 'comment-thread');
        wrap.appendChild(renderOne(node, false));
        node.replies.forEach(function (r) { wrap.appendChild(renderOne(r, true)); });
        listBox.appendChild(wrap);
      });
    }

    var first = true;
    var firstLoad = new Promise(function (resolve) {
      var name = teacher ? 'comments.thread.teacher' : 'comments.thread';
      var stop = ctx.store.watch(name, { thread: threadPath }, function (page, err) {
        if (!ctx.isCurrent()) return;
        renderList(page, err);
        if (first) { first = false; resolve(); }
      });
      ctx.onCleanup(stop);
    });
    ctx.track(firstLoad);

    function form() {
      var f = el('form', 'comment-form');
      f.noValidate = true;
      var replyBar = el('p', 'comment-replying');
      replyBar.hidden = true;
      var replyText = el('span');
      var cancel = C.dom.button('btn-link', '取消回覆', function () {
        replyTo = null;
        replyBar.hidden = true;
      });
      C.dom.add(replyBar, replyText, ' ', cancel);
      var nameLabel = el('label', 'field-label', '署名');
      nameLabel.htmlFor = 'comment-name';
      var name = el('input', 'field');
      name.id = 'comment-name';
      name.maxLength = 20;
      name.placeholder = '例如：某某的媽媽';
      name.value = lsGet(NAME_KEY) || '';
      if (!name.value && teacher) {
        ctx.siteInfo().then(function (info) {
          if (!name.value && info && info.teacherDisplayName) name.value = info.teacherDisplayName;
        });
      }
      var bodyLabel = el('label', 'field-label', '留言');
      bodyLabel.htmlFor = 'comment-body';
      var body = el('textarea', 'field field--area');
      body.id = 'comment-body';
      body.rows = 3;
      body.maxLength = 500;
      var counter = el('span', 'field-counter', '0 / 500');
      body.addEventListener('input', function () {
        counter.textContent = C.validate.len(body.value) + ' / 500';
      });
      var submit = el('button', 'btn btn--primary', '送出留言');
      submit.type = 'submit';
      var msg = el('p', 'form-msg');
      msg.setAttribute('aria-live', 'polite');
      C.dom.add(f, replyBar, nameLabel, name, bodyLabel, body, counter, submit, msg);
      if (readOnly) {
        submit.disabled = true;
        name.disabled = true;
        body.disabled = true;
        msg.textContent = C.READ_ONLY_LOGIN_MSG;
      } else if (!session.roles.kind || !session.roles.alias) {
        submit.disabled = true;
        msg.textContent = '這個帳號的名單資料還沒準備好，暫時不能留言。';
      }
      f.addEventListener('submit', function (e) {
        e.preventDefault();
        var data = {
          authorName: String(name.value || '').trim(),
          body: String(body.value || '').trim(),
          role: session.roles.kind,
          authorAlias: session.roles.alias,
          status: 'visible',
          createdAt: C.SERVER_TIME
        };
        if (replyTo) data.replyTo = replyTo.id;
        try {
          C.validate.write('add', threadPath + '/comments', data);
        } catch (err) {
          msg.textContent = C.errors.message(err, 'form');
          return;
        }
        submit.disabled = true;
        msg.textContent = '送出中…';
        ctx.store.add(threadPath + '/comments', data).then(function () {
          lsSet(NAME_KEY, data.authorName);
          body.value = '';
          counter.textContent = '0 / 500';
          replyTo = null;
          replyBar.hidden = true;
          submit.disabled = false;
          msg.textContent = '已送出，謝謝你的留言。';
        }, function (err) {
          submit.disabled = false;
          msg.textContent = C.errors.message(err, 'form') || '沒有送出，請稍後再試。';
        });
      });
      return {
        form: f,
        body: body,
        showReply: function () {
          replyText.textContent = '回覆「' + (replyTo ? replyTo.name : '') + '」：';
          replyBar.hidden = false;
        }
      };
    }
    return sec;
  }

  C.comments = { mount: mount, roleTag: roleTag, aliasTag: aliasTag, ROLE_LABEL: ROLE_LABEL, threadify: threadify };
})(typeof window !== 'undefined' ? window : globalThis);
