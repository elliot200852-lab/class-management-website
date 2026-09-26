// 咬人檢查（突變測試）：把規則裡幾個關鍵的判斷各拿掉一個，確認對應的測試會跟著翻盤。
// 翻不了盤＝那個測試是擺好看的（不管規則寫對寫錯它都過），這一段就失敗。
// 每個突變點都要在規則原文裡找得到；規則改寫過、找不到了，這一段也會失敗，提醒同步更新。
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  addDoc, collection, doc, getDoc, getDocs, query, serverTimestamp, setDoc, where,
} from 'firebase/firestore';
import { assert } from '../lib/harness.mjs';
import { AT, ENTRY, SLUG } from '../lib/world.mjs';
import { commentFor } from './threads.mjs';
import { entryFor } from './blogs.mjs';

function mutants(vec) {
  return [
    {
      name: '座號權限不看名單（hasSeat 的 isReader() 換成 verified()）',
      find: 'return isReader() && isGoogle()\n        && seatGrants(',
      replace: 'return verified() && isGoogle()\n        && seatGrants(',
      label: '被移出名單的家長讀部落格主頁',
      probe: (W) => getDoc(doc(W.db('removed'), 'student_blogs', '01')),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '紀事列表不看 visible',
      find: 'allow list: if isTeacher() || (isReader() && resource.data.visible == true);',
      replace: 'allow list: if isTeacher() || isReader();',
      label: '班網讀者不帶條件查紀事',
      probe: (W) => getDocs(collection(W.db('reader'), 'posts')),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '下架的紀事 get 不擋',
      find: 'allow get: if isTeacher() || (isReader() && (resource == null || resource.data.visible == true));',
      replace: 'allow get: if isTeacher() || isReader();',
      label: '班網讀者讀下架的紀事',
      probe: (W) => getDoc(doc(W.db('reader'), 'posts', SLUG.postHidden)),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '留言不看父文件可見',
      find: '(ticket && visibleDoc(parent))',
      replace: 'ticket',
      label: '班網讀者在下架的紀事底下留言',
      probe: (W) => addDoc(collection(W.db('reader'), `posts/${SLUG.postHidden}/comments`), commentFor(W, 'reader')),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '留言不驗作者代號',
      find: "        && d.authorAlias == me.data.get('alias', '')\n        && d.status == 'visible'",
      replace: "        && d.status == 'visible'",
      label: '班網讀者冒用座號家長的代號留言',
      probe: (W) => addDoc(collection(W.db('reader'), `posts/${SLUG.post}/comments`),
        commentFor(W, 'reader', { authorAlias: W.alias('parent') })),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '導師不必 Google 登入',
      find: 'return verified() && isGoogle() && emailKey() ==',
      replace: 'return verified() && emailKey() ==',
      label: 'email 連結登入的導師信箱讀名冊',
      probe: (W) => getDoc(doc(W.db('teacherLink'), 'roster', 'students')),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '私密門票不必 Google 登入（H1）',
      find: 'return isTeacher() || (isReader() && isGoogle()\n        && exists(',
      replace: 'return isTeacher() || (isReader()\n        && exists(',
      label: '預先註冊的密碼帳號（在私密名單）讀私密紀事',
      probe: (W) => getDoc(doc(W.db('linkPrivate'), 'private_posts', SLUG.priv)),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '留言不必 Google 登入（H1）',
      find: 'return isGoogle()\n        && ((isTeacher() && parent != null)',
      replace: 'return true\n        && ((isTeacher() && parent != null)',
      label: 'email 連結登入的名單者在紀事底下留言',
      probe: (W) => addDoc(collection(W.db('emailLink'), `posts/${SLUG.post}/comments`), commentFor(W, 'emailLink')),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '回條不必 Google 登入（H1）',
      find: '        && isGoogle()\n        && key == emailKey()\n',
      replace: '        && key == emailKey()\n',
      label: 'email 連結登入的名單者簽紀事回條',
      probe: (W) => setDoc(doc(W.db('emailLink'), `posts/${SLUG.post2}/reads/${W.key('emailLink')}`),
        { kind: 'parent', readAt: serverTimestamp() }),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '部落格文章日期不綁 postId（L1）',
      find: '            && d.date == postId[0:10]\n',
      replace: '',
      label: '座號家長把文章日期填到未來',
      probe: (W) => setDoc(doc(W.db('parent'), 'student_blogs/01/entries/2026-09-20-canary01'),
        entryFor(W, 'parent', { date: '2099-12-31' })),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '對話串開給同仁（isParentOf 換成 isSeatReaderOf）',
      find: "allow list: if isTeacher()\n            || (isParentOf(seat) && visibleDoc(entryDoc()) && resource.data.status == 'visible');",
      replace: "allow list: if isTeacher()\n            || (isSeatReaderOf(seat) && visibleDoc(entryDoc()) && resource.data.status == 'visible');",
      label: '同仁查對話串',
      probe: (W) => getDocs(query(collection(W.db('staff'), `student_blogs/01/entries/${ENTRY.e01}/blog_comments`),
        where('status', '==', 'visible'))),
      real: 'deny', mutant: 'allow',
    },
    {
      name: '回條不驗 doc id 是自己',
      find: '        && key == emailKey()\n',
      replace: '',
      label: '班網讀者替座號家長簽回條',
      probe: (W) => setDoc(doc(W.db('reader'), `posts/${SLUG.post2}/reads/${W.key('parent')}`),
        { kind: 'parent', readAt: serverTimestamp() }),
      real: 'deny', mutant: 'allow',
    },
    {
      name: 'gmail 不去點號',
      find: "? parts[0].replace('[.]', '') + '@gmail.com'",
      replace: "? parts[0] + '@gmail.com'",
      label: `gmail 點號寫法登入的名單者讀 config/site（向量：${vec.why}）`,
      seed: async (W) => W.admin((db) => setDoc(doc(db, 'allowlist', vec.out.join(AT)), { kind: 'parent', alias: 'vectoralias9' })),
      probe: (W) => getDoc(doc(W.dbFor('canary-gmail', { email: vec.in.join(AT), verified: true }), 'config', 'site')),
      real: 'allow', mutant: 'deny',
    },
  ];
}

export async function run(S, W, { repoRoot, rules }) {
  const vectors = JSON.parse(readFileSync(join(repoRoot, 'tests', 'fixtures', 'emailkey_vectors.json'), 'utf8'));
  const vec = vectors.valid.find((v) => v.in[1] === 'gmail.com' && v.in[0] !== v.out[0]);

  S.section('咬人檢查：拿掉關鍵判斷，對應的測試必須翻盤（突變測試）');
  try {
    for (const m of mutants(vec)) {
      const count = rules.split(m.find).length - 1;
      const found = await S.check(`突變點在規則原文裡找得到（${m.name}）`, async () => {
        assert(count >= 1, '找不到——規則改寫過了，請同步更新 suites/canaries.mjs');
      });
      if (!found) continue;
      await W.start(rules);
      await W.reset();
      if (m.seed) await m.seed(W);
      await S.expect(m.real, `真規則：${m.label}`, () => m.probe(W));
      await W.start(rules.replace(m.find, m.replace));
      await W.reset();
      if (m.seed) await m.seed(W);
      await S.expect(m.mutant, `突變後（${m.name}）：${m.label}`, () => m.probe(W));
    }
  } finally {
    await W.start(rules);
  }
}
