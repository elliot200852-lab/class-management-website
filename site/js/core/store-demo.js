/* store-demo.js — DemoStore：示範模式的 Store（docs/ARCHITECTURE.md §2.7）。

   · 零網路：不載 Firebase SDK、不 fetch 任何東西，拔掉網路線也能用。
   · 資料：demo-data.js 的內建資料；寫入疊在上面，存 localStorage（鍵名前綴 cmw-demo-v2:），
     每一次讀寫都包 try/catch；localStorage 不能用時只存在記憶體，畫面照常。
   · 只展示、不模擬拒絕：任何角色讀什麼都拿得到。切換角色只改 Session（畫面長什麼樣）。
     權限只在安全規則一個地方定義，並且只在模擬器驗。
   · 查詢一律走 query-eval.js，跟真站吃同一份 CMW.QUERIES，所以沒登記的查詢名一樣會被擋。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var PREFIX = 'cmw-demo-v2:';
  var K_ROLE = PREFIX + 'role';
  var K_WRITES = PREFIX + 'writes';
  var DEFAULT_ROLE = { role: 'parent', seat: '01' };

  function lsGet(k) {
    try { return g.localStorage ? g.localStorage.getItem(k) : null; } catch (e) { return null; }
  }
  function lsSet(k, v) {
    try { if (g.localStorage) g.localStorage.setItem(k, v); return true; } catch (e) { return false; }
  }
  function lsDel(k) {
    try { if (g.localStorage) g.localStorage.removeItem(k); } catch (e) { /* 忽略 */ }
  }

  // 時間在 localStorage 裡存成 { $d: ISO 字串 }
  function enc(v) {
    if (v instanceof Date) return { $d: v.toISOString() };
    if (Array.isArray(v)) return v.map(enc);
    if (v && typeof v === 'object') {
      var o = {};
      Object.keys(v).forEach(function (k) { o[k] = enc(v[k]); });
      return o;
    }
    return v;
  }
  function dec(v) {
    if (Array.isArray(v)) return v.map(dec);
    if (v && typeof v === 'object') {
      if (typeof v.$d === 'string' && Object.keys(v).length === 1) return new Date(v.$d);
      var o = {};
      Object.keys(v).forEach(function (k) { o[k] = dec(v[k]); });
      return o;
    }
    return v;
  }
  function clone(v) { return dec(enc(v)); }

  function stamp(data) {
    var o = {};
    Object.keys(data).forEach(function (k) {
      o[k] = C.isServerTime(data[k]) ? new Date() : clone(data[k]);
    });
    return o;
  }

  function invalid(msg) { return new C.StoreError('invalid', msg); }

  function DemoStore(mode) {
    this.isDemo = true;
    this.mode = mode || { demo: true, reason: 'demo' };
    this._subs = [];
    this._watches = [];
    this._load();
    var r = null;
    try { r = JSON.parse(lsGet(K_ROLE) || 'null'); } catch (e) { r = null; }
    this._role = r && typeof r.role === 'string' ? r : DEFAULT_ROLE;
    this._session = C.demoData.session(this._role.role, this._role.seat);
  }

  DemoStore.prototype._load = function () {
    var built = C.demoData.build();
    this.info = built.info;
    var db = {};
    built.docs.forEach(function (d) { db[d[0]] = d[1]; });
    var writes = [];
    try { writes = JSON.parse(lsGet(K_WRITES) || '[]'); } catch (e) { writes = []; }
    if (!Array.isArray(writes)) writes = [];
    writes.forEach(function (w) {
      if (!w || typeof w.path !== 'string') return;
      var data = dec(w.data);
      if (w.op === 'update' && db[w.path]) {
        var merged = {};
        Object.keys(db[w.path]).forEach(function (k) { merged[k] = db[w.path][k]; });
        Object.keys(data).forEach(function (k) { merged[k] = data[k]; });
        db[w.path] = merged;
      } else if (w.op === 'set') {
        db[w.path] = data;
      }
    });
    this._db = db;
    this._writes = writes;
  };

  DemoStore.prototype._docs = function () {
    var db = this._db;
    return Object.keys(db).map(function (p) { return { path: p, data: db[p] }; });
  };

  DemoStore.prototype._persist = function (op, path, data) {
    this._writes.push({ op: op, path: path, data: enc(data) });
    lsSet(K_WRITES, JSON.stringify(this._writes));
  };

  DemoStore.prototype._apply = function (op, path, data) {
    if (op === 'update') {
      if (!this._db[path]) throw invalid('要更新的文件不存在');
      var merged = {};
      var cur = this._db[path];
      Object.keys(cur).forEach(function (k) { merged[k] = cur[k]; });
      Object.keys(data).forEach(function (k) { merged[k] = data[k]; });
      this._db[path] = merged;
    } else {
      this._db[path] = data;
    }
    this._persist(op, path, data);
  };

  DemoStore.prototype._toPage = function (res) {
    return {
      items: res.items.map(function (d) { return C.makeDoc(d.path, clone(d.data), { path: d.path, data: d.data }); }),
      next: res.next ? { path: res.next.path, data: res.next.data } : null
    };
  };

  DemoStore.prototype._notify = function () {
    var self = this;
    this._watches.forEach(function (w) { self._runWatch(w); });
  };

  DemoStore.prototype._runWatch = function (w) {
    var page;
    try {
      page = this._toPage(C.queryEval.run(this._docs(), w.name, w.params));
    } catch (e) {
      w.cb(null, C.errors.from(e));
      return;
    }
    w.cb(page);
  };

  DemoStore.prototype._emit = function () {
    var s = this._session;
    this._subs.forEach(function (cb) { cb(s); });
  };

  // ── A. 身分與登入 ──────────────────────────────────
  DemoStore.prototype.onSession = function (cb) {
    var self = this;
    this._subs.push(cb);
    var s = this._session;
    g.setTimeout(function () { if (self._subs.indexOf(cb) >= 0) cb(s); }, 0);
    return function () {
      var i = self._subs.indexOf(cb);
      if (i >= 0) self._subs.splice(i, 1);
    };
  };

  DemoStore.prototype.getSession = function () {
    return this._session;
  };

  /** 示範模式沒有真的登入：等同選一個示範角色（預設學生 A 家長）。 */
  DemoStore.prototype.signInWithGoogle = function () {
    this.demoSetRole('parent', { seat: '01' });
    return Promise.resolve();
  };

  DemoStore.prototype.sendSignInLink = function () {
    return Promise.reject(new C.StoreError('invalid', '示範模式不寄信。'));
  };

  DemoStore.prototype.completeSignInLink = function () {
    return Promise.resolve(false);
  };

  DemoStore.prototype.signOut = function () {
    this.demoSetRole('signed-out');
    return Promise.resolve();
  };

  // ── B. 通用讀取 ────────────────────────────────────
  DemoStore.prototype.get = function (path) {
    if (!C.paths.isDocPath(path)) return Promise.reject(invalid('文件路徑不對'));
    var data = this._db[path];
    return Promise.resolve(data ? C.makeDoc(path, clone(data), { path: path, data: data }) : null);
  };

  DemoStore.prototype.query = function (name, params, page) {
    try {
      return Promise.resolve(this._toPage(C.queryEval.run(this._docs(), name, params, page)));
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  DemoStore.prototype.watch = function (name, params, cb) {
    var self = this;
    C.queryEval.checkWatch(name);
    var w = { name: name, params: params || {}, cb: cb };
    this._watches.push(w);
    g.setTimeout(function () { if (self._watches.indexOf(w) >= 0) self._runWatch(w); }, 0);
    return function () {
      var i = self._watches.indexOf(w);
      if (i >= 0) self._watches.splice(i, 1);
    };
  };

  DemoStore.prototype.count = function (name, params) {
    try {
      return Promise.resolve(C.queryEval.count(this._docs(), name, params));
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  // ── C. 通用寫入（照同一套欄位檢查，存 localStorage） ─────────
  DemoStore.prototype.add = function (collectionPath, data) {
    try {
      if (!C.paths.isCollectionPath(collectionPath)) throw invalid('集合路徑不對');
      C.validate.write('add', collectionPath, data);
      var id = C.util.randomId(20);
      this._apply('set', collectionPath + '/' + id, stamp(data));
      this._notify();
      return Promise.resolve(id);
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  DemoStore.prototype.set = function (path, data) {
    try {
      if (!C.paths.isDocPath(path)) throw invalid('文件路徑不對');
      C.validate.write('set', path, data);
      this._apply('set', path, stamp(data));
      this._notify();
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  DemoStore.prototype.update = function (path, patch) {
    try {
      if (!C.paths.isDocPath(path)) throw invalid('文件路徑不對');
      C.validate.write('update', path, patch);
      this._apply('update', path, stamp(patch));
      this._notify();
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  DemoStore.prototype.batch = function (ops) {
    try {
      C.validate.batch(ops);
      var self = this;
      ops.forEach(function (o) {
        if (!C.paths.isDocPath(o.path)) throw invalid('文件路徑不對');
      });
      ops.forEach(function (o) { self._apply(o.op, o.path, stamp(o.data)); });
      this._notify();
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(C.errors.from(e));
    }
  };

  // ── D. 語意方法 ────────────────────────────────────
  DemoStore.prototype.photoSrc = function (ownerPath, pid, size) {
    try {
      var p = size === 'image' ? C.paths.image(ownerPath, pid) : C.paths.thumb(ownerPath, pid);
      var doc = this._db[p];
      if (!doc) return Promise.resolve(null);
      // 在示範站裡用瀏覽器發文上傳的照片是真的 JPEG；內建資料沒有照片檔，就畫剪影
      if (C.photos.isBase64(doc.data, size === 'image' ? 716800 : 49152)) {
        return Promise.resolve('data:image/jpeg;base64,' + doc.data);
      }
      return Promise.resolve(C.demoArt.src(ownerPath, pid, size));
    } catch (e) {
      return Promise.resolve(null);
    }
  };

  DemoStore.prototype.markRead = function () {
    return Promise.resolve();
  };

  DemoStore.prototype.newPostId = function (date) {
    return C.util.newPostId(date);
  };

  // ── E. 示範模式專用 ────────────────────────────────
  /** role：'signed-out'｜'reader'｜'parent'｜'staff'｜'private'｜'teacher'；opts.seat：家長的座號 */
  DemoStore.prototype.demoSetRole = function (role, opts) {
    var allowed = ['signed-out', 'reader', 'parent', 'staff', 'private', 'teacher'];
    if (allowed.indexOf(role) < 0) throw invalid('不認得的示範角色：' + role);
    var seat = opts && opts.seat;
    this._role = { role: role, seat: seat || '01' };
    lsSet(K_ROLE, JSON.stringify(this._role));
    this._session = C.demoData.session(role, this._role.seat);
    this._emit();
  };

  DemoStore.prototype.demoRole = function () {
    return { role: this._role.role, seat: this._role.seat };
  };

  DemoStore.prototype.demoReset = function () {
    lsDel(K_WRITES);
    lsDel(K_ROLE);
    this._load();
    this._role = DEFAULT_ROLE;
    this._session = C.demoData.session(DEFAULT_ROLE.role, DEFAULT_ROLE.seat);
    this._notify();
    this._emit();
  };

  C.DemoStore = DemoStore;
})(typeof window !== 'undefined' ? window : globalThis);
