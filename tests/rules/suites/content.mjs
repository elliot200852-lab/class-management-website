// 腳本寫入的內容：班級紀事（摘要、正文）、相簿、私密紀事、單頁，以及它們底下的照片
// （DATA-MODEL §2.6、§2.9–§2.12）。網頁一律不能寫；讀取看主人文件的 visible。
import {
  collection, deleteDoc, doc, getDoc, getDocs, limit, orderBy, query, serverTimestamp, setDoc, updateDoc, where,
} from 'firebase/firestore';
import { PAGE, PID, PT, RT, SLUG, T } from '../lib/world.mjs';

// 摘要文件（posts、albums、private_posts、pages）共用的一整列權限表
async function summaryMatrix(S, W, { coll, visibleId, hiddenId, missingId, newId, readers }) {
  await S.grid(W, 'get 可見的', { found: readers }, (db) => getDoc(doc(db, coll, visibleId)));
  await S.grid(W, 'get 下架的', { found: T }, (db) => getDoc(doc(db, coll, hiddenId)));
  await S.grid(W, 'get 不存在的（有門票＝找不到；沒門票＝被拒）', { notfound: readers },
    (db) => getDoc(doc(db, coll, missingId)));
  await S.grid(W, 'list（帶 visible == true）', { allow: readers },
    (db) => getDocs(query(collection(db, coll), where('visible', '==', true))));
  await S.grid(W, 'list（不帶條件：規則不是過濾器）', { allow: T }, (db) => getDocs(collection(db, coll)));
  await S.grid(W, 'list（visible == false）', { allow: T },
    (db) => getDocs(query(collection(db, coll), where('visible', '==', false))));
  await S.grid(W, 'create', {},
    (db) => setDoc(doc(db, coll, newId), { title: '新的', visible: true, updatedAt: serverTimestamp() }));
  await S.grid(W, 'update（改標題）', {}, (db) => updateDoc(doc(db, coll, visibleId), { title: '改過的標題' }));
  await S.grid(W, 'update（上架下架的）', {}, (db) => updateDoc(doc(db, coll, hiddenId), { visible: true }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, coll, visibleId)));
}

// 照片文件：誰讀得到＝誰讀得到主人文件；網頁不能寫（部落格文章的照片另外測）
async function photoMatrix(S, W, { owner, hiddenOwner, missingOwner, readers }) {
  for (const sub of ['thumbs', 'images']) {
    await S.grid(W, `get ${sub}（主人可見）`, { found: readers }, (db) => getDoc(doc(db, `${owner}/${sub}/${PID}`)));
    await S.grid(W, `get ${sub}（主人下架）`, { found: T }, (db) => getDoc(doc(db, `${hiddenOwner}/${sub}/${PID}`)));
  }
  await S.grid(W, 'get thumbs（主人不存在）', { notfound: T }, (db) => getDoc(doc(db, `${missingOwner}/thumbs/${PID}`)));
  await S.grid(W, 'list thumbs（主人可見，依 order 排）', { allow: readers },
    (db) => getDocs(query(collection(db, `${owner}/thumbs`), orderBy('order', 'asc'), limit(60))));
  await S.grid(W, 'list thumbs（主人下架）', { allow: T },
    (db) => getDocs(query(collection(db, `${hiddenOwner}/thumbs`), orderBy('order', 'asc'), limit(60))));
  await S.grid(W, 'create thumbs', {},
    (db) => setDoc(doc(db, `${owner}/thumbs/0`), { data: 'eA==', w: 1, h: 1, order: 0 }));
  await S.grid(W, 'update images', {}, (db) => updateDoc(doc(db, `${owner}/images/${PID}`), { w: 2 }));
  await S.grid(W, 'delete thumbs', {}, (db) => deleteDoc(doc(db, `${owner}/thumbs/${PID}`)));
}

export async function run(S, W) {
  S.section('班級紀事：posts 摘要（§2.6）');
  await W.reset();
  await summaryMatrix(S, W, { coll: 'posts', visibleId: SLUG.post, hiddenId: SLUG.postHidden,
    missingId: SLUG.postMissing, newId: '2026-09-20-new', readers: RT });

  S.section('班級紀事正文：posts/{slug}/content（§2.6）');
  await W.reset();
  await S.grid(W, 'get main（紀事可見）', { found: RT }, (db) => getDoc(doc(db, `posts/${SLUG.post}/content/main`)));
  await S.grid(W, 'get main（紀事下架）', { found: T }, (db) => getDoc(doc(db, `posts/${SLUG.postHidden}/content/main`)));
  await S.grid(W, 'get main（紀事不存在）', { notfound: T }, (db) => getDoc(doc(db, `posts/${SLUG.postMissing}/content/main`)));
  await S.grid(W, 'get main 以外的 id', {}, (db) => getDoc(doc(db, `posts/${SLUG.post}/content/draft`)));
  await S.grid(W, 'list', {}, (db) => getDocs(collection(db, `posts/${SLUG.post}/content`)));
  await S.grid(W, 'create', {}, (db) => setDoc(doc(db, `posts/${SLUG.post2}/content/extra`), { blocks: [] }));
  await S.grid(W, 'update', {}, (db) => updateDoc(doc(db, `posts/${SLUG.post}/content/main`), { blocks: [] }));
  await S.grid(W, 'delete', {}, (db) => deleteDoc(doc(db, `posts/${SLUG.post}/content/main`)));

  S.section('照片：posts/{slug}/thumbs、images（§2.12）');
  await W.reset();
  await photoMatrix(S, W, { owner: `posts/${SLUG.post}`, hiddenOwner: `posts/${SLUG.postHidden}`,
    missingOwner: `posts/${SLUG.postMissing}`, readers: RT });

  S.section('相簿：albums（§2.9）');
  await W.reset();
  await summaryMatrix(S, W, { coll: 'albums', visibleId: SLUG.album, hiddenId: SLUG.albumHidden,
    missingId: SLUG.albumMissing, newId: '2026-09-20-new', readers: RT });

  S.section('照片：albums/{slug}/thumbs、images（§2.12）');
  await W.reset();
  await photoMatrix(S, W, { owner: `albums/${SLUG.album}`, hiddenOwner: `albums/${SLUG.albumHidden}`,
    missingOwner: `albums/${SLUG.albumMissing}`, readers: RT });

  S.section('私密紀事：private_posts（§2.10）');
  await W.reset();
  await summaryMatrix(S, W, { coll: 'private_posts', visibleId: SLUG.priv, hiddenId: SLUG.privHidden,
    missingId: SLUG.privMissing, newId: '2026-09-20-new', readers: PT });

  S.section('照片：private_posts/{slug}/thumbs、images（§2.12）');
  await W.reset();
  await photoMatrix(S, W, { owner: `private_posts/${SLUG.priv}`, hiddenOwner: `private_posts/${SLUG.privHidden}`,
    missingOwner: `private_posts/${SLUG.privMissing}`, readers: PT });

  S.section('單頁：pages（§2.11）');
  await W.reset();
  await summaryMatrix(S, W, { coll: 'pages', visibleId: PAGE.about, hiddenId: PAGE.hidden,
    missingId: PAGE.missing, newId: 'new-page', readers: RT });

  S.section('照片：pages/{pageId}/thumbs、images（§2.12）');
  await W.reset();
  await photoMatrix(S, W, { owner: `pages/${PAGE.home}`, hiddenOwner: `pages/${PAGE.hidden}`,
    missingOwner: `pages/${PAGE.missing}`, readers: RT });
}
