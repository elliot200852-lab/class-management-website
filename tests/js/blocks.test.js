// 正文區塊渲染器（site/js/core/blocks.js）與純文字（text.js）的 XSS 案例（docs/ARCHITECTURE.md §4.2、§4.3）。
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { load, CORE, walk, findAll } = require('./helpers/load.js');

const { C } = load(CORE);

function render(blocks, opts) { return C.blocks.render(blocks, opts || {}); }
function p(...spans) { return { t: 'p', spans }; }

// 渲染結果裡不准出現的東西：事件屬性、HTML 字串屬性、style、script／iframe 元素
function assertClean(root) {
  walk(root, (n) => {
    if (n.nodeType !== 1) return;
    assert.notEqual(n.tagName, 'SCRIPT', '不准出現 <script> 元素');
    for (const k of Object.keys(n.attributes)) {
      assert.ok(!/^on/i.test(k), '不准有事件屬性：' + k);
      assert.notEqual(k.toLowerCase(), 'style', '不准有 style 屬性');
    }
    for (const k of Object.keys(n)) {
      assert.ok(!/^on/i.test(k), '不准設定事件屬性：' + k);
      assert.ok(!/html/i.test(k), '不准設定 HTML 字串屬性：' + k);
    }
  });
}

test('javascript: 連結只剩文字', () => {
  const root = render([p({ text: '點我', href: 'javascript:alert(1)' })]);
  assert.equal(findAll(root, 'a').length, 0);
  assert.equal(root.textContent, '點我');
  assertClean(root);
});

test('大小寫混合、前後空白、data:、http:、相對網址都只剩文字', () => {
  const bad = ['JaVaScRiPt:alert(1)', ' javascript:alert(1)', 'data:text/html,<script>alert(1)</script>',
    'http://example.com/', '/relative', '//example.com/x', 'vbscript:x', 'https://user:pw@example.com/'];
  for (const href of bad) {
    const root = render([p({ text: 'x', href })]);
    assert.equal(findAll(root, 'a').length, 0, href);
    assertClean(root);
  }
});

test('https 連結：rel 一定有 noopener、另開分頁、href 是正規化過的網址', () => {
  const root = render([p({ text: '範例', href: 'https://example.com/a b' })]);
  const a = findAll(root, 'a');
  assert.equal(a.length, 1);
  assert.match(a[0].rel, /noopener/);
  assert.match(a[0].rel, /noreferrer/);
  assert.equal(a[0].target, '_blank');
  assert.equal(a[0].href, 'https://example.com/a%20b');
});

test('<script> 文字只是文字節點', () => {
  const root = render([
    p({ text: '<script>alert(1)</script>' }),
    { t: 'h', level: 2, text: '<img src=x onerror=alert(1)>' },
    { t: 'quote', spans: [{ text: '"><svg onload=alert(1)>' }] },
  ]);
  assert.equal(findAll(root, 'script').length, 0);
  assert.equal(findAll(root, 'img').length, 0);
  assert.equal(findAll(root, 'svg').length, 0);
  assert.match(root.textContent, /<script>alert\(1\)<\/script>/);
  assertClean(root);
});

test('區塊或 span 帶 on* 欄位：不會變成屬性', () => {
  const root = render([
    { t: 'p', spans: [{ text: 'a', onclick: 'alert(1)' }], onmouseover: 'alert(1)', style: 'x' },
    { t: 'hr', onload: 'alert(1)' },
  ]);
  assertClean(root);
  assert.equal(findAll(root, 'p').length, 1);
  assert.equal(findAll(root, 'hr').length, 1);
});

test('超長字串：span 5000 字可以、5001 字整個區塊跳過', () => {
  const ok = render([p({ text: 'a'.repeat(5000) })]);
  assert.equal(findAll(ok, 'p').length, 1);
  const tooLong = render([p({ text: 'a'.repeat(5001) }), p({ text: '下一段' })]);
  assert.equal(findAll(tooLong, 'p').length, 1);
  assert.equal(tooLong.textContent, '下一段');
  const longHref = render([p({ text: 'x', href: 'https://example.com/' + 'a'.repeat(500) })]);
  assert.equal(findAll(longHref, 'p').length, 0, 'href 超過 500 字＝欄位不合，整個區塊跳過');
  const longHeading = render([{ t: 'h', level: 2, text: '字'.repeat(201) }]);
  assert.equal(findAll(longHeading, 'h2').length, 0);
});

test('不認得的區塊、欄位型別不對 → 整個跳過，不丟錯', () => {
  const root = render([
    { t: 'html', html: '<b>x</b>' },
    { t: 'h', level: 1, text: 'h1 不收' },
    { t: 'h', level: 5, text: 'h5 不收' },
    { t: 'p', spans: 'not-array' },
    { t: 'p', spans: [{ text: 1 }] },
    { t: 'p', spans: [{ text: 'x', b: 'yes' }] },
    { t: 'list', ordered: 'no', items: [] },
    { t: 'list', ordered: true, items: [['陣列的陣列']] },
    { t: 'img', pid: '../../x' },
    { t: 'video', url: 'javascript:alert(1)' },
    null, 42, 'p',
    p({ text: '留下來的' }),
  ]);
  assert.equal(root.childNodes.length, 1);
  assert.equal(root.textContent, '留下來的');
});

test('清單上限 100 項、區塊上限 400 個、每段 span 上限 200 個', () => {
  const item = { spans: [{ text: 'i' }] };
  assert.equal(findAll(render([{ t: 'list', ordered: false, items: Array(100).fill(item) }]), 'li').length, 100);
  assert.equal(findAll(render([{ t: 'list', ordered: false, items: Array(101).fill(item) }]), 'li').length, 0);
  const many = Array(450).fill(0).map(() => ({ t: 'hr' }));
  assert.equal(render(many).childNodes.length, 400);
  assert.equal(findAll(render([{ t: 'p', spans: Array(201).fill({ text: 'x' }) }]), 'p').length, 0);
});

test('粗體、斜體、段內換行', () => {
  const root = render([p({ text: '粗', b: true }, { text: '斜', i: true }, { text: '一\n二' })]);
  assert.equal(findAll(root, 'strong').length, 1);
  assert.equal(findAll(root, 'em').length, 1);
  assert.equal(findAll(root, 'br').length, 1);
});

test('影片：YouTube 先畫播放鈕（不建 iframe）；其他 https 網址畫連結卡', () => {
  const yt = render([{ t: 'video', url: 'https://www.youtube.com/watch?v=abcdefghijk', title: '影片' }]);
  assert.equal(findAll(yt, 'iframe').length, 0);
  assert.equal(findAll(yt, 'button').length, 1);
  const other = render([{ t: 'video', url: 'https://example.com/v' }]);
  assert.equal(findAll(other, 'a').length, 1);
  assert.equal(findAll(other, 'button').length, 0);
  // 點了播放鈕才建 iframe，而且只指向 youtube-nocookie
  const btn = findAll(yt, 'button')[0];
  btn.click();
  const frames = findAll(yt, 'iframe');
  assert.equal(frames.length, 1);
  assert.match(frames[0].src, /^https:\/\/www\.youtube-nocookie\.com\/embed\/abcdefghijk\?/);
  // 示範模式：點了只顯示說明，不建 iframe
  const demo = render([{ t: 'video', url: 'https://youtu.be/abcdefghijk' }], { demo: true });
  findAll(demo, 'button')[0].click();
  assert.equal(findAll(demo, 'iframe').length, 0);
});

test('YouTube id 判斷：主機與 11 碼格式都要對', () => {
  assert.equal(C.blocks.youtubeId('https://youtu.be/abcdefghijk'), 'abcdefghijk');
  assert.equal(C.blocks.youtubeId('https://m.youtube.com/shorts/abcdefghijk'), 'abcdefghijk');
  assert.equal(C.blocks.youtubeId('https://www.youtube.com/watch?v=short'), null);
  assert.equal(C.blocks.youtubeId('https://evil.example.com/watch?v=abcdefghijk'), null);
  assert.equal(C.blocks.youtubeId('http://www.youtube.com/watch?v=abcdefghijk'), null);
});

test('圖片：pid 格式對才畫；沒有 Store 時畫「這張照片讀不到」', () => {
  const root = render([{ t: 'img', pid: '0123456789abcdef', caption: '<b>圖說</b>' }]);
  assert.equal(findAll(root, 'figure').length, 1);
  assert.equal(findAll(root, 'img').length, 0);
  assert.match(root.textContent, /這張照片讀不到/);
  assert.match(root.textContent, /<b>圖說<\/b>/);
  assertClean(root);
});

test('text.render：網址變連結（結尾標點不算）、其他一律文字', () => {
  const frag = C.text.render('看 https://example.com/a。\n<script>x</script> javascript:alert(1) http://example.com');
  const a = [];
  walk(frag, (n) => { if (n.nodeType === 1 && n.tagName === 'A') a.push(n); });
  assert.equal(a.length, 1);
  assert.equal(a[0].href, 'https://example.com/a');
  assert.match(a[0].rel, /noopener/);
  let text = '';
  walk(frag, (n) => { if (n.nodeType === 3) text += n.data; });
  assert.match(text, /<script>x<\/script>/);
  assert.match(text, /。/);
  assert.equal(findAll(frag, 'br').length, 1);
});

test('text.safeUrl 只收 https', () => {
  assert.ok(C.text.safeUrl('https://example.com/'));
  for (const u of ['http://example.com/', 'javascript:alert(1)', 'data:,x', '', 'example.com', 42, null]) {
    assert.equal(C.text.safeUrl(u), null, String(u));
  }
});
