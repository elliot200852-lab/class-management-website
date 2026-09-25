// 前端測試的共用工具：在 Node 的 vm 裡依序載入 site/js 的檔案，外加一個極簡的假 DOM。
// 只用 Node 內建模組，不需要 npm 套件（docs/ARCHITECTURE.md §8.3）。
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const SITE_JS = path.join(ROOT, 'site', 'js');

// ── 極簡假 DOM：只實作 createElement／createTextNode／createDocumentFragment／appendChild 這幾個 ──
class FakeNode {
  constructor(type) {
    this.nodeType = type;
    this.childNodes = [];
    this.parentNode = null;
  }
  appendChild(c) {
    if (c.nodeType === 11) {
      for (const k of c.childNodes.slice()) this.appendChild(k);
      c.childNodes = [];
      return c;
    }
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.childNodes.push(c);
    return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  replaceChild(n, o) {
    const i = this.childNodes.indexOf(o);
    if (i < 0) throw new Error('replaceChild：舊節點不在這裡');
    if (n.parentNode) n.parentNode.removeChild(n);
    this.childNodes[i] = n;
    n.parentNode = this;
    o.parentNode = null;
    return o;
  }
  get firstChild() { return this.childNodes[0] || null; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(''); }
  set textContent(v) {
    this.childNodes = [];
    const s = String(v);
    if (s !== '') this.appendChild(new FakeText(s));
  }
}

class FakeText extends FakeNode {
  constructor(t) { super(3); this.data = String(t); }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super(1);
    this.tagName = String(tag).toUpperCase();
    this.attributes = {};
    this.listeners = {};
  }
  setAttribute(k, v) { this.attributes[String(k)] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attributes, k) ? this.attributes[k] : null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn({ target: this })); }
}

function makeDocument() {
  return {
    createElement: (t) => new FakeElement(t),
    createTextNode: (t) => new FakeText(t),
    createDocumentFragment: () => new FakeNode(11),
  };
}

/** 走訪整棵樹（含自己） */
function walk(node, fn) {
  fn(node);
  for (const c of node.childNodes || []) walk(c, fn);
}

function findAll(node, tag) {
  const out = [];
  walk(node, (n) => { if (n.nodeType === 1 && n.tagName === tag.toUpperCase()) out.push(n); });
  return out;
}

function makeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    _map: m,
  };
}

/**
 * 在新的 vm context 裡依序載入 site/js 底下的檔案。回傳 { C, ctx, run, Date }。
 * opts.config：SITE_CONFIG；opts.localStorage：自訂（例如會丟錯的）
 */
function load(files, opts) {
  opts = opts || {};
  const ctx = {
    console,
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    crypto: globalThis.crypto,
    Uint8Array,
    btoa: globalThis.btoa,
    atob: globalThis.atob,
    encodeURIComponent,
    document: makeDocument(),
    localStorage: opts.localStorage || makeStorage(),
    sessionStorage: makeStorage(),
    location: { search: '', hash: '', href: 'http://localhost/index.html', hostname: 'localhost' },
    SITE_CONFIG: opts.config || { demo: true, className: '測試班級', categories: ['甲', '乙', '丙'], pages: {} },
  };
  vm.createContext(ctx);
  for (const f of files) {
    const p = path.join(SITE_JS, f);
    vm.runInContext(fs.readFileSync(p, 'utf8'), ctx, { filename: p });
  }
  return {
    C: ctx.CMW,
    ctx,
    run: (code) => vm.runInContext(code, ctx),
    Date: vm.runInContext('Date', ctx),
  };
}

const CORE = [
  'core/ns.js', 'core/queries.js', 'core/errors.js', 'core/util.js', 'core/emailkey.js', 'core/paths.js',
  'core/validate.js', 'core/text.js', 'core/blocks.js', 'core/read-stats.js', 'core/seen.js', 'core/route.js',
  'core/photos.js', 'core/query-eval.js', 'core/store.js',
];

/** 跨 realm 的物件先轉成純 JSON 再比 */
function plain(v) { return JSON.parse(JSON.stringify(v)); }

module.exports = { load, CORE, ROOT, walk, findAll, makeStorage, plain, FakeElement };
