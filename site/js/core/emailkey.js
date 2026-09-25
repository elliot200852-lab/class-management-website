/* emailkey.js — email 正規化成「email 鍵」（docs/DATA-MODEL.md §0.3）。

   跟 scripts/lib/emailkey.py、安全規則的 emailKey() 是同一套規則，三邊共用測試向量
   tests/fixtures/emailkey_vectors.json：
     1. 前後空白去掉、全部轉小寫
     2. 剛好一個 @，前後都不能空；字元集只收英數與 . _ % + -（擋引號、反斜線、空白、非 ASCII）
     3. gmail.com／googlemail.com：@ 前面的點號全部拿掉，網域統一 gmail.com
     4. 其他網域點號照留；「+」後綴照留
   前端拿它來讀「自己的名單文件」與回條的 doc id。 */
(function (g) {
  'use strict';
  var C = g.CMW = g.CMW || {};

  var EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
  var GMAIL = ['gmail.com', 'googlemail.com'];

  /** 不合法就丟 Error（訊息不含原字串，避免把信箱印進主控台）。 */
  function emailKey(raw) {
    if (typeof raw !== 'string') throw new Error('email 必須是文字');
    var e = raw.trim().toLowerCase();
    if (e.split('@').length !== 2) throw new Error('email 必須剛好有一個 @');
    var parts = e.split('@');
    var local = parts[0];
    var domain = parts[1];
    if (!local || !domain) throw new Error('email 的 @ 前後都不能是空的');
    if (!EMAIL_RE.test(e)) throw new Error('email 含有不允許的字元或格式不對');
    if (GMAIL.indexOf(domain) >= 0) {
      local = local.replace(/\./g, '');
      if (!local) throw new Error('gmail 信箱去掉點號後是空的');
      domain = 'gmail.com';
    }
    return local + '@' + domain;
  }

  C.emailKey = emailKey;
  C.emailKey.isValid = function (raw) {
    try { emailKey(raw); return true; } catch (e) { return false; }
  };
  C.emailKey.EMAIL_RE = EMAIL_RE;
})(typeof window !== 'undefined' ? window : globalThis);
