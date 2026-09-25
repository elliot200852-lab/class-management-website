/* store-firestore.js — FirestoreStore：真站用的 Store（docs/ARCHITECTURE.md §2）。

   全 repo「唯一」載入 Firebase JS SDK 的檔：用動態 import() 從官方 CDN 載入，版本寫死在 SDK_VERSION，
   只有真站模式才會呼叫（示範模式根本不載這支）。
   這支只做三件事：把登記過的查詢形狀變成 SDK 呼叫、轉型別（Timestamp → Date）、
   把 SDK 的錯誤轉成 StoreError。不畫畫面、不判斷權限（權限是安全規則的事）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var SDK_VERSION = '12.19.0';
  var SDK_BASE = 'https://www.gstatic.com/firebasejs/' + SDK_VERSION + '/';
  var SESSION_CACHE_KEY = 'cmw-session-v2';
  var SESSION_TTL_MS = 30 * 60 * 1000;
  var EMAIL_FOR_LINK_KEY = 'cmw-signin-email';
  var B64_RE = /^[A-Za-z0-9+/]+={0,2}$/;

  function ssGet(k) { try { return g.sessionStorage.getItem(k); } catch (e) { return null; } }
  function ssSet(k, v) { try { g.sessionStorage.setItem(k, v); } catch (e) { /* 忽略 */ } }
  function ssDel(k) { try { g.sessionStorage.removeItem(k); } catch (e) { /* 忽略 */ } }
  function lsGet(k) { try { return g.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { g.localStorage.setItem(k, v); } catch (e) { /* 忽略 */ } }
  function lsDel(k) { try { g.localStorage.removeItem(k); } catch (e) { /* 忽略 */ } }

  function invalid(msg) { return new C.StoreError('invalid', msg); }

  function FirestoreStore(config, mode) {
    this.isDemo = false;
    this.mode = mode || { demo: false, reason: 'live' };
    this._cfg = config || {};
    this._sdk = null;
    this._session = C.loadingSession();
    this._subs = [];
    this._photoMemo = {};
    this._authStarted = false;
  }

  /** 載入 SDK 並初始化（只做一次）。載不到（外掛擋住、網路斷）→ StoreError('unavailable')。 */
  FirestoreStore.prototype._ready = function () {
    if (this._sdk) return this._sdk;
    var cfg = this._cfg;
    var fb = cfg.firebase || {};
    this._sdk = Promise.all([
      import(SDK_BASE + 'firebase-app.js'),
      import(SDK_BASE + 'firebase-auth.js'),
      import(SDK_BASE + 'firebase-firestore.js')
    ]).then(function (mods) {
      var A = mods[0];
      var AU = mods[1];
      var F = mods[2];
      var app = A.initializeApp({
        apiKey: fb.apiKey,
        authDomain: fb.authDomain,
        projectId: fb.projectId,
        appId: fb.appId,
        messagingSenderId: fb.messagingSenderId
      });
      var db;
      try {
        // IndexedDB 不能用（私密視窗、被封鎖）時 SDK 會自己退回記憶體快取；這裡再多包一層保險
        db = F.initializeFirestore(app, { localCache: F.persistentLocalCache({ tabManager: F.persistentMultipleTabManager() }) });
      } catch (e) {
        db = F.initializeFirestore(app, { localCache: F.memoryLocalCache() });
      }
      var auth = AU.getAuth(app);
      if (cfg.emulator === true) {
        AU.connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
        F.connectFirestoreEmulator(db, '127.0.0.1', 8080);
      }
      return { A: A, AU: AU, F: F, app: app, db: db, auth: auth };
    }, function (err) {
      throw new C.StoreError('unavailable', '登入元件載不下來（可能被瀏覽器外掛或網路擋住）', err);
    });
    return this._sdk;
  };

  // ── 型別轉換 ─────────────────────────────────────
  function toPlain(v) {
    if (v === null || v === undefined) return v === undefined ? null : v;
    if (typeof v === 'object') {
      if (typeof v.toDate === 'function' && typeof v.seconds === 'number') return v.toDate();
      if (Array.isArray(v)) return v.map(toPlain);
      var o = {};
      Object.keys(v).forEach(function (k) { o[k] = toPlain(v[k]); });
      return o;
    }
    return v;
  }

  function snapToDoc(snap) {
    // serverTimestamps: 'none' → 伺服器還沒填上的時間是 null
    return C.makeDoc(snap.ref.path, toPlain(snap.data({ serverTimestamps: 'none' })), snap);
  }

  function prepare(F, data) {
    var o = {};
    Object.keys(data).forEach(function (k) {
      o[k] = C.isServerTime(data[k]) ? F.serverTimestamp() : data[k];
    });
    return o;
  }

  /** 登記的查詢 → SDK 的 Query */
  FirestoreStore.prototype._buildQuery = function (sdk, name, params, page, forCount) {
    var F = sdk.F;
    var s = C.queryEval.spec(name);
    params = params || {};
    var t = C.queryEval.target(s, params);
    var base = t.group ? F.collectionGroup(sdk.db, t.group) : F.collection(sdk.db, t.path);
    var cons = [];
    (s.where || []).forEach(function (w) {
      cons.push(F.where(w[0], w[1], C.queryEval.whereValue(w[2], params)));
    });
    if (!forCount) {
      (s.orderBy || []).forEach(function (o) { cons.push(F.orderBy(o[0], o[1])); });
      if (page && (page.after || page.before)) {
        if (page.after) {
          if (s.cursor !== 'startAfter') throw invalid('這個查詢的游標是 ' + s.cursor);
          cons.push(F.startAfter(page.after));
        } else {
          if (s.cursor !== 'endBefore') throw invalid('這個查詢的游標是 ' + s.cursor);
          cons.push(F.endBefore(page.before));
        }
      }
      var lim = C.queryEval.limitOf(s, params);
      cons.push(s.limitToLast ? F.limitToLast(lim) : F.limit(lim));
    }
    return { q: F.query.apply(null, [base].concat(cons)), spec: s, limit: forCount ? 0 : C.queryEval.limitOf(s, params) };
  };

  function toPage(snap, s, lim) {
    var items = snap.docs.map(snapToDoc);
    if (s.sortClient) items = C.queryEval.sortClient(items, s.sortClient);
    var next = !s.limitToLast && snap.docs.length === lim ? snap.docs[snap.docs.length - 1] : null;
    return { items: items, next: next };
  }

  // ── A. 身分與登入 ──────────────────────────────────
  FirestoreStore.prototype._emit = function (s) {
    this._session = s;
    this._subs.forEach(function (cb) { cb(s); });
  };

  FirestoreStore.prototype._startAuth = function () {
    if (this._authStarted) return;
    this._authStarted = true;
    var self = this;
    this._ready().then(function (sdk) {
      // 從 Google 登入的轉址頁回來時，把錯誤（例如使用者取消）吃掉，避免主控台報錯
      sdk.AU.getRedirectResult(sdk.auth).catch(function () { /* 由畫面上的按鈕重試 */ });
      sdk.AU.onAuthStateChanged(sdk.auth, function (user) {
        if (!user) {
          ssDel(SESSION_CACHE_KEY);
          self._emit({ state: 'signed-out', user: null, roles: C.emptyRoles() });
          return;
        }
        self._resolveSession(sdk, user).then(function (s) { self._emit(s); }, function (err) {
          self._emit({ state: 'denied', user: self._userOf(user), roles: C.emptyRoles(), error: C.errors.from(err) });
        });
      });
    }, function (err) {
      self._emit({ state: 'signed-out', user: null, roles: C.emptyRoles(), error: C.errors.from(err) });
    });
  };

  FirestoreStore.prototype._userOf = function (user) {
    var key = null;
    try { key = C.emailKey(user.email || ''); } catch (e) { key = null; }
    var provider = 'emailLink';
    (user.providerData || []).forEach(function (p) { if (p && p.providerId === 'google.com') provider = 'google.com'; });
    return { uid: user.uid, email: user.email || '', emailKey: key, provider: provider };
  };

  /** 登入後平行讀四份（DATA-MODEL §1.2）→ Session。結果在同一分頁暫存 30 分鐘。 */
  FirestoreStore.prototype._resolveSession = function (sdk, user) {
    var F = sdk.F;
    var u = this._userOf(user);
    if (!u.emailKey || user.emailVerified === false) {
      return Promise.resolve({ state: 'denied', user: u, roles: C.emptyRoles() });
    }
    try {
      var cached = JSON.parse(ssGet(SESSION_CACHE_KEY) || 'null');
      if (cached && cached.uid === u.uid && Date.now() - cached.at < SESSION_TTL_MS && cached.session) {
        return Promise.resolve(cached.session);
      }
    } catch (e) { /* 暫存壞了就重讀 */ }

    function getOrNull(path) {
      return F.getDoc(F.doc(sdk.db, path)).then(function (snap) {
        return snap.exists() ? toPlain(snap.data()) : null;
      });
    }
    function allowedOrFalse(path) {
      // 探針：放行（文件不存在也算）＝true，被拒＝false
      return F.getDoc(F.doc(sdk.db, path)).then(function () { return true; }, function () { return false; });
    }
    var isGoogle = u.provider === 'google.com';
    return Promise.all([
      getOrNull(C.paths.allow(u.emailKey)).catch(function () { return null; }),
      getOrNull(C.paths.privateAllow(u.emailKey)).catch(function () { return null; }),
      isGoogle ? getOrNull(C.paths.parentMap(u.emailKey)).catch(function () { return null; }) : Promise.resolve(null),
      isGoogle ? allowedOrFalse(C.paths.teacherProbe()) : Promise.resolve(false)
    ]).then(function (r) {
      var allow = r[0];
      var priv = r[1];
      var map = r[2];
      var teacher = r[3] === true;
      if (!allow && !teacher) return { state: 'denied', user: u, roles: C.emptyRoles() };
      var seats = map && map.active === true && Array.isArray(map.seats) ? map.seats.filter(C.seats.valid) : [];
      var s = {
        state: 'ready',
        user: u,
        roles: {
          teacher: teacher,
          reader: !!allow,
          privateReader: teacher || (!!allow && !!priv),
          kind: allow ? allow.kind || null : (teacher ? 'teacher' : null),
          alias: allow ? allow.alias || null : null,
          seats: seats,
          seatKind: seats.length && map ? map.kind : null
        }
      };
      ssSet(SESSION_CACHE_KEY, JSON.stringify({ uid: u.uid, at: Date.now(), session: s }));
      return s;
    });
  };

  FirestoreStore.prototype.onSession = function (cb) {
    var self = this;
    this._subs.push(cb);
    cb(this._session);
    this._startAuth();
    return function () {
      var i = self._subs.indexOf(cb);
      if (i >= 0) self._subs.splice(i, 1);
    };
  };

  FirestoreStore.prototype.getSession = function () {
    return this._session;
  };

  /** Google 登入：先開小視窗；被擋就改用整頁轉址（同網域，ARCHITECTURE §3.4）。 */
  FirestoreStore.prototype.signInWithGoogle = function () {
    return this._ready().then(function (sdk) {
      var provider = new sdk.AU.GoogleAuthProvider();
      provider.setCustomParameters({ prompt: 'select_account' });
      return sdk.AU.signInWithPopup(sdk.auth, provider).then(function () { return undefined; }, function (err) {
        var code = err && err.code;
        if (code === 'auth/popup-blocked' || code === 'auth/operation-not-supported-in-environment' ||
            code === 'auth/web-storage-unsupported') {
          return sdk.AU.signInWithRedirect(sdk.auth, provider);
        }
        throw C.errors.from(err);
      });
    });
  };

  /** 寄登入連結（Spark 方案全專案每天 5 封；額度用完 → StoreError('quota')，source＝auth） */
  FirestoreStore.prototype.sendSignInLink = function (email) {
    var self = this;
    var key;
    try { key = C.emailKey(email); } catch (e) { return Promise.reject(invalid('信箱格式不對')); }
    return this._ready().then(function (sdk) {
      var base = String(self._cfg.siteUrl || g.location.origin).replace(/\/+$/, '');
      return sdk.AU.sendSignInLinkToEmail(sdk.auth, String(email).trim(), {
        url: base + '/index.html',
        handleCodeInApp: true
      }).then(function () {
        lsSet(EMAIL_FOR_LINK_KEY, String(email).trim());
        return key;
      }, function (err) { throw C.errors.from(err); });
    });
  };

  /** 網址是登入連結就完成登入。換裝置開信時本機沒有信箱 → StoreError('invalid','need-email')。 */
  FirestoreStore.prototype.completeSignInLink = function (email) {
    return this._ready().then(function (sdk) {
      var href = String(g.location.href);
      if (!sdk.AU.isSignInWithEmailLink(sdk.auth, href)) return false;
      var addr = email || lsGet(EMAIL_FOR_LINK_KEY);
      if (!addr) throw new C.StoreError('invalid', 'need-email');
      return sdk.AU.signInWithEmailLink(sdk.auth, String(addr).trim(), href).then(function () {
        lsDel(EMAIL_FOR_LINK_KEY);
        try {
          var clean = new URL(href);
          ['apiKey', 'oobCode', 'mode', 'lang', 'continueUrl', 'tenantId'].forEach(function (k) { clean.searchParams.delete(k); });
          g.history.replaceState(null, '', clean.pathname + clean.search + clean.hash);
        } catch (e) { /* 網址清不掉不影響登入 */ }
        return true;
      }, function (err) { throw C.errors.from(err); });
    });
  };

  /** 登出 → 清 Session 暫存 → 清本機的資料庫快取（共用電腦不留別人的資料）→ 重新載入 */
  FirestoreStore.prototype.signOut = function () {
    return this._ready().then(function (sdk) {
      ssDel(SESSION_CACHE_KEY);
      return sdk.AU.signOut(sdk.auth)
        .then(function () { return sdk.F.terminate(sdk.db); })
        .then(function () { return sdk.F.clearIndexedDbPersistence(sdk.db); })
        .catch(function () { /* 清不掉快取也照樣登出 */ })
        .then(function () { g.location.reload(); });
    });
  };

  // ── B. 通用讀取 ────────────────────────────────────
  FirestoreStore.prototype.get = function (path) {
    if (!C.paths.isDocPath(path)) return Promise.reject(invalid('文件路徑不對'));
    return this._ready().then(function (sdk) {
      return sdk.F.getDoc(sdk.F.doc(sdk.db, path)).then(function (snap) {
        return snap.exists() ? snapToDoc(snap) : null;
      }, function (err) { throw C.errors.from(err); });
    });
  };

  FirestoreStore.prototype.query = function (name, params, page) {
    var self = this;
    return this._ready().then(function (sdk) {
      var b = self._buildQuery(sdk, name, params, page, false);
      if (b.spec.count) throw invalid('這個查詢只能用 count：' + name);
      return sdk.F.getDocs(b.q).then(function (snap) { return toPage(snap, b.spec, b.limit); },
        function (err) { throw C.errors.from(err); });
    }).catch(function (err) { throw C.errors.from(err); });
  };

  FirestoreStore.prototype.watch = function (name, params, cb) {
    var self = this;
    C.queryEval.checkWatch(name);
    var stopped = false;
    var unsub = null;
    this._ready().then(function (sdk) {
      if (stopped) return;
      var b = self._buildQuery(sdk, name, params, null, false);
      unsub = sdk.F.onSnapshot(b.q, function (snap) { cb(toPage(snap, b.spec, b.limit)); },
        function (err) { cb(null, C.errors.from(err)); });
    }).catch(function (err) { cb(null, C.errors.from(err)); });
    return function () {
      stopped = true;
      if (unsub) unsub();
    };
  };

  FirestoreStore.prototype.count = function (name, params) {
    var self = this;
    return this._ready().then(function (sdk) {
      if (!C.queryEval.spec(name).count) throw invalid('這個查詢沒有登記 count：' + name);
      var b = self._buildQuery(sdk, name, params, null, true);
      return sdk.F.getCountFromServer(b.q).then(function (snap) { return snap.data().count; },
        function (err) { throw C.errors.from(err); });
    }).catch(function (err) { throw C.errors.from(err); });
  };

  // ── C. 通用寫入 ────────────────────────────────────
  FirestoreStore.prototype.add = function (collectionPath, data) {
    return this._ready().then(function (sdk) {
      if (!C.paths.isCollectionPath(collectionPath)) throw invalid('集合路徑不對');
      C.validate.write('add', collectionPath, data);
      return sdk.F.addDoc(sdk.F.collection(sdk.db, collectionPath), prepare(sdk.F, data))
        .then(function (ref) { return ref.id; }, function (err) { throw C.errors.from(err); });
    }).catch(function (err) { throw C.errors.from(err); });
  };

  FirestoreStore.prototype.set = function (path, data) {
    return this._ready().then(function (sdk) {
      if (!C.paths.isDocPath(path)) throw invalid('文件路徑不對');
      C.validate.write('set', path, data);
      return sdk.F.setDoc(sdk.F.doc(sdk.db, path), prepare(sdk.F, data));
    }).catch(function (err) { throw C.errors.from(err); });
  };

  FirestoreStore.prototype.update = function (path, patch) {
    return this._ready().then(function (sdk) {
      if (!C.paths.isDocPath(path)) throw invalid('文件路徑不對');
      C.validate.write('update', path, patch);
      return sdk.F.updateDoc(sdk.F.doc(sdk.db, path), prepare(sdk.F, patch));
    }).catch(function (err) { throw C.errors.from(err); });
  };

  /** 1–7 個寫入，一次成功或一次失敗（DATA-MODEL §1.6） */
  FirestoreStore.prototype.batch = function (ops) {
    return this._ready().then(function (sdk) {
      C.validate.batch(ops);
      var wb = sdk.F.writeBatch(sdk.db);
      ops.forEach(function (o) {
        if (!C.paths.isDocPath(o.path)) throw invalid('文件路徑不對');
        var ref = sdk.F.doc(sdk.db, o.path);
        if (o.op === 'set') wb.set(ref, prepare(sdk.F, o.data));
        else wb.update(ref, prepare(sdk.F, o.data));
      });
      return wb.commit();
    }).catch(function (err) { throw C.errors.from(err); });
  };

  // ── D. 語意方法 ────────────────────────────────────
  /** 照片文件不可變：先查本機快取、沒有才上網；驗 base64 字元集；MIME 寫死 image/jpeg。 */
  FirestoreStore.prototype.photoSrc = function (ownerPath, pid, size) {
    var self = this;
    var path;
    try {
      path = size === 'image' ? C.paths.image(ownerPath, pid) : C.paths.thumb(ownerPath, pid);
    } catch (e) {
      return Promise.resolve(null);
    }
    if (this._photoMemo[path]) return this._photoMemo[path];
    var max = size === 'image' ? 716800 : 49152;
    this._photoMemo[path] = this._ready().then(function (sdk) {
      var ref = sdk.F.doc(sdk.db, path);
      return sdk.F.getDocFromCache(ref).catch(function () { return sdk.F.getDoc(ref); }).then(function (snap) {
        if (!snap || !snap.exists()) return null;
        var data = snap.get('data');
        if (typeof data !== 'string' || !data || data.length > max || !B64_RE.test(data)) return null;
        return 'data:image/jpeg;base64,' + data;
      });
    }).catch(function () {
      delete self._photoMemo[path];
      return null;
    });
    return this._photoMemo[path];
  };

  /** 開過那一頁＝已讀。導師不寫回條；先 get 自己那份，找不到才建；兩個分頁同時建的被拒只在這裡吞掉。 */
  FirestoreStore.prototype.markRead = function (threadPath) {
    var s = this._session;
    if (!s || s.state !== 'ready' || s.roles.teacher || !s.user || !s.user.emailKey) return Promise.resolve();
    var kind = s.roles.kind;
    if (kind !== 'parent' && kind !== 'staff') return Promise.resolve();
    var path;
    try { path = C.paths.receipt(threadPath, s.user.emailKey); } catch (e) { return Promise.reject(e); }
    var self = this;
    return this.get(path).then(function (doc) {
      if (doc) return undefined;
      return self.set(path, { kind: kind, readAt: C.SERVER_TIME }).catch(function (err) {
        if (C.errors.from(err).code === 'denied') return undefined; // 另一個分頁剛建好
        throw err;
      });
    });
  };

  FirestoreStore.prototype.newPostId = function (date) {
    return C.util.newPostId(date);
  };

  // ── E. 示範模式專用：真站一律 invalid ─────────────────
  FirestoreStore.prototype.demoSetRole = function () {
    throw invalid('只有示範模式能切換角色');
  };
  FirestoreStore.prototype.demoReset = function () {
    throw invalid('只有示範模式能清除示範資料');
  };

  C.FirestoreStore = FirestoreStore;
  C.FirestoreStore.SDK_VERSION = SDK_VERSION;
})(typeof window !== 'undefined' ? window : globalThis);
