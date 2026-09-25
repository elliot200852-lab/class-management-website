/* read-stats.js — 「已讀 X/N」的判準，全站只有這一份（docs/DATA-MODEL.md §2.8）。

   班級紀事：N＝parent_child_map 裡 kind == 'parent' 且 active 的 email 數；
             X＝回條 doc id 落在這批 email 裡的數量（同一個 email 多台裝置只算一次；同仁與導師不算）。
             單篇頁用 reads.all 精算；列表卡片用 reads.countParents 近似。
   私密紀事：N＝private_allowlist 人數減掉導師；X＝回條數（reads.count）。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  /** parentMap.all 的結果 → 純家長 email 鍵的集合 */
  function parentKeys(mapDocs) {
    var set = {};
    (mapDocs || []).forEach(function (d) {
      var x = d && d.data;
      if (x && x.kind === 'parent' && x.active === true) set[d.id] = true;
    });
    return set;
  }

  function size(set) { return Object.keys(set).length; }

  /** 單篇紀事：reads.all 的結果＋純家長集合 → { x, n, readKeys } */
  function postStats(readDocs, keys) {
    var seen = {};
    (readDocs || []).forEach(function (d) {
      if (d && keys[d.id]) seen[d.id] = true;
    });
    return { x: size(seen), n: size(keys), readKeys: seen };
  }

  /** 列表卡片：家長回條數（reads.countParents）＋純家長集合 → { x, n }（近似：x 不超過 n） */
  function cardStats(parentReadCount, keys) {
    var n = size(keys);
    return { x: Math.min(parentReadCount || 0, n), n: n };
  }

  /** 私密紀事：回條數（reads.count）＋私密名單（privateAllowlist.all）＋導師 email 鍵 → { x, n } */
  function privateStats(readCount, privateAllowDocs, teacherKey) {
    var n = (privateAllowDocs || []).filter(function (d) { return d && d.id !== teacherKey; }).length;
    return { x: Math.min(readCount || 0, n), n: n };
  }

  function label(st) {
    return '已讀 ' + st.x + '/' + st.n;
  }

  C.readStats = {
    parentKeys: parentKeys,
    postStats: postStats,
    cardStats: cardStats,
    privateStats: privateStats,
    label: label
  };
})(typeof window !== 'undefined' ? window : globalThis);
