/* blog-compose.js — 在網頁上發一篇部落格文章（docs/ARCHITECTURE.md §5.6、docs/DATA-MODEL.md §2.14）。

   一篇文章＝一個批次（最多 7 個寫入，一次成功或一次失敗）：
     student_blogs/{seat}/entries/{postId}          文章（photos 依序 { pid: '0'|'1'|'2', w, h, caption? }）
     …/entries/{postId}/images/{i}、…/thumbs/{i}      每張照片的顯示圖與縮圖（照片已經由 photo-encode.js 重新編碼）
   · postId 每次送出都重新產生（重試也是）：同一個 postId 再寫一次會變成「修改」而被規則拒絕。
   · 家長發的 author 是 'parent'、導師發的是 'teacher'；authorAlias 帶自己名單上的作者代號（規則會比對）。
   · 內文逐字保留（空白、換行照原樣），只擋「整篇都是空白」。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  function invalid(msg) { return new C.StoreError('invalid', msg); }

  /** 驗標題、內文、照片張數與圖說；不合就丟 invalid（訊息直接給人看）。 */
  function check(input) {
    var L = C.validate.LIMITS;
    var title = String(input.title || '').trim();
    var body = String(input.body === undefined || input.body === null ? '' : input.body);
    if (!title) throw invalid('請寫一個標題。');
    if (C.validate.len(title) > L.entryTitle[1]) throw invalid('標題最多 ' + L.entryTitle[1] + ' 字。');
    if (!body.trim()) throw invalid('內文不能是空的。');
    if (C.validate.len(body) > L.entryBody[1]) throw invalid('內文最多 ' + L.entryBody[1] + ' 字（現在 ' + C.validate.len(body) + ' 字）。');
    var photos = input.photos || [];
    if (photos.length > L.photosPerEntry) throw invalid('照片最多 ' + L.photosPerEntry + ' 張。');
    photos.forEach(function (p) {
      if (!p || !p.image || !p.thumb) throw invalid('照片還在處理中，請等一下再送出。');
      if (p.caption && C.validate.len(p.caption) > L.caption) throw invalid('圖說最多 ' + L.caption + ' 字。');
    });
    return { title: title, body: body, photos: photos };
  }

  /** 組批次的寫入清單（不送出）。input：{ seat, postId, date, author, authorAlias, title, body, photos } */
  function ops(input) {
    var v = check(input);
    var entryPath = C.paths.entry(input.seat, input.postId);
    var refs = v.photos.map(function (p, i) {
      var ref = { pid: String(i), w: p.image.w, h: p.image.h };
      var cap = String(p.caption || '').trim();
      if (cap) ref.caption = cap;
      return ref;
    });
    var list = [{
      op: 'set',
      path: entryPath,
      data: {
        title: v.title,
        body: v.body,
        date: input.date,
        author: input.author,
        authorAlias: input.authorAlias,
        photos: refs,
        visible: true,
        createdAt: C.SERVER_TIME
      }
    }];
    v.photos.forEach(function (p, i) {
      var pid = String(i);
      list.push({ op: 'set', path: C.paths.image(entryPath, pid), data: { data: p.image.data, w: p.image.w, h: p.image.h } });
      list.push({ op: 'set', path: C.paths.thumb(entryPath, pid), data: { data: p.thumb.data, w: p.thumb.w, h: p.thumb.h, order: i } });
    });
    return list;
  }

  /** 送出：每次都換新的 postId → store.batch。成功回傳 postId；失敗原樣丟出（表單內容由畫面保留）。 */
  function submit(store, session, input) {
    var roles = session && session.roles ? session.roles : {};
    var author = roles.teacher ? 'teacher' : 'parent';
    if (!roles.alias) return Promise.reject(invalid('這個帳號的名單資料還沒準備好，暫時不能發文。'));
    if (!roles.teacher && (roles.seatKind !== 'parent' || (roles.seats || []).indexOf(input.seat) < 0)) {
      return Promise.reject(invalid('只有這位孩子的家長可以在這裡發文。'));
    }
    var list;
    var postId;
    try {
      // 規則要求 date == postId 的前 10 碼（DATA-MODEL §2.14）：同一個日期只算一次，跨午夜也不會對不上
      var date = C.util.today();
      postId = store.newPostId(date);
      list = ops({
        seat: input.seat,
        postId: postId,
        date: date,
        author: author,
        authorAlias: roles.alias,
        title: input.title,
        body: input.body,
        photos: input.photos
      });
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
    return store.batch(list).then(function () { return postId; });
  }

  C.blogCompose = { check: check, ops: ops, submit: submit };
})(typeof window !== 'undefined' ? window : globalThis);
