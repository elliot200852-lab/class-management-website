/* store.js — 資料存取層（Store）的介面說明與選擇器 CMW.getStore()（docs/ARCHITECTURE.md §2）。

   頁面程式不直接碰 Firebase SDK，一律透過 Store。兩個實作回傳同一種形狀：
     FirestoreStore（store-firestore.js）：真站，全 repo 唯一載入 Firebase SDK 的檔
     DemoStore（store-demo.js）：示範模式，零網路，資料只存在這個瀏覽器

   型別（JSDoc）：
     Session { state: 'loading'|'signed-out'|'denied'|'ready',
               user:  { uid, email, emailKey, provider: 'google.com'|'emailLink' } | null,
               roles: { teacher, reader, privateReader, kind, alias, seats, seatKind } }
     Doc     { id, path, data }   data 裡的時間一律是 Date（伺服器還沒填上時是 null）；
                                   另有不可列舉的 doc.cursor，可以原樣當 { after: … }／{ before: … }
     Page    { items: Doc[], next: 游標或 null }
     Op      { op: 'set'|'update', path, data }

   方法（完整 20 個，兩個實作都要有；tests/js/store.test.js 逐一比對）：
     A 身分：onSession(cb)、getSession()、signInWithGoogle()、sendSignInLink(email)、
             completeSignInLink(email?)、signOut()
     B 讀取：get(path)、query(name, params?, page?)、watch(name, params, cb)、count(name, params)
     C 寫入：add(collectionPath, data)、set(path, data)、update(path, patch)、batch(ops)
     D 語意：photoSrc(ownerPath, pid, size)、markRead(threadPath)、newPostId(date?)
     E 示範：isDemo（屬性）、demoSetRole(role, opts?)、demoReset() */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  C.STORE_METHODS = [
    'onSession', 'getSession', 'signInWithGoogle', 'sendSignInLink', 'completeSignInLink', 'signOut',
    'get', 'query', 'watch', 'count',
    'add', 'set', 'update', 'batch',
    'photoSrc', 'markRead', 'newPostId',
    'isDemo', 'demoSetRole', 'demoReset'
  ];

  C.emptyRoles = function () {
    return { teacher: false, reader: false, privateReader: false, kind: null, alias: null, seats: [], seatKind: null };
  };

  C.loadingSession = function () {
    return { state: 'loading', user: null, roles: C.emptyRoles() };
  };

  /** 組一份 Doc；cursor 不可列舉（JSON 化、比較時不會帶到）。 */
  C.makeDoc = function (path, data, cursor) {
    var segs = String(path).split('/');
    var d = { id: segs[segs.length - 1], path: path, data: data };
    Object.defineProperty(d, 'cursor', { value: cursor === undefined ? { path: path, data: data } : cursor, enumerable: false });
    return d;
  };

  var instance = null;

  /** 同一頁只建一個 Store（ARCHITECTURE §2.1）。 */
  C.getStore = function () {
    if (instance) return instance;
    var mode = C.detectMode();
    if (mode.demo) {
      if (typeof C.DemoStore !== 'function') throw new Error('示範模式的程式沒有載入（store-demo.js）');
      instance = new C.DemoStore(mode);
    } else {
      if (typeof C.FirestoreStore !== 'function') throw new Error('真站的程式沒有載入（store-firestore.js）');
      instance = new C.FirestoreStore(C.config(), mode);
    }
    return instance;
  };

  /** 只給測試用：丟掉目前的 Store 實例 */
  C._resetStore = function () { instance = null; };
})(typeof window !== 'undefined' ? window : globalThis);
