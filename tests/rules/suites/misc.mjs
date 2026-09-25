// v1.1 集合（只有導師讀、網頁不寫）、導師的集合群組讀取、預設拒絕（DATA-MODEL §2.18–§2.20）
import {
  collection, collectionGroup, deleteDoc, doc, getDoc, getDocs, orderBy, query, setDoc, updateDoc, where,
} from 'firebase/firestore';
import { PID, RT, T } from '../lib/world.mjs';

export async function run(S, W) {
  S.section('v1.1：每日一詩 pages/poems-YYYY-MM（§2.11，一個月一份單頁）');
  await W.reset();
  await S.grid(W, 'get 這個月', { found: RT }, (db) => getDoc(doc(db, 'pages', 'poems-2026-09')));
  await S.grid(W, 'get 還沒發的月份（找不到）', { notfound: RT }, (db) => getDoc(doc(db, 'pages', 'poems-2026-10')));
  await S.grid(W, 'update（只有腳本寫）', {}, (db) => updateDoc(doc(db, 'pages', 'poems-2026-09'), { title: 'x' }));
  await S.grid(W, 'create（只有腳本寫）', {}, (db) => setDoc(doc(db, 'pages', 'poems-2026-11'), { title: 'x', kind: 'poem' }));

  S.section('v1.1：seating 座位表（§2.18）');
  await W.reset();
  await S.grid(W, 'get', { found: T }, (db) => getDoc(doc(db, 'seating', '2026-09-01')));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'seating')));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, 'seating', '2026-09-02'), { title: 'x' }));
  await S.grid(W, 'update', {}, (db) => updateDoc(doc(db, 'seating', '2026-09-01'), { title: 'y' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'seating', '2026-09-01')));

  S.section('v1.1：parent_photo_display 家長合照（§2.18）');
  await W.reset();
  await S.grid(W, 'get 主文件', { found: T }, (db) => getDoc(doc(db, 'parent_photo_display', '01')));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'parent_photo_display')));
  await S.grid(W, 'get thumbs', { found: T }, (db) => getDoc(doc(db, `parent_photo_display/01/thumbs/${PID}`)));
  await S.grid(W, 'get thumbs、images 以外的子集合', {}, (db) => getDoc(doc(db, `parent_photo_display/01/notes/${PID}`)));
  await S.grid(W, 'update 主文件', {}, (db) => updateDoc(doc(db, 'parent_photo_display', '01'), { note: 'x' }));
  await S.grid(W, 'create thumbs', {},
    (db) => setDoc(doc(db, 'parent_photo_display/01/thumbs/x'), { data: 'eA==', w: 1, h: 1, order: 0 }));

  S.section('v1.1：personal_photos 個人照（§2.18）');
  await W.reset();
  await S.grid(W, 'get 主文件', { found: T }, (db) => getDoc(doc(db, 'personal_photos', '01')));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'personal_photos')));
  await S.grid(W, 'get images', { found: T }, (db) => getDoc(doc(db, `personal_photos/01/images/${PID}`)));
  await S.grid(W, 'create thumbs', {},
    (db) => setDoc(doc(db, 'personal_photos/01/thumbs/x'), { data: 'eA==', w: 1, h: 1, order: 0 }));
  await S.grid(W, 'delete 主文件', {}, (db) => deleteDoc(doc(db, 'personal_photos', '01')));

  S.section('v1.1：blog_notify_queue 通知佇列（§2.18）');
  await W.reset();
  await S.grid(W, 'get', { found: T }, (db) => getDoc(doc(db, 'blog_notify_queue', '01__q1')));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'blog_notify_queue')));
  await S.grid(W, 'get sent/{hash}', { found: T }, (db) => getDoc(doc(db, 'blog_notify_queue/01__q1/sent/h1')));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, 'blog_notify_queue', '01__q2'), { state: 'pending' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'blog_notify_queue', '01__q1')));

  S.section('集合群組：comments、entries、blog_comments 只給導師（§2.19）');
  await W.reset();
  await S.grid(W, 'comments 群組（依 createdAt 排）', { allow: T },
    (db) => getDocs(query(collectionGroup(db, 'comments'), orderBy('createdAt', 'desc'))));
  await S.grid(W, 'comments 群組（帶 status == visible 也一樣只給導師）', { allow: T },
    (db) => getDocs(query(collectionGroup(db, 'comments'), where('status', '==', 'visible'))));
  await S.grid(W, 'entries 群組（author == parent）', { allow: T },
    (db) => getDocs(query(collectionGroup(db, 'entries'), where('author', '==', 'parent'))));
  await S.grid(W, 'entries 群組（帶 visible == true）', { allow: T },
    (db) => getDocs(query(collectionGroup(db, 'entries'), where('visible', '==', true))));
  await S.grid(W, 'blog_comments 群組（role == parent）', { allow: T },
    (db) => getDocs(query(collectionGroup(db, 'blog_comments'), where('role', '==', 'parent'))));
  await S.grid(W, 'thumbs 群組（沒有開放）', {}, (db) => getDocs(collectionGroup(db, 'thumbs')));
  await S.grid(W, 'reads 群組（沒有開放）', {}, (db) => getDocs(collectionGroup(db, 'reads')));

  S.section('預設拒絕：沒列到的路徑（§2.20）');
  await W.reset();
  await S.grid(W, 'get 沒列到的集合', {}, (db) => getDoc(doc(db, 'secrets', 'x')));
  await S.grid(W, 'list 沒列到的集合', {}, (db) => getDocs(collection(db, 'users')));
  await S.grid(W, 'create 沒列到的集合', {}, (db) => setDoc(doc(db, 'users', 'x'), { a: 1 }));
  await S.grid(W, 'get 紀事底下沒列到的子集合', {}, (db) => getDoc(doc(db, 'posts/2026-09-01-open/drafts/x')));
  await S.grid(W, 'create 部落格主頁底下沒列到的子集合', {},
    (db) => setDoc(doc(db, 'student_blogs/01/notes/x'), { a: 1 }));
}
