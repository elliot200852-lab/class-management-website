// 我的孩子：部落格主頁、文章、文章照片、導師與家長的對話串（DATA-MODEL §2.12–§2.15）
// 座號家長（01）對自己座號、別人座號（02）兩邊都測；同仁的授權是 01 與 03。
import {
  addDoc, collection, deleteDoc, doc, getCountFromServer, getDoc, getDocs, limit, orderBy, query,
  serverTimestamp, setDoc, updateDoc, where,
} from 'firebase/firestore';
import { ENTRY, T } from '../lib/world.mjs';

const SEAT_READERS_01 = ['parent', 'staff', 'teacher'];
const WRITERS_01 = ['parent', 'teacher'];

// 每個角色一個不重複的新 postId（格式：日期＋8 碼小寫英數）
export function newPostId(r, day = '10') {
  return `2026-09-${day}-${r.toLowerCase().replace(/[^a-z0-9]/g, '').padEnd(8, '0').slice(0, 8)}`;
}

export const entryFor = (W, r, extra = {}) => ({
  title: '標題', body: '家長寫的內文', date: '2026-09-10',
  author: W.kind(r) === 'teacher' ? 'teacher' : 'parent', authorAlias: W.alias(r),
  photos: [], visible: true, createdAt: serverTimestamp(), ...extra,
});

export const blogCommentFor = (W, r, extra = {}) => ({
  body: '對話內容', role: W.kind(r) === 'teacher' ? 'teacher' : 'parent', authorAlias: W.alias(r),
  status: 'visible', createdAt: serverTimestamp(), ...extra,
});

export const THUMB = { data: 'dGh1bWI=', w: 320, h: 240, order: 0 };
export const IMAGE = { data: 'aW1hZ2U=', w: 1280, h: 960 };

export async function run(S, W) {
  const E01 = `student_blogs/01/entries/${ENTRY.e01}`;
  const E01H = `student_blogs/01/entries/${ENTRY.e01Hidden}`;
  const E02 = `student_blogs/02/entries/${ENTRY.e02}`;
  const EMISS = `student_blogs/01/entries/${ENTRY.missing}`;

  S.section('部落格主頁：student_blogs（§2.13）');
  await W.reset();
  await S.grid(W, 'get 座號 01', { found: SEAT_READERS_01 }, (db) => getDoc(doc(db, 'student_blogs', '01')));
  await S.grid(W, 'get 座號 02（別人的座號）', { found: T }, (db) => getDoc(doc(db, 'student_blogs', '02')));
  await S.grid(W, 'get 座號 03（同仁被授權）', { found: ['staff', 'teacher'] }, (db) => getDoc(doc(db, 'student_blogs', '03')));
  await S.grid(W, 'get 座號 05（不存在）', { notfound: T }, (db) => getDoc(doc(db, 'student_blogs', '05')));
  await S.grid(W, 'get 座號 "1"（格式不對）', { notfound: T }, (db) => getDoc(doc(db, 'student_blogs', '1')));
  await S.grid(W, 'list（家長不能列整班）', { allow: T }, (db) => getDocs(collection(db, 'student_blogs')));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, 'student_blogs', '04'), { seat: '04', displayName: '新', avatar: null }));
  await S.grid(W, 'update（改稱呼）', {}, (db) => updateDoc(doc(db, 'student_blogs', '01'), { displayName: '改掉' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'student_blogs', '01')));

  S.section('部落格文章：student_blogs/{seat}/entries（§2.14）');
  await W.reset();
  await S.grid(W, 'get 可見文章（座號 01）', { found: SEAT_READERS_01 }, (db) => getDoc(doc(db, E01)));
  await S.grid(W, 'get 下架文章（座號 01）', { found: T }, (db) => getDoc(doc(db, E01H)));
  await S.grid(W, 'get 不存在的文章（座號 01）', { notfound: SEAT_READERS_01 }, (db) => getDoc(doc(db, EMISS)));
  await S.grid(W, 'get 可見文章（座號 02）', { found: T }, (db) => getDoc(doc(db, E02)));
  await S.grid(W, 'list 座號 01（帶 visible == true）', { allow: SEAT_READERS_01 },
    (db) => getDocs(query(collection(db, 'student_blogs/01/entries'), where('visible', '==', true))));
  await S.grid(W, 'list 座號 01（不帶條件）', { allow: T }, (db) => getDocs(collection(db, 'student_blogs/01/entries')));
  await S.grid(W, 'list 座號 02（帶 visible == true）', { allow: T },
    (db) => getDocs(query(collection(db, 'student_blogs/02/entries'), where('visible', '==', true))));
  await S.grid(W, 'create 座號 01（家長 author=parent、導師 author=teacher）', { allow: WRITERS_01 },
    (db, r) => setDoc(doc(db, `student_blogs/01/entries/${newPostId(r, '10')}`), entryFor(W, r)));
  await S.grid(W, 'create 座號 02', { allow: T },
    (db, r) => setDoc(doc(db, `student_blogs/02/entries/${newPostId(r, '11')}`), entryFor(W, r, { date: '2026-09-11' })));
  await S.grid(W, 'create（date 跟 postId 前 10 碼不同：釘到未來）', {},
    (db, r) => setDoc(doc(db, `student_blogs/01/entries/${newPostId(r, '12')}`), entryFor(W, r, { date: '2099-12-31' })));
  await S.grid(W, 'create（postId 格式不對）', {},
    (db, r) => setDoc(doc(db, `student_blogs/01/entries/post-${r.toLowerCase()}`), entryFor(W, r)));
  await S.grid(W, 'update（導師改標題）', { allow: T },
    (db) => updateDoc(doc(db, E01), { title: '導師改過的標題', updatedAt: serverTimestamp() }));
  await S.grid(W, 'update（下架）', { allow: T },
    (db) => updateDoc(doc(db, E02), { visible: false, updatedAt: serverTimestamp() }));
  await S.grid(W, 'delete（網頁上只能下架）', {}, (db) => deleteDoc(doc(db, E01)));

  S.section('照片：部落格文章的 thumbs、images（§2.12）');
  await W.reset();
  await S.grid(W, 'get thumbs/0（文章可見，座號 01）', { found: SEAT_READERS_01 }, (db) => getDoc(doc(db, `${E01}/thumbs/0`)));
  await S.grid(W, 'get images/0（文章可見，座號 01）', { found: SEAT_READERS_01 }, (db) => getDoc(doc(db, `${E01}/images/0`)));
  await S.grid(W, 'get thumbs/0（文章下架）', { found: T }, (db) => getDoc(doc(db, `${E01H}/thumbs/0`)));
  await S.grid(W, 'get images/0（座號 02）', { found: T }, (db) => getDoc(doc(db, `${E02}/images/0`)));
  await S.grid(W, 'list thumbs（文章可見，依 order 排）', { allow: SEAT_READERS_01 },
    (db) => getDocs(query(collection(db, `${E01}/thumbs`), orderBy('order', 'asc'), limit(60))));
  await S.grid(W, 'list thumbs（文章下架）', { allow: T },
    (db) => getDocs(query(collection(db, `${E01H}/thumbs`), orderBy('order', 'asc'), limit(60))));
  await S.grid(W, 'create thumbs/0（座號 01）', { allow: WRITERS_01 },
    (db, r) => setDoc(doc(db, `student_blogs/01/entries/${newPostId(r, '12')}/thumbs/0`), THUMB));
  await S.grid(W, 'create images/0（座號 01）', { allow: WRITERS_01 },
    (db, r) => setDoc(doc(db, `student_blogs/01/entries/${newPostId(r, '12')}/images/0`), IMAGE));
  await S.grid(W, 'create thumbs/0（座號 02）', { allow: T },
    (db, r) => setDoc(doc(db, `student_blogs/02/entries/${newPostId(r, '13')}/thumbs/0`), THUMB));
  await S.grid(W, 'update thumbs/0（照片不可變）', {}, (db) => updateDoc(doc(db, `${E01}/thumbs/0`), { w: 100 }));
  await S.grid(W, 'delete images/0', {}, (db) => deleteDoc(doc(db, `${E01}/images/0`)));

  S.section('部落格對話串：entries/{postId}/blog_comments（§2.15，同仁進不來）');
  await W.reset();
  const BC = (e) => `${e}/blog_comments`;
  await S.grid(W, 'get 可見的一則（座號 01）', { found: WRITERS_01 }, (db) => getDoc(doc(db, `${BC(E01)}/bc-teacher`)));
  await S.grid(W, 'get 收起的一則', { found: T }, (db) => getDoc(doc(db, `${BC(E01)}/bc-hidden`)));
  await S.grid(W, 'get 不存在的一則', { notfound: WRITERS_01 }, (db) => getDoc(doc(db, `${BC(E01)}/bc-nothing`)));
  await S.grid(W, 'get（文章下架）', { found: T }, (db) => getDoc(doc(db, `${BC(E01H)}/bc-teacher`)));
  await S.grid(W, 'get（座號 02）', { found: T }, (db) => getDoc(doc(db, `${BC(E02)}/bc-teacher`)));
  await S.grid(W, 'list（帶 status == visible）', { allow: WRITERS_01 },
    (db) => getDocs(query(collection(db, BC(E01)), where('status', '==', 'visible'))));
  await S.grid(W, 'list（不帶條件）', { allow: T }, (db) => getDocs(collection(db, BC(E01))));
  await S.grid(W, 'list（文章下架，帶條件）', { allow: T },
    (db) => getDocs(query(collection(db, BC(E01H)), where('status', '==', 'visible'))));
  await S.grid(W, 'list（座號 02，帶條件）', { allow: T },
    (db) => getDocs(query(collection(db, BC(E02)), where('status', '==', 'visible'))));
  await S.grid(W, 'count（帶 status == visible）', { allow: WRITERS_01 },
    (db) => getCountFromServer(query(collection(db, BC(E01)), where('status', '==', 'visible'))));
  await S.grid(W, 'create（文章可見）', { allow: WRITERS_01 }, (db, r) => addDoc(collection(db, BC(E01)), blogCommentFor(W, r)));
  await S.grid(W, 'create（文章下架）', { allow: T }, (db, r) => addDoc(collection(db, BC(E01H)), blogCommentFor(W, r)));
  await S.grid(W, 'create（文章不存在）', {}, (db, r) => addDoc(collection(db, BC(EMISS)), blogCommentFor(W, r)));
  await S.grid(W, 'create（座號 02）', { allow: T }, (db, r) => addDoc(collection(db, BC(E02)), blogCommentFor(W, r)));
  await S.grid(W, 'update（收起導師那則）', { allow: T },
    (db) => updateDoc(doc(db, `${BC(E01)}/bc-teacher`), { status: 'hidden' }));
  await S.grid(W, 'update（改內文）', {}, (db) => updateDoc(doc(db, `${BC(E01)}/bc-parent`), { body: '改掉' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, `${BC(E01)}/bc-parent`)));

  // 家長只能收起自己那則、不能改回；導師可以還原（順序有意義，所以不用 grid）
  await W.reset();
  const parentDb = W.db('parent');
  const mine = doc(parentDb, `${BC(E01)}/bc-parent`);
  await S.expect('deny', '家長收起導師那則', () => updateDoc(doc(parentDb, `${BC(E01)}/bc-teacher`), { status: 'hidden' }));
  await S.expect('deny', '同仁收起家長那則', () => updateDoc(doc(W.db('staff'), `${BC(E01)}/bc-parent`), { status: 'hidden' }));
  await S.expect('deny', '家長把自己那則的狀態改成別的值', () => updateDoc(mine, { status: 'deleted' }));
  await S.expect('allow', '家長收起自己那則', () => updateDoc(mine, { status: 'hidden' }));
  await S.expect('deny', '家長把自己收起的那則改回可見', () => updateDoc(mine, { status: 'visible' }));
  await S.expect('allow', '導師把它還原', () => updateDoc(doc(W.db('teacher'), `${BC(E01)}/bc-parent`), { status: 'visible' }));
  await S.expect('deny', '家長收起自己那則時順便改內文', () => updateDoc(mine, { status: 'hidden', body: '改掉' }));
  await S.expect('deny', 'email 連結登入的家長收起同一則（不是 Google 登入）',
    () => updateDoc(doc(W.db('emailLink'), `${BC(E01)}/bc-parent`), { status: 'hidden' }));
}
