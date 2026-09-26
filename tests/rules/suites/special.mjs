// DATA-MODEL 附錄 A 最後那張「必測清單」裡，權限表逐格測不到的部分：
// email 鍵向量（規則端與 Python 同一套）、「找不到」與「被拒」、撤名單立即生效、部落格發文批次。
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  collection, deleteDoc, doc, getDoc, getDocs, query, serverTimestamp, setDoc, where, writeBatch,
} from 'firebase/firestore';
import { assert } from '../lib/harness.mjs';
import { AT, ENTRY, SLUG } from '../lib/world.mjs';
import { blogCommentFor, entryFor, IMAGE, THUMB } from './blogs.mjs';
import { commentFor } from './threads.mjs';

const google = (email, extra = {}) => ({ email, verified: true, provider: 'google.com', ...extra });

async function expectCode(label, S, fn, code) {
  await S.check(label, async () => {
    try {
      await fn();
    } catch (e) {
      assert(e.code === code, `錯誤碼是 ${e.code}，預期 ${code}`);
      return;
    }
    throw new Error(`預期錯誤碼 ${code}，結果成功了`);
  });
}

export async function run(S, W, { repoRoot }) {
  const vectors = JSON.parse(readFileSync(join(repoRoot, 'tests', 'fixtures', 'emailkey_vectors.json'), 'utf8'));

  S.section('email 鍵：共用向量（tests/fixtures/emailkey_vectors.json；規則端與 Python 一致）');
  await W.reset();
  // 合法向量：用「登入時的寫法」登入，名單文件放在「Python 算出來的鍵」上 → 必須對得上
  await W.admin(async (db) => {
    for (const v of vectors.valid) {
      await setDoc(doc(db, 'allowlist', v.out.join(AT)), { kind: 'parent', alias: 'vectoralias1', updatedAt: serverTimestamp() });
    }
  });
  let i = 0;
  for (const v of vectors.valid) {
    i += 1;
    const db = W.dbFor(`vec${i}`, google(v.in.join(AT)));
    await S.expect('found', `讀得到自己的名單文件：${v.why}`, () => getDoc(doc(db, 'allowlist', v.out.join(AT))));
    await S.expect('found', `是班網讀者（讀 config/site）：${v.why}`, () => getDoc(doc(db, 'config', 'site')));
  }
  // 沒有正規化就對不上：gmail 名單文件若誤存成「照登入寫法小寫」的鍵，規則不會去找它
  await W.reset();
  const rawKeyOnly = vectors.valid.filter((v) => v.in.join(AT).trim().toLowerCase() !== v.out.join(AT));
  await W.admin(async (db) => {
    for (const v of rawKeyOnly) {
      await setDoc(doc(db, 'allowlist', v.in.join(AT).trim().toLowerCase()), { kind: 'parent', alias: 'vectoralias2' });
    }
  });
  for (const v of rawKeyOnly) {
    i += 1;
    const db = W.dbFor(`raw${i}`, google(v.in.join(AT)));
    await S.expect('deny', `名單文件用沒正規化的鍵就對不上：${v.why}`, () => getDoc(doc(db, 'config', 'site')));
  }
  // 非 gmail 網域少一個點就是另一個信箱
  await W.admin((db) => setDoc(doc(db, 'allowlist', 'parent.dot@example.com'), { kind: 'parent', alias: 'vectoralias3' }));
  await S.expect('deny', '非 gmail 網域：少一個點就對不上', () => getDoc(doc(W.dbFor('nodot', google('parentdot' + AT + 'example.com')), 'config', 'site')));
  await S.expect('found', '非 gmail 網域：大小寫不同照樣對得上',
    () => getDoc(doc(W.dbFor('updot', google('PARENT.DOT' + AT + 'EXAMPLE.COM')), 'config', 'site')));
  // 不合法向量：Python 拒收的信箱，規則也不當成已驗證的身分（就算名單裡剛好有一份「照字面」的文件）
  for (const v of vectors.invalid) {
    i += 1;
    const raw = v.in.join(v.join === undefined ? AT : v.join);
    const naive = raw.trim().toLowerCase();
    // 名單裡放一份「照字面」的文件；gmail 那種再放一份「去掉點號後」的（例如只剩 @ 後面）
    const candidates = new Set([naive, naive.replace(/^[^@]*@/, (m) => m.replace(/[.]/g, ''))]);
    for (const c of candidates) {
      if (c && !c.includes('/')) {
        await W.admin((db) => setDoc(doc(db, 'allowlist', c), { kind: 'parent', alias: 'vectoralias4' }));
      }
    }
    const db = W.dbFor(`bad${i}`, google(raw));
    await S.expect('deny', `不合法的信箱不算讀者：${v.why}`, () => getDoc(doc(db, 'config', 'site')));
  }

  S.section('「找不到」與「被拒」（§1.5）');
  await W.reset();
  const code = 'permission-denied';
  await expectCode('班網讀者 get 下架的紀事 → permission-denied（前端顯示「這篇找不到（可能已下架）」）', S,
    () => getDoc(doc(W.db('reader'), 'posts', SLUG.postHidden)), code);
  await S.expect('notfound', '班網讀者 get 不存在的紀事 → 找不到（exists() == false）',
    () => getDoc(doc(W.db('reader'), 'posts', SLUG.postMissing)));
  await expectCode('非名單登入者 get 不存在的紀事 → permission-denied（沒門票就不說有沒有）', S,
    () => getDoc(doc(W.db('outsider'), 'posts', SLUG.postMissing)), code);
  await expectCode('班網讀者 get 不存在的私密紀事 → permission-denied（不洩漏有沒有這一篇）', S,
    () => getDoc(doc(W.db('reader'), 'private_posts', SLUG.privMissing)), code);
  await S.expect('notfound', '私密讀者 get 不存在的私密紀事 → 找不到',
    () => getDoc(doc(W.db('private'), 'private_posts', SLUG.privMissing)));
  await expectCode('座號家長 get 下架的部落格文章 → permission-denied', S,
    () => getDoc(doc(W.db('parent'), `student_blogs/01/entries/${ENTRY.e01Hidden}`)), code);
  await S.expect('notfound', '導師 get 不存在的紀事 → 找不到', () => getDoc(doc(W.db('teacher'), 'posts', SLUG.postMissing)));

  S.section('撤名單立即生效（§1.1、§0.5）');
  await W.reset();
  const pdb = W.db('parent');
  const entryPath = `student_blogs/01/entries/${ENTRY.e01}`;
  await S.expect('found', '撤之前：座號家長讀得到部落格主頁', () => getDoc(doc(pdb, 'student_blogs', '01')));
  await S.expect('found', '撤之前：讀得到文章', () => getDoc(doc(pdb, entryPath)));
  await W.admin((db) => deleteDoc(doc(db, 'allowlist', W.key('parent'))));
  await S.check('撤掉 allowlist 後 parent_child_map 還在（只撤了名單）', async () => {
    let exists = false;
    await W.admin(async (db) => { exists = (await getDoc(doc(db, 'parent_child_map', W.key('parent')))).exists(); });
    assert(exists, 'parent_child_map 被刪了，這個測試就沒意義');
  });
  await S.expect('deny', '撤之後：部落格主頁被拒', () => getDoc(doc(pdb, 'student_blogs', '01')));
  await S.expect('deny', '撤之後：文章被拒', () => getDoc(doc(pdb, entryPath)));
  await S.expect('deny', '撤之後：文章列表被拒',
    () => getDocs(query(collection(pdb, 'student_blogs/01/entries'), where('visible', '==', true))));
  await S.expect('deny', '撤之後：照片被拒', () => getDoc(doc(pdb, `${entryPath}/thumbs/0`)));
  await S.expect('deny', '撤之後：對話串被拒',
    () => getDocs(query(collection(pdb, `${entryPath}/blog_comments`), where('status', '==', 'visible'))));
  await S.expect('deny', '撤之後：發文被拒',
    () => setDoc(doc(pdb, 'student_blogs/01/entries/2026-09-22-revoked1'), entryFor(W, 'parent', { date: '2026-09-22' })));
  await S.expect('deny', '撤之後：對話被拒',
    () => setDoc(doc(pdb, `${entryPath}/blog_comments/x1`), blogCommentFor(W, 'parent')));
  await S.expect('deny', '撤之後：班網一般頁也被拒', () => getDoc(doc(pdb, 'config', 'site')));
  await S.expect('deny', '撤之後：自己的 parent_child_map 也讀不到', () => getDoc(doc(pdb, 'parent_child_map', W.key('parent'))));
  await W.admin((db) => setDoc(doc(db, 'parent_child_map', W.key('parent')), { active: false }, { merge: true }));
  await W.admin((db) => setDoc(doc(db, 'allowlist', W.key('parent')), { kind: 'parent', alias: 'parentalias1' }));
  await S.expect('deny', '加回名單但座號對應暫停（active=false）：部落格照樣被拒', () => getDoc(doc(pdb, 'student_blogs', '01')));
  await S.expect('found', '加回名單但座號對應暫停：班網一般頁恢復', () => getDoc(doc(pdb, 'config', 'site')));
  // 私密名單：撤掉 private_allowlist，私密紀事與私密回條立刻失效
  const prdb = W.db('private');
  await S.expect('found', '撤之前：私密讀者讀得到私密紀事', () => getDoc(doc(prdb, 'private_posts', SLUG.priv)));
  await W.admin((db) => deleteDoc(doc(db, 'private_allowlist', W.key('private'))));
  await S.expect('deny', '撤掉 private_allowlist 後：私密紀事被拒', () => getDoc(doc(prdb, 'private_posts', SLUG.priv)));
  await S.expect('deny', '撤掉 private_allowlist 後：私密回條寫不進去',
    () => setDoc(doc(prdb, `private_posts/${SLUG.priv2}/reads/${W.key('private')}`), { kind: 'parent', readAt: serverTimestamp() }));
  await S.expect('allow', '撤掉 private_allowlist 後：一般紀事的回條照樣能寫（兩張門票分開）',
    () => setDoc(doc(prdb, `posts/${SLUG.post2}/reads/${W.key('private')}`), { kind: 'parent', readAt: serverTimestamp() }));

  S.section('部落格發文批次（§2.14：1 篇文章＋3 縮圖＋3 顯示圖，一次成功或一次失敗）');
  await W.reset();
  const batchFor = (db, seat, postId, author, { badPhoto = false } = {}) => {
    const b = writeBatch(db);
    const base = `student_blogs/${seat}/entries/${postId}`;
    b.set(doc(db, base), entryFor(W, author, {
      date: postId.slice(0, 10),
      photos: [0, 1, 2].map((k) => ({ pid: String(k), w: 1280, h: 960, caption: `第 ${k + 1} 張` })),
    }));
    for (const k of [0, 1, 2]) {
      b.set(doc(db, `${base}/thumbs/${k}`), { ...THUMB, order: k, ...(badPhoto && k === 2 ? { w: 9999 } : {}) });
      b.set(doc(db, `${base}/images/${k}`), IMAGE);
    }
    return b.commit();
  };
  const P1 = '2026-09-23-batch001';
  await S.expect('allow', '座號家長送出 7 個寫入的批次（座號 01）', () => batchFor(pdb, '01', P1, 'parent'));
  await S.expect('deny', '同一個 postId 再送一次（等於改）→ 被拒；重試要換新 postId', () => batchFor(pdb, '01', P1, 'parent'));
  await S.expect('allow', '換新 postId 重送 → 成功', () => batchFor(pdb, '01', '2026-09-23-batch002', 'parent'));
  await S.expect('deny', '批次裡有一張照片不合格 → 整批被拒', () => batchFor(pdb, '01', '2026-09-23-batch003', 'parent', { badPhoto: true }));
  await S.check('整批被拒時文章也沒有被寫進去（原子性）', async () => {
    let exists = true;
    await W.admin(async (db) => { exists = (await getDoc(doc(db, 'student_blogs/01/entries/2026-09-23-batch003'))).exists(); });
    assert(!exists, '被拒的批次留下了半篇文章');
  });
  await S.expect('deny', '座號家長對別人的座號（02）送批次', () => batchFor(pdb, '02', '2026-09-23-batch004', 'parent'));
  await S.expect('deny', '同仁送批次（只能讀、不能發）', () => batchFor(W.db('staff'), '01', '2026-09-23-batch005', 'staff'));
  await S.expect('deny', 'email 連結登入的家長送批次（不是 Google 登入）',
    () => batchFor(W.db('emailLink'), '01', '2026-09-23-batch006', 'emailLink'));
  await S.expect('allow', '導師對任何座號送批次（座號 02）', () => batchFor(W.db('teacher'), '02', '2026-09-23-batch007', 'teacher'));
  await S.expect('found', '批次寫完，座號家長讀得到自己那篇的第 3 張顯示圖',
    () => getDoc(doc(pdb, `student_blogs/01/entries/${P1}/images/2`)));

  // H1：規則分不出 email 連結與密碼登入（兩者 sign_in_provider 都是 'password'）。任何人都能拿一位還沒登入過的家長信箱
  // 預先註冊密碼帳號，家長點了驗證信，這個帳號就 email_verified=true。所以 password 登入只給「讀公開內容」。
  S.section('預先註冊的密碼帳號（§1.1：password 登入只能讀公開內容）');
  await W.reset();
  const ldb = W.db('linkPrivate');
  await S.expect('found', 'password 登入、已驗證、在名單：讀得到公開紀事', () => getDoc(doc(ldb, 'posts', SLUG.post)));
  await S.expect('found', '同上：讀得到公開紀事正文', () => getDoc(doc(ldb, `posts/${SLUG.post}/content/main`)));
  await S.expect('found', '同上：讀得到相簿', () => getDoc(doc(ldb, 'albums', SLUG.album)));
  await S.expect('deny', '在私密名單也讀不到私密紀事', () => getDoc(doc(ldb, 'private_posts', SLUG.priv)));
  await S.expect('deny', '查私密紀事列表被拒',
    () => getDocs(query(collection(ldb, 'private_posts'), where('visible', '==', true))));
  await S.expect('deny', '不能在公開紀事留言（用自己名單上的 kind 與代號）',
    () => setDoc(doc(ldb, `posts/${SLUG.post}/comments/prereg1`), commentFor(W, 'linkPrivate')));
  await S.expect('deny', '不能在相簿留言', () => setDoc(doc(ldb, `albums/${SLUG.album}/comments/prereg2`), commentFor(W, 'linkPrivate')));
  await S.expect('deny', '不能在私密紀事留言',
    () => setDoc(doc(ldb, `private_posts/${SLUG.priv}/comments/prereg3`), commentFor(W, 'linkPrivate')));
  await S.expect('deny', '不能簽公開紀事的已讀回條',
    () => setDoc(doc(ldb, `posts/${SLUG.post2}/reads/${W.key('linkPrivate')}`), { kind: 'parent', readAt: serverTimestamp() }));
  await S.expect('deny', '不能簽私密紀事的已讀回條',
    () => setDoc(doc(ldb, `private_posts/${SLUG.priv2}/reads/${W.key('linkPrivate')}`), { kind: 'parent', readAt: serverTimestamp() }));
  // 同一個信箱改用 Google 登入（Google 帳號是本人的）就恢復全部權限
  const gdb = W.dbFor('prereg-google', google(W.key('linkPrivate')));
  await S.expect('found', '同一信箱改用 Google 登入：私密紀事讀得到', () => getDoc(doc(gdb, 'private_posts', SLUG.priv)));
  await S.expect('allow', '同一信箱改用 Google 登入：可以留言',
    () => setDoc(doc(gdb, `posts/${SLUG.post}/comments/prereg4`), commentFor(W, 'linkPrivate')));
  await S.expect('allow', '同一信箱改用 Google 登入：可以簽回條',
    () => setDoc(doc(gdb, `posts/${SLUG.post2}/reads/${W.key('linkPrivate')}`), { kind: 'parent', readAt: serverTimestamp() }));
}
