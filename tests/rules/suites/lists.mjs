// 名單、探針、站台設定、導師限定（DATA-MODEL §2.1–§2.5、§2.16、§2.17）
import {
  collection, deleteDoc, doc, getDoc, getDocs, serverTimestamp, setDoc, updateDoc,
} from 'firebase/firestore';
import { RT, T } from '../lib/world.mjs';

export async function run(S, W) {
  const NEW = { kind: 'parent', alias: 'newalias0001', updatedAt: serverTimestamp() };
  const HAS_ALLOW = ['reader', 'inactive', 'parent', 'staff', 'private', 'emailLink', 'linkPrivate', 'teacher', 'teacherLink'];

  S.section('名單：allowlist（§2.1）');
  await W.reset();
  // 自己那份：email 已驗證就讀得到；不在名單的人拿到「找不到」＝前端的「尚未授權」
  await S.grid(W, 'get 自己那份', { found: HAS_ALLOW, notfound: ['outsider', 'removed'] },
    (db, r) => getDoc(doc(db, 'allowlist', W.keyOf(r))));
  await S.grid(W, 'get 別人那份', { found: T }, (db, r) => getDoc(doc(db, 'allowlist', W.otherKey(r))));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'allowlist')));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, 'allowlist', 'new.person@example.com'), NEW));
  await S.grid(W, 'update（改自己的 kind）', {},
    (db, r) => updateDoc(doc(db, 'allowlist', HAS_ALLOW.includes(r) ? W.keyOf(r) : W.key('reader')), { kind: 'teacher' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'allowlist', W.key('reader'))));

  S.section('名單：private_allowlist（§2.2）');
  await W.reset();
  await S.grid(W, 'get 自己那份',
    { found: ['private', 'linkPrivate', 'teacher', 'teacherLink'], notfound: ['outsider', 'removed', 'reader', 'inactive', 'parent', 'staff', 'emailLink'] },
    (db, r) => getDoc(doc(db, 'private_allowlist', W.keyOf(r))));
  await S.grid(W, 'get 別人那份（私密讀者的）', { found: T },
    (db, r) => getDoc(doc(db, 'private_allowlist', r === 'private' ? W.key('teacher') : W.key('private'))));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'private_allowlist')));
  await S.grid(W, 'create（把自己加進去）', {},
    (db, r) => setDoc(doc(db, 'private_allowlist', W.keyOf(r)), { updatedAt: serverTimestamp() }));
  await S.grid(W, 'update', {}, (db) => updateDoc(doc(db, 'private_allowlist', W.key('private')), { x: 1 }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'private_allowlist', W.key('private'))));

  S.section('導師探針：site_access（§2.3）');
  await W.reset();
  await S.grid(W, 'get teacher（文件不存在）', { notfound: T }, (db) => getDoc(doc(db, 'site_access', 'teacher')));
  await S.grid(W, 'get 其他 id', {}, (db) => getDoc(doc(db, 'site_access', 'admin')));
  await S.grid(W, 'list', {}, (db) => getDocs(collection(db, 'site_access')));
  await S.grid(W, 'create teacher', {}, (db) => setDoc(doc(db, 'site_access', 'teacher'), { ok: true }));
  await S.grid(W, 'delete teacher', {}, (db) => deleteDoc(doc(db, 'site_access', 'teacher')));

  S.section('座號對應：parent_child_map（§2.4）');
  await W.reset();
  // 讀者＋Google 登入才讀得到自己那份；email 連結登入、被移出名單的都不行
  await S.grid(W, 'get 自己那份',
    { found: ['parent', 'staff', 'inactive'], notfound: ['reader', 'private', 'teacher'] },
    (db, r) => getDoc(doc(db, 'parent_child_map', W.keyOf(r))));
  await S.grid(W, 'get 別人那份（座號家長的）', { found: T },
    (db, r) => getDoc(doc(db, 'parent_child_map', r === 'parent' ? W.key('staff') : W.key('parent'))));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, 'parent_child_map')));
  await S.grid(W, 'create（替自己加座號）', {},
    (db, r) => setDoc(doc(db, 'parent_child_map', W.keyOf(r)),
      { seats: ['02'], kind: 'parent', active: true, label: '座號 02 家長', updatedAt: serverTimestamp() }));
  await S.grid(W, 'update（多加一個座號）', {},
    (db) => updateDoc(doc(db, 'parent_child_map', W.key('parent')), { seats: ['01', '02'] }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, 'parent_child_map', W.key('parent'))));

  S.section('站台資訊：config（§2.5）');
  await W.reset();
  await S.grid(W, 'get config/site', { found: RT }, (db) => getDoc(doc(db, 'config', 'site')));
  await S.grid(W, 'get config/notify（其他 doc）', { found: T }, (db) => getDoc(doc(db, 'config', 'notify')));
  await S.grid(W, 'get 不存在的 doc', { notfound: T }, (db) => getDoc(doc(db, 'config', 'nothing')));
  await S.grid(W, 'list', {}, (db) => getDocs(collection(db, 'config')));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, 'config', 'extra'), { x: 1 }));
  await S.grid(W, 'update config/site', {}, (db) => updateDoc(doc(db, 'config', 'site'), { studentsCount: 30 }));
  await S.grid(W, 'delete config/site', {}, (db) => deleteDoc(doc(db, 'config', 'site')));

  S.section('導師限定：roster（§2.16）');
  await W.reset();
  await S.grid(W, 'get roster/students', { found: T }, (db) => getDoc(doc(db, 'roster', 'students')));
  await S.grid(W, 'get roster/links', { found: T }, (db) => getDoc(doc(db, 'roster', 'links')));
  await S.grid(W, 'list roster', {}, (db) => getDocs(collection(db, 'roster')));
  await S.grid(W, 'create roster', {}, (db) => setDoc(doc(db, 'roster', 'extra'), { x: 1 }));
  await S.grid(W, 'update roster/students', {}, (db) => updateDoc(doc(db, 'roster', 'students'), { students: [] }));
  await S.grid(W, 'delete roster/links', {}, (db) => deleteDoc(doc(db, 'roster', 'links')));

  S.section('導師限定：ops 心跳（§2.17）');
  await W.reset();
  await S.grid(W, 'get ops/backup_status', { found: T }, (db) => getDoc(doc(db, 'ops', 'backup_status')));
  await S.grid(W, 'list ops', {}, (db) => getDocs(collection(db, 'ops')));
  await S.grid(W, 'create ops/backup_status 以外的', {}, (db) => setDoc(doc(db, 'ops', 'x'), { ok: true }));
  await S.grid(W, 'update ops/backup_status', {}, (db) => updateDoc(doc(db, 'ops', 'backup_status'), { nightly: {} }));
  await S.grid(W, 'delete ops/backup_status', {}, (db) => deleteDoc(doc(db, 'ops', 'backup_status')));
}
