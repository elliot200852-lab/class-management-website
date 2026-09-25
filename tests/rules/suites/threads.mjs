// 三種討論串（紀事、相簿、私密紀事）的留言與回條（DATA-MODEL §2.7、§2.8）
import {
  addDoc, collection, deleteDoc, doc, getCountFromServer, getDoc, getDocs, query, serverTimestamp, setDoc,
  updateDoc, where,
} from 'firebase/firestore';
import { PT, RT, SLUG, T, WRITERS } from '../lib/world.mjs';

export const commentFor = (W, r, extra = {}) => ({
  authorName: '署名', body: '留言內容', role: W.kind(r), authorAlias: W.alias(r),
  status: 'visible', createdAt: serverTimestamp(), ...extra,
});

async function commentMatrix(S, W, { parent, hiddenParent, missingParent, readers, writers }) {
  await S.grid(W, 'get 可見的留言（父文件可見）', { found: readers },
    (db) => getDoc(doc(db, `${parent}/comments/c-visible`)));
  await S.grid(W, 'get 收起的留言', { found: T }, (db) => getDoc(doc(db, `${parent}/comments/c-hidden`)));
  await S.grid(W, 'get 留言（父文件下架）', { found: T }, (db) => getDoc(doc(db, `${hiddenParent}/comments/c-visible`)));
  await S.grid(W, 'get 不存在的留言（父文件可見）', { notfound: readers },
    (db) => getDoc(doc(db, `${parent}/comments/c-nothing`)));
  await S.grid(W, 'get 留言（父文件不存在）', { notfound: T }, (db) => getDoc(doc(db, `${missingParent}/comments/c-visible`)));
  await S.grid(W, 'list（帶 status == visible）', { allow: readers },
    (db) => getDocs(query(collection(db, `${parent}/comments`), where('status', '==', 'visible'))));
  await S.grid(W, 'list（不帶條件）', { allow: T }, (db) => getDocs(collection(db, `${parent}/comments`)));
  await S.grid(W, 'list（父文件下架，帶條件）', { allow: T },
    (db) => getDocs(query(collection(db, `${hiddenParent}/comments`), where('status', '==', 'visible'))));
  await S.grid(W, 'count（帶 status == visible）', { allow: readers },
    (db) => getCountFromServer(query(collection(db, `${parent}/comments`), where('status', '==', 'visible'))));
  await S.grid(W, 'create（父文件可見；各自的 kind 與代號）', { allow: writers },
    (db, r) => addDoc(collection(db, `${parent}/comments`), commentFor(W, r)));
  await S.grid(W, 'create（父文件下架）', { allow: T },
    (db, r) => addDoc(collection(db, `${hiddenParent}/comments`), commentFor(W, r)));
  await S.grid(W, 'create（父文件不存在）', {},
    (db, r) => addDoc(collection(db, `${missingParent}/comments`), commentFor(W, r)));
  await S.grid(W, 'update（收起一則）', { allow: T },
    (db) => updateDoc(doc(db, `${parent}/comments/c-visible`), { status: 'hidden' }));
  await S.grid(W, 'update（改內文）', {}, (db) => updateDoc(doc(db, `${parent}/comments/c-hidden`), { body: '改掉' }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, `${parent}/comments/c-hidden`)));
}

async function receiptMatrix(S, W, { parent, parent2, hiddenParent, owner, readers, signers }) {
  const receipt = (r) => ({ kind: W.kind(r), readAt: serverTimestamp() });
  await S.grid(W, 'get 自己那份', { found: [owner], notfound: readers.filter((r) => r !== owner) },
    (db, r) => getDoc(doc(db, `${parent}/reads/${W.keyOf(r)}`)));
  await S.grid(W, 'get 別人那份', { found: T },
    (db, r) => getDoc(doc(db, `${parent}/reads/${r === owner ? W.key('teacher') : W.key(owner)}`)));
  await S.grid(W, 'list', { allow: T }, (db) => getDocs(collection(db, `${parent}/reads`)));
  await S.grid(W, 'count', { allow: T }, (db) => getCountFromServer(collection(db, `${parent}/reads`)));
  await S.grid(W, 'count（kind == parent）', { allow: T },
    (db) => getCountFromServer(query(collection(db, `${parent}/reads`), where('kind', '==', 'parent'))));
  await S.grid(W, 'create 自己那份（父文件可見）', { allow: signers },
    (db, r) => setDoc(doc(db, `${parent2}/reads/${W.keyOf(r)}`), receipt(r)));
  await S.grid(W, 'create 自己那份（父文件下架）', {},
    (db, r) => setDoc(doc(db, `${hiddenParent}/reads/${W.keyOf(r)}`), receipt(r)));
  await S.grid(W, 'create 替別人簽', {},
    (db, r) => setDoc(doc(db, `${parent2}/reads/${W.otherKey(r)}`), receipt(r)));
  await S.grid(W, 'update（改已讀時間）', {},
    (db) => updateDoc(doc(db, `${parent}/reads/${W.key(owner)}`), { readAt: serverTimestamp() }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, `${parent}/reads/${W.key(owner)}`)));
  // 簽過的再送一次＝改＝被拒（前端先 get 自己那份，找不到才建；DATA-MODEL §2.8）
  await S.expect('deny', `已簽過的再建一次（等於改）｜${W.label(owner)}`,
    () => setDoc(doc(W.db(owner), `${parent}/reads/${W.key(owner)}`), receipt(owner)));
}

export async function run(S, W) {
  const writers = [...WRITERS, 'teacher'];

  S.section('留言：posts/{slug}/comments（§2.7）');
  await W.reset();
  await commentMatrix(S, W, { parent: `posts/${SLUG.post}`, hiddenParent: `posts/${SLUG.postHidden}`,
    missingParent: `posts/${SLUG.postMissing}`, readers: RT, writers });

  S.section('留言：albums/{slug}/comments（§2.7）');
  await W.reset();
  await commentMatrix(S, W, { parent: `albums/${SLUG.album}`, hiddenParent: `albums/${SLUG.albumHidden}`,
    missingParent: `albums/${SLUG.albumMissing}`, readers: RT, writers });

  S.section('留言：private_posts/{slug}/comments（§2.7，門票是私密讀者）');
  await W.reset();
  await commentMatrix(S, W, { parent: `private_posts/${SLUG.priv}`, hiddenParent: `private_posts/${SLUG.privHidden}`,
    missingParent: `private_posts/${SLUG.privMissing}`, readers: PT, writers: ['private', 'teacher'] });

  S.section('回條：posts/{slug}/reads（§2.8）');
  await W.reset();
  await receiptMatrix(S, W, { parent: `posts/${SLUG.post}`, parent2: `posts/${SLUG.post2}`,
    hiddenParent: `posts/${SLUG.postHidden}`, owner: 'reader', readers: RT, signers: WRITERS });

  S.section('回條：private_posts/{slug}/reads（§2.8，用私密門票）');
  await W.reset();
  await receiptMatrix(S, W, { parent: `private_posts/${SLUG.priv}`, parent2: `private_posts/${SLUG.priv2}`,
    hiddenParent: `private_posts/${SLUG.privHidden}`, owner: 'private', readers: PT, signers: ['private'] });
}
