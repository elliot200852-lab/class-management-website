/* query-eval.js — 照 CMW.QUERIES 登記的形狀，在記憶體裡跑查詢（示範模式用；前端排序兩邊共用）。

   跟真站吃同一份登記表（templates/queries.json → site/js/core/queries.js），所以示範模式一樣會擋
   「沒登記的查詢名」、一樣只能把 limit 調小。語意照 Firestore：
     · where 只支援 ==、<、<=、>、>=；型別不同一律不相等、不比大小
     · orderBy 的欄位不存在的文件不會出現在結果裡
     · 同值時以文件路徑排序（方向跟最後一個 orderBy 一樣）
     · startAfter／endBefore 用游標文件的排序值比；limitToLast 取最後 n 筆
     · sortClient 在取回後排（真站也用這裡的 sortClient） */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  function invalid(msg) { return new C.StoreError('invalid', msg); }

  function spec(name) {
    var Q = C.QUERIES || {};
    if (typeof name !== 'string' || !Object.prototype.hasOwnProperty.call(Q, name)) {
      throw invalid('沒有登記的查詢名：' + name);
    }
    return Q[name];
  }

  /** 登記的 path 代換 {參數} → 集合路徑；group 查詢回 { group }。 */
  function target(s, params) {
    if (s.group) return { group: s.group };
    var missing = null;
    var path = s.path.replace(/\{([a-zA-Z]+)\}/g, function (all, k) {
      var v = params ? params[k] : undefined;
      if (typeof v !== 'string' || !v) { missing = k; return ''; }
      return v;
    });
    if (missing) throw invalid('查詢少了路徑參數：' + missing);
    if (!C.paths.isCollectionPath(path)) throw invalid('查詢路徑不對');
    if (s.path.indexOf('{thread}') >= 0) C.paths.checkThread(params.thread);
    if (s.path.indexOf('{owner}') >= 0) C.paths.checkOwner(params.owner);
    if (s.path.indexOf('{entry}') >= 0) C.paths.checkEntry(params.entry);
    if (s.path.indexOf('{seat}') >= 0 && !C.seats.valid(params.seat)) throw invalid('座號格式不對');
    return { path: path };
  }

  /** where 的值：常數，或 ':參數' */
  function whereValue(v, params) {
    if (typeof v === 'string' && v.charAt(0) === ':') {
      var k = v.slice(1);
      if (!params || params[k] === undefined) throw invalid('查詢少了參數：' + k);
      return params[k];
    }
    return v;
  }

  function limitOf(s, params) {
    var lim = s.limit;
    if (params && params.limit !== undefined) {
      var l = params.limit;
      if (typeof l !== 'number' || Math.floor(l) !== l || l < 1 || l > s.limit) {
        throw invalid('limit 只能比登記的（' + s.limit + '）小');
      }
      lim = l;
    }
    return lim;
  }

  // ── 比較（Firestore 的型別順序：null < 布林 < 數字 < 時間 < 字串） ──
  function typeRank(v) {
    if (v === null || v === undefined) return 0;
    if (typeof v === 'boolean') return 1;
    if (typeof v === 'number') return 2;
    if (v instanceof Date) return 3;
    if (typeof v === 'string') return 4;
    return 5;
  }

  function cmp(a, b) {
    var ta = typeRank(a);
    var tb = typeRank(b);
    if (ta !== tb) return ta < tb ? -1 : 1;
    if (ta === 0) return 0;
    if (ta === 3) { a = a.getTime(); b = b.getTime(); }
    if (ta === 1) { a = a ? 1 : 0; b = b ? 1 : 0; }
    return a < b ? -1 : (a > b ? 1 : 0);
  }

  function sameType(a, b) { return typeRank(a) === typeRank(b); }

  function get(data, field) {
    return data ? data[field] : undefined;
  }

  function has(data, field) {
    return !!data && Object.prototype.hasOwnProperty.call(data, field);
  }

  function matchWhere(data, w, params) {
    var field = w[0];
    var op = w[1];
    var val = whereValue(w[2], params);
    if (!has(data, field)) return false;
    var v = get(data, field);
    if (!sameType(v, val)) return false;
    var c = cmp(v, val);
    switch (op) {
      case '==': return c === 0;
      case '<': return c < 0;
      case '<=': return c <= 0;
      case '>': return c > 0;
      case '>=': return c >= 0;
    }
    throw invalid('不支援的條件：' + op);
  }

  /** 同集合：路徑是 <集合路徑>/<id>；集合群組：倒數第二段是群組名 */
  function inTarget(docPath, t) {
    var segs = docPath.split('/');
    if (t.group) return segs.length >= 2 && segs.length % 2 === 0 && segs[segs.length - 2] === t.group;
    return docPath.indexOf(t.path + '/') === 0 && segs.length === t.path.split('/').length + 1;
  }

  function orderKeyCmp(order) {
    var lastDir = order.length ? order[order.length - 1][1] : 'asc';
    return function (a, b) {
      for (var i = 0; i < order.length; i++) {
        var c = cmp(get(a.data, order[i][0]), get(b.data, order[i][0]));
        if (c !== 0) return order[i][1] === 'desc' ? -c : c;
      }
      var p = a.path < b.path ? -1 : (a.path > b.path ? 1 : 0);
      return lastDir === 'desc' ? -p : p;
    };
  }

  /** 前端排序（登記表的 sortClient）；欄位不存在的排最後。穩定排序。 */
  function sortClient(items, rules) {
    if (!rules || !rules.length) return items;
    var indexed = items.map(function (it, i) { return { it: it, i: i }; });
    indexed.sort(function (x, y) {
      for (var r = 0; r < rules.length; r++) {
        var f = rules[r][0];
        var hx = has(x.it.data, f);
        var hy = has(y.it.data, f);
        if (hx !== hy) return hx ? -1 : 1;
        var c = cmp(get(x.it.data, f), get(y.it.data, f));
        if (c !== 0) return rules[r][1] === 'desc' ? -c : c;
      }
      return x.i - y.i;
    });
    return indexed.map(function (x) { return x.it; });
  }

  /** docs：[{ path, data }] → 符合形狀的清單（尚未套 limit）。 */
  function filterSort(docs, s, params) {
    var t = target(s, params);
    var where = s.where || [];
    var order = s.orderBy || [];
    var out = docs.filter(function (d) {
      if (!inTarget(d.path, t)) return false;
      for (var i = 0; i < where.length; i++) if (!matchWhere(d.data, where[i], params)) return false;
      for (var j = 0; j < order.length; j++) if (!has(d.data, order[j][0])) return false;
      return true;
    });
    if (order.length) {
      out.sort(orderKeyCmp(order));
    } else {
      out.sort(function (a, b) { return a.path < b.path ? -1 : (a.path > b.path ? 1 : 0); });
    }
    return out;
  }

  /** 跑一個查詢。docs：[{ path, data }]；page：{ after: 游標文件 } 或 { before: 游標文件 }。
      回傳 { items: [{ path, data }], next: 最後一筆或 null } */
  function run(docs, name, params, page) {
    var s = spec(name);
    if (s.count) throw invalid('這個查詢只能用 count：' + name);
    params = params || {};
    var lim = limitOf(s, params);
    var list = filterSort(docs, s, params);
    var order = s.orderBy || [];
    if (page && (page.after || page.before)) {
      if (!s.cursor) throw invalid('這個查詢沒有登記游標：' + name);
      var cur = page.after || page.before;
      if (!cur || typeof cur.path !== 'string') throw invalid('游標不對');
      var kc = orderKeyCmp(order);
      if (page.after) {
        if (s.cursor !== 'startAfter') throw invalid('這個查詢的游標是 ' + s.cursor);
        list = list.filter(function (d) { return kc(d, cur) > 0; });
      } else {
        if (s.cursor !== 'endBefore') throw invalid('這個查詢的游標是 ' + s.cursor);
        list = list.filter(function (d) { return kc(d, cur) < 0; });
      }
    }
    var items = s.limitToLast ? list.slice(Math.max(0, list.length - lim)) : list.slice(0, lim);
    if (s.sortClient) items = sortClient(items, s.sortClient);
    var next = !s.limitToLast && items.length === lim && list.length > 0 ? items[items.length - 1] : null;
    return { items: items, next: next };
  }

  function count(docs, name, params) {
    var s = spec(name);
    if (!s.count) throw invalid('這個查詢沒有登記 count：' + name);
    return filterSort(docs, s, params || {}).length;
  }

  function checkWatch(name) {
    if (!spec(name).watch) throw invalid('這個查詢沒有登記即時更新：' + name);
  }

  C.queryEval = {
    spec: spec,
    target: target,
    limitOf: limitOf,
    whereValue: whereValue,
    run: run,
    count: count,
    checkWatch: checkWatch,
    sortClient: sortClient,
    cmp: cmp
  };
})(typeof window !== 'undefined' ? window : globalThis);
