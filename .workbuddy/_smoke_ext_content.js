/* content.js 运行时冒烟测试（Node + 最小 DOM 桩，不联网、不开浏览器）。
 *
 * 为什么值得用桩测：悬浮按钮的风险点大多不是「像素好不好看」，而是
 *   ① 工具不可达 / 设置里关了 / 该站被隐藏过 时，**绝不能**挂出一个永远点不动的按钮；
 *   ② 样式到底有没有真的进影子树（adoptedStyleSheets 写错就裸奔，裸奔在无头环境里看不出来）；
 *   ③ 送出去的 payload 有没有带页面 HTML、行业、国家、升级开关；
 *   ④ 抓页面时有没有把 <script> 和自己那个宿主节点一起送进后端解析器；
 *   ⑤ 结果提示的文案映射（评分/邮箱/电话/第几级）与按钮态。
 * 这五条都能在桩上精确断言。至于「按钮长得对不对」——那必须人工加载扩展看，桩测不碰。
 *
 * 运行：node .workbuddy/_smoke_ext_content.js      （EXIT 0 = 全过）
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const EXT = path.join(__dirname, '..', 'extension');
const N = 400000;                       // 与 content.js / background.js 的 MAX_HTML 一致

let fails = 0, checks = 0;
function check(cond, label, detail) {
  checks++;
  if (cond) console.log('  OK   ' + label);
  else { fails++; console.log('  FAIL ' + label + (detail ? '  -- ' + detail : '')); }
}
function section(t) { console.log('\n========== ' + t + ' =========='); }
function tick(ms) { return new Promise((r) => setTimeout(r, ms == null ? 8 : ms)); }

/* ================= 最小 DOM 桩 ================= */

let elSeq = 0;
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.uid = ++elSeq;
    this.children = [];
    this.parent = null;
    this.className = '';
    this.id = '';
    this.textContent = '';
    this.disabled = false;
    this._html = '';
    this._listeners = {};
  }
  set innerHTML(v) { this._html = String(v); this.children = parseHtml(this._html); }
  get innerHTML() { return this._html; }
  appendChild(c) { c.parent = this; this.children.push(c); return c; }
  remove() {
    if (!this.parent) return;
    const i = this.parent.children.indexOf(this);
    if (i >= 0) this.parent.children.splice(i, 1);
    this.parent = null;
  }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  emit(type) { (this._listeners[type] || []).forEach((f) => f({ preventDefault() {} })); }
  attachShadow(opts) {
    this.shadow = {
      mode: opts && opts.mode,
      children: [],
      adoptedStyleSheets: [],
      appendChild(c) { c.parent = this; this.children.push(c); return c; },
    };
    return this.shadow;
  }
  querySelector(sel) { return walk(this, sel)[0] || null; }
  querySelectorAll(sel) { return walk(this, sel); }
  descendants() {
    const out = [];
    (function go(n) { n.children.forEach((c) => { out.push(c); go(c); }); })(this);
    return out;
  }
}

function matches(el, sel) {
  const s = sel.trim();
  if (!s) return false;
  if (s[0] === '.') return (' ' + el.className + ' ').indexOf(' ' + s.slice(1) + ' ') >= 0;
  if (s[0] === '#') return el.id === s.slice(1);
  return el.tagName === s.toUpperCase();
}

function walk(root, sel) {
  const parts = sel.split(',').map((s) => s.trim()).filter(Boolean);
  const all = root.descendants();
  const out = [];
  for (const p of parts) for (const el of all) if (matches(el, p) && out.indexOf(el) < 0) out.push(el);
  return out;
}

/** 极简 HTML 解析：只认 标签名 / class / id，够 querySelector 用。 */
function parseHtml(html) {
  const roots = [], stack = [];
  const re = /<(\/?)([a-zA-Z0-9]+)([^>]*?)(\/?)>/g;
  let m;
  while ((m = re.exec(html))) {
    if (m[1] === '/') { stack.pop(); continue; }
    const el = new El(m[2]);
    const cm = /class="([^"]*)"/.exec(m[3]);
    if (cm) el.className = cm[1];
    const im = /id="([^"]*)"/.exec(m[3]);
    if (im) el.id = im[1];
    if (stack.length) stack[stack.length - 1].appendChild(el); else roots.push(el);
    if (!m[4]) stack.push(el);
  }
  return roots;
}

/** documentElement.cloneNode() 返回「字符串 DOM」：只实现 content.js 真正用到的
 *  querySelectorAll + remove + outerHTML —— 刚好够验证「剥标签 / 摘掉自己 / 截断」。 */
function makeDocumentElement(pageHtml) {
  const el = new El('html');
  el.cloneNode = function () {
    let src = pageHtml;
    return {
      get outerHTML() { return src; },
      querySelectorAll(sel) {
        const out = [];
        for (const part of sel.split(',')) {
          const p = part.trim();
          const re = (p[0] === '#')
            ? new RegExp('<[a-zA-Z0-9]+[^>]*id="' + p.slice(1) + '"[^>]*>[\\s\\S]*?</[a-zA-Z0-9]+>', 'g')
            : new RegExp('<' + p + '\\b[^>]*>[\\s\\S]*?</' + p + '>', 'g');
          let mm;
          while ((mm = re.exec(src))) {
            const text = mm[0];
            out.push({ remove() { src = src.split(text).join(''); } });
          }
        }
        return out;
      },
    };
  };
  return el;
}

/* ================= 在「隔离世界」里跑真实的 content.js ================= */

const DEFAULT_SETTINGS = { industry: '塑料包装袋', country: '德国', upgrade: false, fabEnabled: true, port: 0 };

function loadContentScript(opts) {
  const o = opts || {};
  const cap = { payloads: [], sent: [], storage: {}, onMessage: [], grabCount: 0 };

  const chrome = {
    runtime: {
      lastError: undefined,
      onMessage: { addListener(f) { cap.onMessage.push(f); } },
      sendMessage(msg, cb) {
        cap.sent.push(msg.type);
        let resp = null;
        if (msg.type === 'DP_SETTINGS_GET') resp = o.settings || DEFAULT_SETTINGS;
        else if (msg.type === 'DP_PING') resp = o.ping || { online: true, port: 8000 };
        else if (msg.type === 'DP_COLLECT_PAYLOAD') {
          cap.payloads.push(msg.payload);
          resp = o.onCollect ? o.onCollect(msg.payload) : { ok: true, added: true, tier: 1, row: {} };
        }
        cb(resp);
      },
    },
    storage: {
      local: {
        get(k, cb) { cb(o.storageGet ? o.storageGet(k) : {}); },
        set(obj, cb) { Object.assign(cap.storage, obj); if (cb) cb(); },
      },
    },
  };

  const docEl = makeDocumentElement(o.pageHtml || PAGE);
  const body = new El('body');
  docEl.appendChild(body);
  const doc = {
    documentElement: docEl, body, title: o.title || 'Acme Bags',
    _listeners: {},
    addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
    createElement(tag) { return new El(tag); },
  };

  const sandbox = {
    chrome, document: doc,
    location: { href: 'https://acme-bags.com/about', hostname: 'acme-bags.com', protocol: 'https:' },
    setTimeout, clearTimeout, Promise, Object, Array, JSON, Number, String, Boolean,
    Math, Date, URL, Error, RegExp, console,
    CSSStyleSheet: class { constructor() { this.cssText = ''; } replaceSync(t) { this.cssText = t; } },
  };
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(EXT, 'floating-css.js'), 'utf8'), context, { filename: 'floating-css.js' });
  vm.runInContext(fs.readFileSync(path.join(EXT, 'content.js'), 'utf8'), context, { filename: 'content.js' });

  return { sandbox, doc, cap };
}

/** 模拟 background 向内容脚本要页面：走真实的 onMessage 监听器。 */
function grabVia(st) {
  let out = null;
  for (const f of st.cap.onMessage) {
    f({ type: 'DP_GRAB' }, {}, (r) => { out = r; });
  }
  return out;
}

function pushResult(st, result) {
  for (const f of st.cap.onMessage) f({ type: 'DP_RESULT', result }, {}, () => {});
}

function hostOf(st) { return st.doc.body.children[0] || null; }
function wrapOf(st) { const h = hostOf(st); return h ? h.shadow.children[0] : null; }

const PAGE = '<html><head><title>Acme Bags</title>'
  + '<style>body{color:red}</style></head><body>'
  + '<script>window.x=1</script>'
  + '<h1>Acme Bags Wholesale</h1>'
  + '<a href="mailto:sales@acme-bags.com">sales@acme-bags.com</a>'
  + '<div id="dp-collect-fab-host"></div>'
  + '</body></html>';

const OK_RESULT = {
  ok: true, added: true, existed: false, upgraded: true, tier: 3,
  row: { title: 'Acme Bags', url: 'https://acme-bags.com', emails: ['sales@acme-bags.com'],
         phones: ['+49 30 1234'], contact_url: '', score: 75, rating: '重点客户',
         snippet: '', formula: '', country: '德国', industry: '塑料包装袋' },
};

(async function main() {
  /* ---------------- ① 挂载门控 ---------------- */
  section('① 挂载门控：不该出现时绝不出现');

  const offline = loadContentScript({ ping: { online: false, port: 0 } });
  await tick(40);
  check(hostOf(offline) === null, '工具不可达 → 页面上没有宿主节点');

  const off = loadContentScript({ settings: Object.assign({}, DEFAULT_SETTINGS, { fabEnabled: false }),
                                  ping: { online: true, port: 8000 } });
  await tick(40);
  check(hostOf(off) === null, '设置里关了悬浮按钮 → 不挂载');

  const hid = loadContentScript({ ping: { online: true, port: 8000 },
                                  storageGet: (k) => ({ [k]: true }) });
  await tick(40);
  check(hostOf(hid) === null, '该网站被手动隐藏过（dpHide:<host>）→ 不挂载');

  const on = loadContentScript({ ping: { online: true, port: 8000 } });
  await tick(40);
  check(hostOf(on) !== null, '工具可达 → 挂上宿主节点');

  /* ---------------- ② 影子树与样式 ---------------- */
  section('② Shadow DOM 与样式：按钮不能裸奔');
  const host = hostOf(on);
  check(host.id === 'dp-collect-fab-host', '宿主 id 正确', host.id);
  check(host.shadow && host.shadow.mode === 'closed', 'Shadow DOM 是 closed 模式（页面脚本摸不到）',
        host.shadow && host.shadow.mode);
  const sheets = (host.shadow && host.shadow.adoptedStyleSheets) || [];
  check(sheets.length === 1, 'adoptedStyleSheets 挂了 1 张构造式样式表', 'len=' + sheets.length);
  const css = (sheets[0] && sheets[0].cssText) || '';
  check(css.indexOf(':host') >= 0 && css.indexOf('.dp-btn') >= 0 && css.indexOf('.dp-toast') >= 0,
        '样式表里真的含 :host / .dp-btn / .dp-toast（不是空表）');
  check(!!(sheets[0] instanceof on.sandbox.CSSStyleSheet), '用的是 CSSStyleSheet 实例（纯 CSSOM，不受页面 CSP 管）');
  const wrap = wrapOf(on);
  check(wrap && wrap.className === 'dp-wrap', '影子树里挂上了 .dp-wrap', wrap && wrap.className);
  check(!!wrap.querySelector('.dp-btn') && !!wrap.querySelector('.dp-toast') && !!wrap.querySelector('.dp-hide'),
        '.dp-btn / .dp-toast / .dp-hide 三个元素都在');
  check(wrap.innerHTML.indexOf('style=') < 0, '拼出的 HTML 里没有 style= 属性');
  check(wrap.querySelector('.dp-toast').className === 'dp-toast', '提示条初始状态是收起的');

  /* ---------------- ③ DP_GRAB：background 兜底取页面的那条路 ---------------- */
  section('③ DP_GRAB：background 直接问内容脚本要页面');
  const g = grabVia(on);
  check(!!g && g.ok === true, 'DP_GRAB 同步返回 ok=true');
  check(g && g.url === 'https://acme-bags.com/about', '返回当前页 URL', g && g.url);
  check(g && g.title === 'Acme Bags', '返回页面标题', g && g.title);

  /* ---------------- ④ 点击采集：payload 组装 ---------------- */
  section('④ 点击采集：payload 组装 + 页面清洗');
  wrap.querySelector('.dp-btn').emit('click');
  await tick(40);
  check(on.cap.payloads.length === 1, '点击后恰好发出 1 个采集请求', 'n=' + on.cap.payloads.length);
  const p = on.cap.payloads[0] || {};
  check(p.url === 'https://acme-bags.com/about', 'payload.url 是当前页地址', p.url);
  check(p.title === 'Acme Bags', 'payload.title 正确', p.title);
  check(p.industry === '塑料包装袋' && p.country === '德国',
        'payload 带上了设置里的默认行业/国家', p.industry + '/' + p.country);
  check(p.upgrade === false, 'payload.upgrade 跟随设置（本例是 false）', String(p.upgrade));
  check(typeof p.html === 'string' && p.html.indexOf('<!DOCTYPE html>') === 0,
        'payload.html 以 <!DOCTYPE html> 开头');
  check(p.html.indexOf('<script') < 0, 'payload.html 剥掉了 <script>');
  check(p.html.indexOf('<style') < 0, 'payload.html 剥掉了 <style>');
  check(p.html.indexOf('dp-collect-fab-host') < 0, 'payload.html 里没有我们自己那个宿主节点');
  check(p.html.indexOf('mailto:sales@acme-bags.com') >= 0,
        'payload.html 保留了 mailto（后端靠它抽邮箱）');
  check(wrap.querySelector('.dp-btn').disabled === false,
        '请求返回后按钮恢复可点（不是永久 disabled）');

  /* ---------------- ⑤ 超长页面截断 ---------------- */
  section('⑤ 超长页面：截断到 400000');
  const bigPage = '<html><body>' + '<p>填充内容</p>'.repeat(80000) + '</body></html>';
  check(bigPage.length > N, `构造的测试页 ${bigPage.length} 字节 > ${N}`);
  const big = loadContentScript({ ping: { online: true, port: 8000 }, pageHtml: bigPage, title: 'big' });
  await tick(40);
  const bigGrab = grabVia(big);
  check(bigGrab && bigGrab.html.length <= N, `DP_GRAB 也截断到 <=${N}（实际 ${bigGrab ? bigGrab.html.length : 0}）`);
  wrapOf(big).querySelector('.dp-btn').emit('click');
  await tick(40);
  const bp = big.cap.payloads[0] || {};
  check(bp.html && bp.html.length <= N, `payload.html 截断到 <=${N}（实际 ${bp.html ? bp.html.length : 0}）`);

  /* ---------------- ⑥ 结果文案与按钮态 ---------------- */
  section('⑥ 结果提示与按钮态');
  const okst = loadContentScript({ ping: { online: true, port: 8000 }, onCollect: () => OK_RESULT });
  await tick(40);
  const ow = wrapOf(okst);
  ow.querySelector('.dp-btn').emit('click');
  await tick(40);
  let toast = ow.querySelector('.dp-toast');
  check(toast.className.indexOf('show') >= 0 && toast.className.indexOf('ok') >= 0,
        '成功 → 提示条展开且用 ok 配色', toast.className);
  check(toast.textContent.indexOf('评分 75') >= 0, '提示里有评分', toast.textContent);
  check(toast.textContent.indexOf('重点客户') >= 0, '提示里有评级');
  check(toast.textContent.indexOf('sales@acme-bags.com') >= 0, '提示里有邮箱');
  check(toast.textContent.indexOf('+49 30 1234') >= 0, '提示里有电话');
  check(toast.textContent.indexOf('第 3 级') >= 0, '提示里说明了第几级抓取', toast.textContent);
  check(toast.textContent.indexOf('升级到浏览器') >= 0, '升级路径有额外标注');
  check(ow.querySelector('.dp-btn').className.indexOf('is-ok') >= 0, '按钮切成成功色');

  const dupst = loadContentScript({ ping: { online: true, port: 8000 },
    onCollect: () => ({ ok: true, added: false, existed: true, row: { url: 'https://acme-bags.com/a?x=1' } }) });
  await tick(40);
  const dw = wrapOf(dupst);
  dw.querySelector('.dp-btn').emit('click');
  await tick(40);
  toast = dw.querySelector('.dp-toast');
  check(toast.className.indexOf('dup') >= 0, '已在库 → 用 dup 配色', toast.className);
  check(toast.textContent.indexOf('已在客户库') >= 0, '文案说明已在库', toast.textContent);
  check(toast.textContent.indexOf('acme-bags.com') >= 0 && toast.textContent.indexOf('?x=1') < 0,
        '文案里只给域名，不糊一长串 URL', toast.textContent);
  check(dw.querySelector('.dp-btn').className.indexOf('is-dup') >= 0, '按钮切成灰色');

  const errst = loadContentScript({ ping: { online: true, port: 8000 },
    onCollect: () => ({ ok: false, msg: '没找到本机「谷歌客户开发工具」' }) });
  await tick(40);
  const ew = wrapOf(errst);
  ew.querySelector('.dp-btn').emit('click');
  await tick(40);
  toast = ew.querySelector('.dp-toast');
  check(toast.className.indexOf('err') >= 0, '失败 → 用 err 配色');
  check(toast.textContent.indexOf('没找到本机') >= 0, '失败原因原样透出', toast.textContent);
  check(ew.querySelector('.dp-btn').className.indexOf('is-err') >= 0, '按钮切成红色');

  const nost = loadContentScript({ ping: { online: true, port: 8000 },
    onCollect: () => ({ ok: true, added: true, tier: 1,
      row: { url: 'https://x.com', title: 'X', emails: [], phones: [],
             score: 20, rating: '观察', industry: '' } }) });
  await tick(40);
  const nw = wrapOf(nost);
  nw.querySelector('.dp-btn').emit('click');
  await tick(40);
  toast = nw.querySelector('.dp-toast');
  check(toast.textContent.indexOf('未抓到') >= 0 &&
        (toast.textContent.match(/未抓到/g) || []).length === 2,
        '邮箱电话都没抓到时，两行都写「未抓到」', toast.textContent);
  check(toast.textContent.indexOf('行业') < 0, '行业为空时不显示行业行', toast.textContent);

  /* ---------------- ⑦ DP_RESULT：右键菜单/popup 的结果也要在这页弹 ---------------- */
  section('⑦ DP_RESULT：右键菜单与 popup 触发的采集，结果回灌到页面');
  const rs = loadContentScript({ ping: { online: true, port: 8000 } });
  await tick(40);
  pushResult(rs, OK_RESULT);
  await tick(20);
  const rw = wrapOf(rs);
  check(!!rw && rw.querySelector('.dp-toast').textContent.indexOf('评分 75') >= 0,
        '收到 DP_RESULT → 页面就地弹出结果');
  const rsOff = loadContentScript({ settings: Object.assign({}, DEFAULT_SETTINGS, { fabEnabled: false }),
                                    ping: { online: true, port: 8000 } });
  await tick(40);
  pushResult(rsOff, OK_RESULT);
  await tick(20);
  check(hostOf(rsOff) === null, '设置里关了悬浮按钮 → DP_RESULT 不会强行把按钮挂出来');

  /* ---------------- ⑧ 「在这个网站上隐藏」 ---------------- */
  section('⑧ × 隐藏：写 storage 并摘掉节点');
  const hst = loadContentScript({ ping: { online: true, port: 8000 } });
  await tick(40);
  const hhost = hostOf(hst);
  wrapOf(hst).querySelector('.dp-hide').emit('click');
  await tick(20);
  check(hst.cap.storage['dpHide:acme-bags.com'] === true,
        '写入 dpHide:acme-bags.com = true', JSON.stringify(hst.cap.storage));
  check(hhost.parent === null, '宿主节点被摘掉（按钮当场消失）');

  console.log('\n' + '='.repeat(62));
  if (fails) { console.log(`FAIL ${fails} / ${checks}`); process.exit(1); }
  console.log(`ALL PASS (${checks} checks) —— content.js 运行时行为符合预期`);
  process.exit(0);
})();
