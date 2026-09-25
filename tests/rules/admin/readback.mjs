// 管理腳本寫出來的資料，用「真的規則＋真的 Firebase JS SDK」以各種讀者身分讀回來（模擬器）。
//
// 不要直接跑這支：由 python3 scripts/test_admin.py 在 firebase emulators:exec 裡呼叫，
// 環境變數 CMW_READBACK_MANIFEST 指到一份 JSON（規則檔、導師 email、各篇的路徑）。
//
// 要證明的事：
//   1. 讀者、座號家長、同仁、私密讀者照 DATA-MODEL 的權限表讀得到（或讀不到）腳本寫的內容——
//      也就是腳本寫的 visible、kind、seats、alias 這些欄位的形狀，規則真的吃得下。
//   2. 腳本寫的部落格文章＋照片：導師用同一份欄位在瀏覽器端重建一次（新 postId、伺服器時間），
//      規則的欄位白名單放行＝腳本寫的形狀跟瀏覽器寫的是同一套。
//   3. 家長用名單上的作者代號留言：規則放行＝access_sync 產生的代號格式正確。
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import {
  addDoc, collection, doc, getDoc, getDocs, limit, orderBy, query, serverTimestamp, setLogLevel,
  updateDoc, where, writeBatch,
} from 'firebase/firestore';

setLogLevel('silent');
const M = JSON.parse(readFileSync(process.env.CMW_READBACK_MANIFEST, 'utf8'));
const rules = readFileSync(M.rulesFile, 'utf8');
const env = await initializeTestEnvironment({ projectId: M.projectId, firestore: { rules } });

const token = (email) => ({ email, email_verified: true, firebase: { sign_in_provider: 'google.com', identities: {} } });
const as = (name, email) => env.authenticatedContext(`u-${name}`, token(email)).firestore();
const T = as('teacher', M.teacher);
const PA = as('parentA', M.parentA);      // 座號 01 的母（也是私密讀者）
const PY = as('parentY', M.parentY);      // 座號 25 的母（一般讀者）
const ST = as('staff', M.staff);          // 同仁，授權 01、03
const ANON = env.unauthenticatedContext().firestore();

let pass = 0;
let fail = 0;
async function ok(label, fn) {
  try {
    await fn();
    pass += 1;
    if (M.verbose) console.log(`   ✓ ${label}`);
  } catch (e) {
    fail += 1;
    console.log(`   ✗ ${label}　→ ${String((e && (e.code ? e.code + '：' : '') + e.message) || e).split('\n')[0].slice(0, 200)}`);
  }
}
const must = (cond, msg) => { if (!cond) throw new Error(msg); };
const allowed = (p) => assertSucceeds(p);
const denied = (p) => assertFails(p);

const post = `posts/${M.post}`;
const album = `albums/${M.album}`;
const priv = `private_posts/${M.private}`;

await ok('家長讀自己的名單文件：kind＝parent、代號 12 碼', async () => {
  const s = await allowed(getDoc(doc(PA, 'allowlist', M.parentAKey)));
  must(s.exists() && s.data().kind === 'parent' && /^[a-z0-9]{12}$/.test(s.data().alias), '名單文件形狀不對');
});
await ok('家長讀自己的座號對應：seats＝[01]、active', async () => {
  const s = await allowed(getDoc(doc(PA, 'parent_child_map', M.parentAKey)));
  must(s.exists() && JSON.stringify(s.data().seats) === '["01"]' && s.data().active === true, '座號對應不對');
});
await ok('家長讀別人的名單文件被拒', () => denied(getDoc(doc(PA, 'allowlist', M.parentYKey))));
await ok('私密讀者名單：座號 01 的母在、座號 25 的母讀自己那份是「找不到」', async () => {
  must((await allowed(getDoc(doc(PA, 'private_allowlist', M.parentAKey)))).exists(), '座號 01 的母不在私密名單');
  must(!(await allowed(getDoc(doc(PY, 'private_allowlist', M.parentYKey)))).exists(), '座號 25 的母不該在私密名單');
});
await ok('讀者查最新紀事（visible＋date desc）看得到這篇', async () => {
  const r = await allowed(getDocs(query(collection(PY, 'posts'), where('visible', '==', true), orderBy('date', 'desc'), limit(20))));
  must(r.docs.some((d) => d.id === M.post), '列表裡沒有這篇');
});
await ok('讀者讀正文 content/main', async () => {
  const s = await allowed(getDoc(doc(PY, post, 'content', 'main')));
  must(s.exists() && Array.isArray(s.data().blocks) && s.data().blocks.length > 0, '正文是空的');
});
if (M.postCover) {
  await ok('讀者讀紀事的縮圖與顯示圖', async () => {
    must((await allowed(getDoc(doc(PY, post, 'thumbs', M.postCover)))).exists(), '縮圖不存在');
    must((await allowed(getDoc(doc(PY, post, 'images', M.postCover)))).exists(), '顯示圖不存在');
  });
}
await ok('未登入讀紀事被拒', () => denied(getDoc(doc(ANON, post))));
await ok('家長用名單上的作者代號留言（規則驗代號）', async () => {
  await allowed(addDoc(collection(PA, post, 'comments'), {
    authorName: '學生 A 家長', body: '謝謝老師', role: 'parent', authorAlias: M.parentAAlias,
    status: 'visible', createdAt: serverTimestamp(),
  }));
});
await ok('相簿列表（visible）看得到、縮圖依 order 查得到', async () => {
  const r = await allowed(getDocs(query(collection(PY, 'albums'), where('visible', '==', true), limit(200))));
  must(r.docs.some((d) => d.id === M.album), '相簿列表裡沒有這本');
  const t = await allowed(getDocs(query(collection(PY, album, 'thumbs'), orderBy('order', 'asc'), limit(60))));
  must(t.size === M.albumPhotos, `縮圖 ${t.size} 張，應該 ${M.albumPhotos} 張`);
});
await ok('私密紀事：私密讀者查得到、一般讀者被拒', async () => {
  const r = await allowed(getDocs(query(collection(PA, 'private_posts'), where('visible', '==', true), limit(100))));
  must(r.docs.some((d) => d.id === M.private), '私密讀者查不到');
  await denied(getDocs(query(collection(PY, 'private_posts'), where('visible', '==', true), limit(100))));
});
await ok('單頁：about、fun 讀者讀得到', async () => {
  must((await allowed(getDoc(doc(PY, 'pages', 'about')))).exists(), 'about 不存在');
  must((await allowed(getDoc(doc(PY, 'pages', 'fun')))).exists(), 'fun 不存在');
});
await ok('座號家長讀自己孩子的部落格主頁，讀別的座號被拒', async () => {
  must((await allowed(getDoc(doc(PA, 'student_blogs', '01')))).exists(), '01 的部落格不存在');
  await denied(getDoc(doc(PA, 'student_blogs', '02')));
});
await ok('同仁讀授權座號（03）可以、沒授權的（02）被拒', async () => {
  must((await allowed(getDoc(doc(ST, 'student_blogs', '03')))).exists(), '03 的部落格不存在');
  await denied(getDoc(doc(ST, 'student_blogs', '02')));
});
let entryData = null;
await ok('座號家長看得到導師用腳本發的文章與照片', async () => {
  const r = await allowed(getDocs(query(collection(PA, 'student_blogs', '01', 'entries'), where('visible', '==', true), limit(300))));
  const d = r.docs.find((x) => x.id === M.entryId);
  must(d, '文章列表裡沒有這篇');
  entryData = d.data();
  must(entryData.author === 'teacher' && entryData.authorAlias === M.teacherAlias, '作者或代號不對');
  for (const p of entryData.photos) {
    must((await allowed(getDoc(doc(PA, 'student_blogs', '01', 'entries', M.entryId, 'thumbs', p.pid)))).exists(), '縮圖不存在');
  }
});
await ok('導師名冊：導師讀得到、家長被拒', async () => {
  must((await allowed(getDoc(doc(T, 'roster', 'students')))).exists(), '名冊不存在');
  await denied(getDoc(doc(PA, 'roster', 'students')));
});
await ok('站台資訊 config/site：讀者讀得到', async () => {
  const s = await allowed(getDoc(doc(PY, 'config', 'site')));
  must(s.exists() && typeof s.data().teacherDisplayName === 'string', 'config/site 不對');
});
await ok('欄位白名單：用腳本寫的文章欄位，導師在瀏覽器端重建一次（規則放行＝形狀一致）', async () => {
  must(entryData, '沒有讀到文章');
  const newId = M.entryId.slice(0, 11) + 'zzzz9999';
  const base = `student_blogs/01/entries/${newId}`;
  const b = writeBatch(T);
  // updatedAt 是 --update（導師改文）才加的欄位；建立時規則不收它，這裡驗的是「建立」那一刻的形狀
  const { createdAt, updatedAt, ...rest } = entryData;
  b.set(doc(T, base), { ...rest, createdAt: serverTimestamp() });
  for (const p of entryData.photos) {
    const th = (await getDoc(doc(T, `student_blogs/01/entries/${M.entryId}/thumbs/${p.pid}`))).data();
    const im = (await getDoc(doc(T, `student_blogs/01/entries/${M.entryId}/images/${p.pid}`))).data();
    b.set(doc(T, `${base}/thumbs/${p.pid}`), th);
    b.set(doc(T, `${base}/images/${p.pid}`), im);
  }
  await allowed(b.commit());
});
await ok('導師改文（腳本 --update 動的欄位：title、body、updatedAt）規則放行', async () => {
  await allowed(updateDoc(doc(T, 'student_blogs', '01', 'entries', M.entryId), {
    title: entryData.title, body: entryData.body, updatedAt: serverTimestamp(),
  }));
});
await ok('導師用名單上的代號在文章底下回話', async () => {
  await allowed(addDoc(collection(T, 'student_blogs', '01', 'entries', M.entryId, 'blog_comments'), {
    body: '謝謝分享', role: 'teacher', authorAlias: M.teacherAlias, status: 'visible', createdAt: serverTimestamp(),
  }));
});

// v1.1：座位表、個人照、家長合照只有導師讀得到；每日一詩（一個月一份單頁）讀者讀得到
if (M.v11) {
  await ok('v1.1 座位表：導師讀得到、家長 get 與讀者查詢都被拒', async () => {
    must((await allowed(getDoc(doc(T, 'seating', M.v11.seating)))).exists(), '座位表不存在');
    await denied(getDoc(doc(PA, 'seating', M.v11.seating)));
    await denied(getDocs(query(collection(PY, 'seating'), limit(100))));
  });
  await ok('v1.1 每日一詩：讀者讀得到這個月那一份（kind poem、2 首）', async () => {
    const s = await allowed(getDoc(doc(PY, 'pages', M.v11.poemPage)));
    must(s.exists() && s.data().kind === 'poem' && s.data().data.items.length === 2, '每日一詩不對');
  });
  if (M.v11.personalSeat) {
    await ok('v1.1 個人照與家長合照：導師讀得到文件與照片，家長、同仁被拒', async () => {
      const p = await allowed(getDoc(doc(T, 'personal_photos', M.v11.personalSeat)));
      must(p.exists(), '個人照不存在');
      const pid = p.data().photoPids[0];
      must((await allowed(getDoc(doc(T, 'personal_photos', M.v11.personalSeat, 'images', pid)))).exists(), '顯示圖不存在');
      await denied(getDoc(doc(PA, 'personal_photos', M.v11.personalSeat)));
      await denied(getDoc(doc(PA, 'personal_photos', M.v11.personalSeat, 'thumbs', pid)));
      await denied(getDoc(doc(ST, 'parent_photo_display', M.v11.parentSeat)));
      const q = await allowed(getDocs(query(collection(T, 'parent_photo_display'), limit(40))));
      must(q.size >= 1 && Array.isArray(q.docs[0].data().relations), '家長合照查不到或沒有稱謂');
    });
  }
}

await env.cleanup();
console.log(`讀回檢查（真規則＋真 SDK）：通過 ${pass}、失敗 ${fail}`);
process.exit(fail === 0 && pass > 0 ? 0 : 1);
