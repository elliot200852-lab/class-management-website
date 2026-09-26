// 欄位白名單：瀏覽器寫得到的每一種文件，多一欄、少必填、型別錯、超過大小、冒用他人（DATA-MODEL §2.7、§2.8、
// §2.12、§2.14、§2.15）。每一組先放一個「合法的基準」證明身分本身是允許的，再逐項弄壞一個地方。
import {
  addDoc, collection, doc, serverTimestamp, setDoc, Timestamp, updateDoc,
} from 'firebase/firestore';
import { ENTRY, SLUG } from '../lib/world.mjs';
import { commentFor } from './threads.mjs';
import { blogCommentFor, entryFor, IMAGE, newPostId, THUMB } from './blogs.mjs';

const without = (obj, key) => {
  const o = { ...obj };
  delete o[key];
  return o;
};
const CLIENT_TIME = Timestamp.fromDate(new Date('2026-09-01T00:00:00Z'));

export async function run(S, W) {
  S.section('欄位白名單：留言（§2.7）');
  await W.reset();
  const rdb = W.db('reader');
  const thread = `posts/${SLUG.post}/comments`;
  const base = commentFor(W, 'reader');
  const addC = (data) => addDoc(collection(rdb, thread), data);
  await S.expect('allow', '合法基準（班網讀者）', () => addC(base));
  await S.expect('allow', '帶合法的 replyTo', () => addC({ ...base, replyTo: 'AbC123xyz' }));
  await S.expect('allow', 'authorName 剛好 20 字、body 剛好 500 字', () => addC({ ...base, authorName: '字'.repeat(20), body: 'x'.repeat(500) }));
  await S.expect('deny', '多一欄', () => addC({ ...base, extra: 1 }));
  for (const k of ['authorName', 'body', 'role', 'authorAlias', 'status', 'createdAt']) {
    await S.expect('deny', `少必填 ${k}`, () => addC(without(base, k)));
  }
  await S.expect('deny', 'authorName 是數字', () => addC({ ...base, authorName: 123 }));
  await S.expect('deny', 'authorName 空字串', () => addC({ ...base, authorName: '' }));
  await S.expect('deny', 'authorName 21 字', () => addC({ ...base, authorName: '字'.repeat(21) }));
  await S.expect('deny', 'body 空字串', () => addC({ ...base, body: '' }));
  await S.expect('deny', 'body 501 字', () => addC({ ...base, body: 'x'.repeat(501) }));
  await S.expect('deny', 'body 是陣列', () => addC({ ...base, body: ['x'] }));
  await S.expect('deny', '建立時 status 就是 hidden', () => addC({ ...base, status: 'hidden' }));
  await S.expect('deny', 'createdAt 用瀏覽器自己的時間', () => addC({ ...base, createdAt: CLIENT_TIME }));
  await S.expect('deny', 'role 冒充導師', () => addC({ ...base, role: 'teacher' }));
  await S.expect('deny', 'role 冒充同仁（名單上是家長）', () => addC({ ...base, role: 'staff' }));
  await S.expect('deny', 'authorAlias 冒用別人的代號', () => addC({ ...base, authorAlias: W.alias('parent') }));
  await S.expect('deny', 'authorAlias 空字串', () => addC({ ...base, authorAlias: '' }));
  await S.expect('deny', 'replyTo 65 字', () => addC({ ...base, replyTo: 'a'.repeat(65) }));
  await S.expect('deny', 'replyTo 含不准的字元', () => addC({ ...base, replyTo: 'abc/../x' }));
  await S.expect('deny', 'replyTo 是數字', () => addC({ ...base, replyTo: 12 }));
  const tdb = W.db('teacher');
  const tbase = commentFor(W, 'teacher');
  await S.expect('allow', '導師以 role=teacher 留言', () => addDoc(collection(tdb, thread), tbase));
  await S.expect('deny', '導師以 role=parent 留言（跟名單上的 kind 不符）', () => addDoc(collection(tdb, thread), { ...tbase, role: 'parent' }));
  await S.expect('deny', '導師冒用家長的代號', () => addDoc(collection(tdb, thread), { ...tbase, authorAlias: W.alias('reader') }));
  await S.expect('deny', '導師收起留言時順便改內文',
    () => updateDoc(doc(tdb, `${thread}/c-visible`), { status: 'hidden', body: '改' }));
  await S.expect('deny', '導師把狀態改成白名單外的值', () => updateDoc(doc(tdb, `${thread}/c-visible`), { status: 'deleted' }));
  await S.expect('allow', '導師把收起的還原', () => updateDoc(doc(tdb, `${thread}/c-hidden`), { status: 'visible' }));

  S.section('欄位白名單：回條（§2.8）');
  await W.reset();
  const rc = (r, data, key = W.key(r)) => setDoc(doc(W.db(r), `posts/${SLUG.post2}/reads/${key}`), data);
  const rbase = { kind: 'parent', readAt: serverTimestamp() };
  await S.expect('allow', '合法基準（班網讀者）', () => rc('reader', rbase));
  await S.expect('allow', '同仁的 kind 是 staff', () => rc('staff', { kind: 'staff', readAt: serverTimestamp() }));
  await S.expect('deny', '多一欄', () => rc('parent', { ...rbase, email: 'x@example.com' }));
  await S.expect('deny', '少 kind', () => rc('parent', { readAt: serverTimestamp() }));
  await S.expect('deny', '少 readAt', () => rc('parent', { kind: 'parent' }));
  await S.expect('deny', 'readAt 用瀏覽器自己的時間', () => rc('parent', { kind: 'parent', readAt: CLIENT_TIME }));
  await S.expect('deny', 'kind 跟名單不符（家長填 staff）', () => rc('parent', { kind: 'staff', readAt: serverTimestamp() }));
  await S.expect('deny', 'kind 填 teacher', () => rc('private', { kind: 'teacher', readAt: serverTimestamp() }));
  await S.expect('deny', 'doc id 用大寫寫法（不是自己的 email 鍵）', () => rc('reader', rbase, W.key('reader').toUpperCase()));

  S.section('欄位白名單：部落格文章（§2.14）');
  await W.reset();
  const pdb = W.db('parent');
  let n = 0;
  const addE = (data, seat = '01') => {
    n += 1;
    return setDoc(doc(pdb, `student_blogs/${seat}/entries/2026-09-20-f${String(n).padStart(7, '0')}`), data);
  };
  const ebase = entryFor(W, 'parent', { date: '2026-09-20' });   // date 必須等於 postId 前 10 碼
  const ph = (i, extra = {}) => ({ pid: String(i), w: 1280, h: 960, ...extra });
  await S.expect('allow', '合法基準（座號家長，沒有照片）', () => addE(ebase));
  await S.expect('allow', '三張照片、帶圖說', () => addE({ ...ebase, photos: [ph(0, { caption: '圖說' }), ph(1), ph(2)] }));
  await S.expect('allow', 'title 200 字、body 10000 字', () => addE({ ...ebase, title: 't'.repeat(200), body: 'b'.repeat(10000) }));
  await S.expect('deny', '多一欄', () => addE({ ...ebase, pinned: true }));
  await S.expect('deny', '建立時就帶 updatedAt（不在建立的白名單）', () => addE({ ...ebase, updatedAt: serverTimestamp() }));
  for (const k of ['title', 'body', 'date', 'author', 'authorAlias', 'photos', 'visible', 'createdAt']) {
    await S.expect('deny', `少必填 ${k}`, () => addE(without(ebase, k)));
  }
  await S.expect('deny', 'title 空字串', () => addE({ ...ebase, title: '' }));
  await S.expect('deny', 'title 201 字', () => addE({ ...ebase, title: 't'.repeat(201) }));
  await S.expect('deny', 'body 10001 字', () => addE({ ...ebase, body: 'b'.repeat(10001) }));
  await S.expect('deny', 'date 格式不對', () => addE({ ...ebase, date: '2026/09/10' }));
  await S.expect('deny', 'date 跟 postId 前 10 碼不同（填到未來）', () => addE({ ...ebase, date: '2099-01-01' }));
  await S.expect('deny', 'date 跟 postId 前 10 碼不同（格式對、差一天）', () => addE({ ...ebase, date: '2026-09-21' }));
  await S.expect('deny', '家長填 author=teacher', () => addE({ ...ebase, author: 'teacher' }));
  await S.expect('deny', 'authorAlias 冒用導師的代號', () => addE({ ...ebase, authorAlias: W.alias('teacher') }));
  await S.expect('deny', '建立時 visible=false', () => addE({ ...ebase, visible: false }));
  await S.expect('deny', 'createdAt 用瀏覽器自己的時間', () => addE({ ...ebase, createdAt: CLIENT_TIME }));
  await S.expect('deny', 'photos 四張', () => addE({ ...ebase, photos: [ph(0), ph(1), ph(2), { pid: '3', w: 1, h: 1 }] }));
  await S.expect('deny', 'photos 順序錯（第一張 pid 是 1）', () => addE({ ...ebase, photos: [ph(1)] }));
  await S.expect('deny', 'photos 多一欄', () => addE({ ...ebase, photos: [ph(0, { url: 'https://example.com/x.jpg' })] }));
  await S.expect('deny', 'photos 少 h', () => addE({ ...ebase, photos: [without(ph(0), 'h')] }));
  await S.expect('deny', 'photos 的 w 是 0', () => addE({ ...ebase, photos: [ph(0, { w: 0 })] }));
  await S.expect('deny', 'photos 的 w 超過 1600', () => addE({ ...ebase, photos: [ph(0, { w: 1601 })] }));
  await S.expect('deny', 'photos 的圖說 301 字', () => addE({ ...ebase, photos: [ph(0, { caption: 'c'.repeat(301) })] }));
  await S.expect('deny', 'photos 不是陣列', () => addE({ ...ebase, photos: { 0: ph(0) } }));
  await S.expect('deny', 'postId 格式不對（大寫）',
    () => setDoc(doc(pdb, 'student_blogs/01/entries/2026-09-20-ABCD1234'), ebase));
  await S.expect('deny', '座號格式不對（"1"）',
    () => setDoc(doc(pdb, `student_blogs/1/entries/${newPostId('seatfmt')}`), ebase));
  const tdb2 = W.db('teacher');
  const E01 = doc(tdb2, `student_blogs/01/entries/${ENTRY.e01}`);
  await S.expect('allow', '導師改文（title、body、updatedAt）', () => updateDoc(E01, { title: '新標題', body: '新內文', updatedAt: serverTimestamp() }));
  await S.expect('deny', '導師改文沒帶 updatedAt', () => updateDoc(E01, { title: '再改' }));
  await S.expect('deny', '導師改文的 updatedAt 用瀏覽器時間', () => updateDoc(E01, { title: '再改', updatedAt: CLIENT_TIME }));
  await S.expect('deny', '導師改 author', () => updateDoc(E01, { author: 'teacher', updatedAt: serverTimestamp() }));
  await S.expect('deny', '導師改 createdAt', () => updateDoc(E01, { createdAt: serverTimestamp(), updatedAt: serverTimestamp() }));
  await S.expect('deny', '導師改 photos', () => updateDoc(E01, { photos: [], updatedAt: serverTimestamp() }));
  await S.expect('deny', '導師改的 title 201 字', () => updateDoc(E01, { title: 't'.repeat(201), updatedAt: serverTimestamp() }));
  await S.expect('deny', '導師把 visible 改成字串', () => updateDoc(E01, { visible: 'no', updatedAt: serverTimestamp() }));
  await S.expect('deny', '家長改自己發的文', () => updateDoc(doc(pdb, `student_blogs/01/entries/${ENTRY.e01}`), { title: '改', updatedAt: serverTimestamp() }));

  S.section('欄位白名單：部落格照片（§2.12）');
  await W.reset();
  let m = 0;
  const photo = (sub, pid, data) => {
    m += 1;
    return setDoc(doc(pdb, `student_blogs/01/entries/2026-09-21-p${String(m).padStart(7, '0')}/${sub}/${pid}`), data);
  };
  await S.expect('allow', '縮圖合法基準（pid 0）', () => photo('thumbs', '0', THUMB));
  await S.expect('allow', '縮圖 pid 2、order 2', () => photo('thumbs', '2', { ...THUMB, order: 2 }));
  await S.expect('allow', '縮圖 data 剛好 49152 字元、480×480', () => photo('thumbs', '0', { ...THUMB, data: 'A'.repeat(49152), w: 480, h: 480 }));
  await S.expect('deny', '縮圖多一欄（caption 只給腳本）', () => photo('thumbs', '0', { ...THUMB, caption: 'x' }));
  await S.expect('deny', '縮圖少 order', () => photo('thumbs', '0', without(THUMB, 'order')));
  await S.expect('deny', '縮圖 order 跟 pid 不符', () => photo('thumbs', '1', { ...THUMB, order: 0 }));
  await S.expect('deny', '縮圖 order 是字串', () => photo('thumbs', '0', { ...THUMB, order: '0' }));
  await S.expect('deny', '縮圖 data 49153 字元', () => photo('thumbs', '0', { ...THUMB, data: 'A'.repeat(49153) }));
  await S.expect('deny', '縮圖 data 空字串', () => photo('thumbs', '0', { ...THUMB, data: '' }));
  await S.expect('deny', '縮圖 w 481', () => photo('thumbs', '0', { ...THUMB, w: 481 }));
  await S.expect('deny', '縮圖 h 是字串', () => photo('thumbs', '0', { ...THUMB, h: '240' }));
  await S.expect('deny', '縮圖 pid 3', () => photo('thumbs', '3', { ...THUMB, order: 3 }));
  await S.expect('deny', '縮圖 pid 是腳本那種 16 碼', () => photo('thumbs', 'a1b2c3d4e5f60718', THUMB));
  await S.expect('allow', '顯示圖合法基準', () => photo('images', '0', IMAGE));
  await S.expect('allow', '顯示圖 data 剛好 716800 字元、1600×1600', () => photo('images', '1', { data: 'A'.repeat(716800), w: 1600, h: 1600 }));
  await S.expect('deny', '顯示圖多帶 order', () => photo('images', '0', { ...IMAGE, order: 0 }));
  await S.expect('deny', '顯示圖少 data', () => photo('images', '0', without(IMAGE, 'data')));
  await S.expect('deny', '顯示圖 data 716801 字元', () => photo('images', '0', { ...IMAGE, data: 'A'.repeat(716801) }));
  await S.expect('deny', '顯示圖 h 1601', () => photo('images', '0', { ...IMAGE, h: 1601 }));
  await S.expect('deny', '顯示圖 w 是小數', () => photo('images', '0', { ...IMAGE, w: 12.5 }));

  S.section('欄位白名單：部落格對話串（§2.15）');
  await W.reset();
  const bcPath = `student_blogs/01/entries/${ENTRY.e01}/blog_comments`;
  const addB = (r, data) => addDoc(collection(W.db(r), bcPath), data);
  const bbase = blogCommentFor(W, 'parent');
  await S.expect('allow', '合法基準（座號家長）', () => addB('parent', bbase));
  await S.expect('allow', '合法基準（導師）', () => addB('teacher', blogCommentFor(W, 'teacher')));
  await S.expect('deny', '多一欄（authorName 不在這裡的白名單）', () => addB('parent', { ...bbase, authorName: '媽媽' }));
  for (const k of ['body', 'role', 'authorAlias', 'status', 'createdAt']) {
    await S.expect('deny', `少必填 ${k}`, () => addB('parent', without(bbase, k)));
  }
  await S.expect('deny', 'body 501 字', () => addB('parent', { ...bbase, body: 'x'.repeat(501) }));
  await S.expect('deny', 'body 空字串', () => addB('parent', { ...bbase, body: '' }));
  await S.expect('deny', '家長填 role=teacher', () => addB('parent', { ...bbase, role: 'teacher' }));
  await S.expect('deny', '導師填 role=parent', () => addB('teacher', { ...blogCommentFor(W, 'teacher'), role: 'parent' }));
  await S.expect('deny', '家長冒用導師的代號', () => addB('parent', { ...bbase, authorAlias: W.alias('teacher') }));
  await S.expect('deny', '建立時 status 是 hidden', () => addB('parent', { ...bbase, status: 'hidden' }));
  await S.expect('deny', 'createdAt 用瀏覽器自己的時間', () => addB('parent', { ...bbase, createdAt: CLIENT_TIME }));
}
