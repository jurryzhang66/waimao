/* popup.js 运行时冒烟测试（Node + 最小 DOM 桩，不联网、不开浏览器）。
 *
 * 为什么要桩测这一块：popup 是「用户唯一能看见采集结果」的地方，它的风险点全都
 * 不是「好不好看」，而是这几条在无头环境里恰恰能用桩精确断言的：
 *   ① 「本轮采集明细」两种 kind（added 完整行 / existed 只有 title+url）渲染口径；
 *   ② 状态行四个分支（进行中 / 上一轮已生成 / 未开始 / 保存失败）与按钮可用态；
 *   ③ **后台不认识 DP_MANUAL_STATE 时**（= 扩展没重新加载，service worker 还是旧代码）
 *      必须显示红字原因、且**不能把已有明细清空**、按钮必须禁用；
 *      —— 这一幕真实发生过：用户采完后看到「0 条 + 未知消息：DP_MANUAL_STATE」，
 *         以为采集失败。这里把它固化成断言。
 *   ④ 明细「只有内容变化才重建」（否则每秒轮询会重置滚动位置、闪烁）；
 *   ⑤ 结束后台的五个返回分支（pending / saved / 空轮 / 失败 / 无应答）；
 *   ⑥ 轮询间隔与 pagehide 停止；⑦ 四个链接的去向；
 *   ⑧ 删除单条（行尾 ✕）：confirm 取消不发请求 / 确认后发 DP_SESSION_DELETE / 回执与徽章 /
 *      后端拒绝与后台无应答的原因都必须留在结果行（不能被随后的 refreshSession 吃掉）/
 *      点没有 data-rid 的地方不动作。
 *
 * 至于「面板长得对不对」——那必须人工加载扩展看，桩测不碰像素。
 *
 * 运行：node .workbuddy/_smoke_ext_popup.js      （EXIT 0 = 全过）
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const EXT = path.join(__dirname, '..', 'extension');
const POPUP_HTML = fs.readFileSync(path.join(EXT, 'popup.html'), 'utf8');
const POPUP_JS = fs.readFileSync(path.join(EXT, 'popup.js'), 'utf8');

let fails = 0, checks = 0;
function check(cond, label, detail) {
  checks++;
  if (cond) console.log('  OK   ' + label);
  else { fails++; console.log('  FAIL ' + label + (detail ? '  -- ' + detail : '')); }
}
function section(t) { console.log('\n========== ' + t + ' =========='); }
function tick(ms) { return new Promise((r) => setTimeout(r, ms == null ? 0 : ms)); }
async function waitFor(cond, ms) {
  const end = Date.now() + (ms || 1000);
  while (Date.now() < end) { if (cond()) return true; await tick(2); }
  return cond();
}
// popup 里一次交互会串好几个 await send(...)（每次 send 都走一个 setTimeout 0），
// 所以不能只等「按钮 disabled=false」——那太早，后面的 DP_STATE / 明细拉取还没发出去。
async function settle(ms) { await tick(ms == null ? 80 : ms); }

/* ================= 最小 DOM 桩 ================= */

class El {
  constructor(id) {
    this.id = id;
    this.className = '';
    this.textContent = '';
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = '';
    this.style = {};
    this.scrollTop = 0;
    this.scrollHeight = 480;
    this._html = '';
    this._writes = 0;          // innerHTML 被写入的次数（用来验「不变化就不重建」）
    this._ih = [];             // insertAdjacentHTML 记录
    this._listeners = {};
  }
  set innerHTML(v) { this._writes++; this._html = String(v); }
  get innerHTML() { return this._html; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  // emit(type, extra)：extra 用来伪造事件对象。删除那条链路要 e.target.closest('[data-rid]')，
  // 桩里不必实现 closest —— 测试直接传一个带 closest 的假 target 即可（见 ⑪ 段）。
  emit(type, extra) {
    const ev = Object.assign({ preventDefault() {} }, extra || {});
    (this._listeners[type] || []).forEach((f) => f(ev));
  }
  insertAdjacentHTML(pos, html) { this._ih.push([pos, html]); }
}

const ELS = {};
function el(id) {
  if (!ELS[id]) ELS[id] = new El(id);
  return ELS[id];
}
// 元素表**从 popup.html 里解析出来**，popup.html 加了新 id 而桩里没登记会立刻报错，
// 而不是安静地变成 null（那会一路 TypeError 到用户脸上）。
const HTML_IDS = [...POPUP_HTML.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
HTML_IDS.forEach(el);
// 再把 popup.html 里写死的初始文案灌进桩元素。必须做：finishSession 会先读
// btn.textContent 当「原文」、结束后再还原 —— 桩里没有这段文本，还原就验不出来
// （实测踩过：报「按钮文案已还原」FAIL，其实是桩的 textContent 一开始就是空串）。
for (const m of POPUP_HTML.matchAll(/<[a-zA-Z0-9]+[^>]*?\bid="([^"]+)"[^>]*?>([^<]*)</g)) {
  const t = m[2].trim();
  if (t) el(m[1]).textContent = t;
}
const FINISH_LABEL = el('btnFinish').textContent;    // 还原断言拿它当基准
const COLLECT_LABEL = el('btnCollect').textContent;

const WINDOW_LISTENERS = {};
const document = {
  getElementById(id) {
    if (!ELS[id]) throw new Error('popup.js 取了 popup.html 里不存在的 id：' + id);
    return ELS[id];
  },
};
let CONFIRM_RETURN = true;             // window.confirm 的桩返回值（⑪ 段会改）
const window = {
  addEventListener(type, fn) { (WINDOW_LISTENERS[type] = WINDOW_LISTENERS[type] || []).push(fn); },
  confirm() { return CONFIRM_RETURN; },
};
function emitWindow(type) {
  (WINDOW_LISTENERS[type] || []).forEach((f) => f({}));
}

/* ================= chrome 桩 ================= */

const SENT = [];                    // 所有发往 background 的消息（按时间序）
const MSGS = [];                    // 同上，但留整个消息体（验 DP_SETTINGS_SET 的 patch 内容）
const CREATED = [];                 // chrome.tabs.create 的 url
let optionsOpened = 0;
let alerts = [];
const HANDLERS = {};                // type -> (msg) => 返回值 | Promise
const TIMERS = [];                  // 被 setInterval 注册的（fn, ms）
let timerSeq = 0;
const aliveTimers = new Set();

function setHandler(type, fn) { HANDLERS[type] = fn; }

const chrome = {
  runtime: {
    lastError: null,
    sendMessage(msg, cb) {
      SENT.push(msg.type);
      MSGS.push(msg);
      const h = HANDLERS[msg.type];
      const out = h ? h(msg) : undefined;
      Promise.resolve(out).then((v) => setTimeout(() => cb(v === undefined ? null : v), 0));
    },
    openOptionsPage() { optionsOpened++; },
  },
  tabs: {
    query(_q, cb) { setTimeout(() => cb([{ url: ACTIVE_URL }]), 0); },
    create(o) { CREATED.push(o.url); },
  },
};

let ACTIVE_URL = 'https://leasidepets.com/';

function fakeSetInterval(fn, ms) {
  const id = ++timerSeq;
  TIMERS.push({ id, fn, ms });
  aliveTimers.add(id);
  return id;
}
function fakeClearInterval(id) { aliveTimers.delete(id); }

/* ================= 状态工厂 ================= */

function row(o) {
  return Object.assign({
    title: '', url: '', emails: [], phones: [], contact_url: '', score: null,
    rating: '', snippet: '', formula: '[手动采集] x', country: '德国', industry: '宠物用品',
    kind: 'added',
  }, o);
}
function mkState(o) {
  return Object.assign({
    ok: true, online: true, port: 8000,
    running: false, stop: false, total: 0, done: 0, current: '',
    added: 0, existed: 0, failed: 0, upgraded: 0,
    session_active: false, session_started_at: 0, session_rows: [],
    session_industry: '', session_country: '', session_excel: '', session_error: '',
    session_finish_pending: false, ext_last_seen: 0, recent: [],
  }, o || {});
}
const R1 = row({ title: 'Leaside Pets', url: 'https://leasidepets.com/',
  emails: ['leasidepets@gmail.com', 'info@leasidepets.com'], phones: ['(416) 546 3152'], score: 65, rating: '普通客户' });
const R2 = row({ title: 'Trash Bag Wholesale GmbH', url: 'https://flatbag-maker.de/',
  emails: ['sales@flatbag-maker.de'], score: 75, rating: '重点客户' });
const R3 = { kind: 'existed', title: 'Trash Bags Wholesale Supplier', url: 'https://plasticbagpc.com/' };
const R4 = row({ title: 'No Mail Co', url: 'https://nomail.example.com/', score: 30, rating: '普通客户' });

let STATE = mkState({ session_active: true, session_industry: '宠物用品', session_country: '德国',
  session_rows: [R1, R2, R3], added: 2, existed: 1 });

/* ================= 加载真 popup.js ================= */

const sandbox = {
  console, URL, Promise, Object, Array, String, Number, Boolean, JSON, Math, Date, Error,
  RegExp, Map, Set, isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent,
  setTimeout, clearTimeout, document, window, chrome,
  setInterval: fakeSetInterval, clearInterval: fakeClearInterval,
  alert(m) { alerts.push(String(m)); },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 默认 handler
setHandler('DP_STATE', () => ({
  ok: true, online: true, port: 8000,
  tool: { running: false, manual_running: false },
  settings: { industry: '宠物用品', country: '德国', upgrade: false },
  last: null,
}));
setHandler('DP_KEYWORDS', () => ({ ok: true, names: ['塑料包装袋', '宠物用品'] }));
setHandler('DP_MANUAL_STATE', () => STATE);
setHandler('DP_URLS', () => ({ ok: true, base: 'http://127.0.0.1:8000',
  manual: 'http://127.0.0.1:8000/manual', home: 'http://127.0.0.1:8000/',
  db: 'http://127.0.0.1:8000/db' }));
setHandler('DP_FORGET_PORT', () => ({ ok: true, online: true, port: 8000, tool: {} }));
setHandler('DP_SETTINGS_SET', () => ({ ok: true }));
setHandler('DP_COLLECT_TAB', () => ({
  ok: true, added: true, existed: false, tier: 1, upgraded: false, row: R1,
  msg: '',
}));
setHandler('DP_SESSION_FINISH', () => ({ ok: true, saved: true, rows: 2, file: 'output/宠物用品-20260930_0100-德国.xlsx' }));

(async function main() {
  vm.runInContext(POPUP_JS, sandbox, { filename: 'popup.js' });
  await waitFor(() => TIMERS.length > 0, 1500);      // 等 init() 跑完（末尾 startPolling）

  section('① 初始化：连接状态 / 行业下拉 / 轮询启动');
  check(/已连接 127\.0\.0\.1:8000/.test(el('connText').textContent),
        '连接状态显示真实端口', el('connText').textContent);
  check(el('dot').className === 'dot on', '在线时指示灯为 on', el('dot').className);
  const selHtml = el('industry')._ih.map((x) => x[1]).join('');
  check(el('industry')._ih.length === 2 && /value="塑料包装袋"/.test(selHtml),
        '行业下拉从 /api/keywords 动态追加（不硬编码枚举）', JSON.stringify(el('industry')._ih));
  check(el('country').value === '德国', '国家输入框回填了记住的值', el('country').value);
  check(el('upgrade').checked === false, 'upgrade=false 时复选框不勾', String(el('upgrade').checked));
  // 「记住上面的行业/国家」默认勾上：桩里的 settings 没带 remember（= 没存过）→ 必须是勾着的
  check(el('remember').checked === true,
        '「记住上面的行业/国家」没存过 → 默认勾上', String(el('remember').checked));
  check(SENT.filter((t) => t === 'DP_MANUAL_STATE').length >= 1,
        'init 里先拉了一次本轮明细', SENT.join(','));
  check(el('btnCollect').textContent === COLLECT_LABEL,
        '采集按钮文案与 popup.html 一致（popup.js 里的字面量没写错）', el('btnCollect').textContent);
  check(/结束并生成 Excel/.test(FINISH_LABEL),
        '结束按钮的 HTML 原文就是「🏁 结束并生成 Excel」', FINISH_LABEL);
  check(TIMERS.length === 1 && TIMERS[0].ms === 1000, '轮询间隔 1000ms',
        TIMERS.map((t) => t.ms).join(','));
  check(el('btnFinish')._listeners.click && el('btnCollect')._listeners.click,
        '两个主按钮都绑了 click');

  section('② 明细渲染：added / existed 两种 kind');
  const L = el('sessList');
  check(el('sessCount').textContent === '有效 2 / 共 3',
        '徽章报两组数「有效 2 / 共 3」', el('sessCount').textContent);
  // ⚠️ 别用 /class="li/ 数条目：li-top / li-idx / li-site / li-score / li-sub / li-mail / li-phone
  //    全都以 li 开头，会数出 8 倍。只认行容器本身。
  const itemCount = (u) => (u.match(/class="li"|class="li li-old"/g) || []).length;
  check(itemCount(L.innerHTML) === 3, '渲染出 3 个条目', String(itemCount(L.innerHTML)));
  check(/leasidepets\.com/.test(L.innerHTML) && /flatbag-maker\.de/.test(L.innerHTML),
        '站点显示为主机名（去掉 www.）');
  check(/<span class="mail">leasidepets@gmail\.com, info@leasidepets\.com<\/span>/.test(L.innerHTML),
        '有邮箱 → 绿色等宽 .mail，多邮箱用逗号分隔（不是斜杠）', '未命中 mail 片段');
  check(L.innerHTML.includes('65 分') && L.innerHTML.includes('75 分'), '显示评分');
  check(L.innerHTML.includes('电话未抓到'), '没电话的条目显示灰字「电话未抓到」');
  check(L.innerHTML.includes('已在客户库'), 'existed 渲染成「已在客户库」');
  check(/class="li li-old"/.test(L.innerHTML), 'existed 用 li-old 灰化', L.innerHTML.slice(0, 200));
  check(!/plasticbagpc[\s\S]{0,120}?分/.test(L.innerHTML), 'existed 那条不显示评分（后端没给 score）');
  check(el('sessEmpty').style.display === 'none', '有条目时空态隐藏', String(el('sessEmpty').style.display));
  check(/🟢 进行中/.test(el('sessStatus').textContent)
        && /有效 2 · 采集总数 3/.test(el('sessStatus').textContent)
        && /行业 宠物用品/.test(el('sessStatus').textContent)
        && /国家 德国/.test(el('sessStatus').textContent),
        '状态行=进行中+两组数+口径', el('sessStatus').textContent);
  // ⚠️ 必须报**两组数**：「有效数」（真正入库的新客户 ＝ 结果 Excel 行数）与
  //    「采集总数」（明细行数 ＝ 新增 + 已在库）。只报一个总数会被当成成功数
  //    （用户点名要改；实测踩过：已采 17 条、表里 13 行）。
  check(/有效 2 · 采集总数 3 · 已在库 1/.test(el('sessStatus').textContent),
        '状态行把「有效 / 采集总数 / 已在库」一起报出来',
        el('sessStatus').textContent);
  check(/有效 2 条 \/ 采集总数 3 条 = 新增 2 \+ 已在库 1/.test(String(el('sessCount').title || '')),
        '徽章悬停给出「有效 / 采集总数 = 新增 + 已在库」的算式', String(el('sessCount').title));
  check(el('sessStatus').className === 'live-status', '状态行不是错误态', el('sessStatus').className);
  check(el('btnFinish').disabled === false, '本轮进行中 → 结束按钮可用');
  check(el('sessFile').textContent === '', '还没有结果文件/提示时该行为空', el('sessFile').textContent);

  section('③ 采一条 → 结果卡 + 明细立刻长出这条');
  STATE = mkState({ session_active: true, session_industry: '宠物用品', session_country: '德国',
    session_rows: [R1, R2, R3, R4], added: 3, existed: 1 });
  const writesBefore = L._writes;
  el('btnCollect').emit('click');
  await settle();
  check(/✓ 已采集入库/.test(el('rTitle').textContent), '结果卡显示成功', el('rTitle').textContent);
  check(el('resultCard').hidden === false, '结果卡已展开');
  check(/leasidepets@gmail\.com/.test(el('rBody').innerHTML), '结果卡里带邮箱');
  check(SENT.includes('DP_COLLECT_TAB'), '发了 DP_COLLECT_TAB');
  check(el('btnCollect').textContent === COLLECT_LABEL,
        '采集完成后按钮文案还原成 popup.html 的原文', el('btnCollect').textContent);
  check(SENT[SENT.length - 1] === 'DP_MANUAL_STATE',
        'collect 结束后主动补拉一次明细（不等下一次轮询）', SENT.slice(-3).join(','));
  check(L._writes > writesBefore, '明细被重建', `writes ${writesBefore} → ${L._writes}`);
  check(el('sessCount').textContent === '有效 3 / 共 4', '徽章变「有效 3 / 共 4」', el('sessCount').textContent);
  check(L.innerHTML.includes('nomail.example.com') && L.innerHTML.includes('邮箱未抓到'),
        '新条目进来，且无邮箱显示「邮箱未抓到」');
  check(L.scrollTop === L.scrollHeight && L.scrollTop > 0, '自动滚到最新一条', String(L.scrollTop));

  // ③b 「记住」勾着 → 三个值回写设置；取消勾选 → 只回写 remember=false，三个值一个都不写
  const patchOf = () => ((MSGS.filter((m) => m.type === 'DP_SETTINGS_SET').pop() || {}).patch) || {};
  const p1 = patchOf();
  check(p1.remember === true && p1.country === '德国' && p1.upgrade === false,
        '默认勾着「记住」→ 采集时把行业/国家/升级一并写回设置', JSON.stringify(p1));
  el('remember').checked = false;
  el('btnCollect').emit('click');
  await settle();
  const p2 = patchOf();
  check(p2.remember === false && !('country' in p2) && !('industry' in p2),
        '取消勾选 → 只回写 remember=false，不写行业/国家（临时换一次不该被永久记住）', JSON.stringify(p2));
  el('remember').checked = true;
  await settle();

  // ③c 国家/行业「一改就立刻写回设置」—— 悬浮按钮 / 右键菜单读的就是这份设置，看不到输入框。
  //     这是用户实测的 bug：改完国家直接点悬浮按钮，本轮仍被记成上一轮的国家。
  const setCount = () => MSGS.filter((m) => m.type === 'DP_SETTINGS_SET').length;
  const c0 = setCount();
  el('country').value = '新加坡';
  el('country').emit('input');
  await settle();
  check(setCount() === c0 + 1 && patchOf().country === '新加坡',
        '改国家 → 立刻写回设置（不用按采集按钮）', JSON.stringify(patchOf()));
  el('industry').value = '塑料包装袋';
  el('industry').emit('change');
  await settle();
  check(patchOf().industry === '塑料包装袋', '改行业 → 立刻写回设置', JSON.stringify(patchOf()));
  // 不勾「记住」也照写「本轮用的值」（悬浮按钮还得靠它）；「记住」只管下次打开预不预填
  el('remember').checked = false;
  el('country').value = '法国';
  el('country').emit('input');
  await settle();
  check(patchOf().country === '法国',
        '取消「记住」也即时回写本轮值（悬浮按钮读它）', JSON.stringify(patchOf()));
  el('remember').checked = true;
  el('country').value = '德国';
  el('industry').value = '宠物用品';
  await settle();

  section('④ 内容没变就别重建（否则每秒轮询会闪、会重置滚动）');
  el('btnCollect').emit('click');
  await settle();
  const writesStable = L._writes;
  TIMERS[0].fn();
  await settle(40);
  check(L._writes === writesStable, '同样的 session_rows → innerHTML 不重写',
        `writes ${writesStable} → ${L._writes}`);
  check(aliveTimers.has(TIMERS[0].id), '轮询 tick 后定时器仍在（不是一次性的）');

  section('⑤ ⚠️ 后台不认识 DP_MANUAL_STATE（扩展没重新加载 / service worker 是旧代码）');
  // 这一幕真实发生过：用户采完看到「0 条 + 未知消息：DP_MANUAL_STATE」，以为采集失败。
  setHandler('DP_MANUAL_STATE', () => ({ ok: false, msg: '未知消息：DP_MANUAL_STATE' }));
  const writesErr = L._writes;
  const htmlErr = L.innerHTML;
  TIMERS[0].fn();
  await tick(30);
  check(el('sessStatus').className === 'live-status err', '状态行转红', el('sessStatus').className);
  check(el('sessStatus').textContent === '未知消息：DP_MANUAL_STATE',
        '把后台给的原因原样显示出来（好定位）', el('sessStatus').textContent);
  check(el('btnFinish').disabled === true, '拿不到状态时结束按钮必须禁用（不能瞎点）');
  check(L._writes === writesErr && L.innerHTML === htmlErr,
        '⚠️ 绝不能因为一次读失败就把已有明细清空', `writes ${writesErr} → ${L._writes}`);

  section('⑥ 后台完全没应答（send 解析为 null）');
  setHandler('DP_MANUAL_STATE', () => null);
  TIMERS[0].fn();
  await tick(30);
  check(el('sessStatus').className === 'live-status err', '状态行红字');
  check(el('sessStatus').textContent === '读不到本机工具', '给出可理解的原因', el('sessStatus').textContent);
  check(el('btnFinish').disabled === true, '按钮禁用');

  section('⑦ 结束本轮：各返回分支（refreshSession 会用后端状态收尾）');
  const XLSX = 'output/宠物用品-20260930_0100-德国.xlsx';
  STATE = mkState({ session_active: true, session_industry: '宠物用品', session_country: '德国',
    session_rows: [R1, R2], added: 2 });
  setHandler('DP_MANUAL_STATE', () => STATE);
  TIMERS[0].fn();
  await settle(40);
  check(el('btnFinish').disabled === false, '恢复后按钮可用（前置条件）');

  // 7a 成功：后端关轮 + 记下文件名 → 状态行与结果行都指向这份文件
  setHandler('DP_SESSION_FINISH', () => ({ ok: true, saved: true, rows: 2, file: XLSX }));
  el('btnFinish').emit('click');
  STATE = mkState({ session_active: false, session_excel: XLSX, session_rows: [],
                    added: 5, existed: 2 });
  await settle();
  check(el('sessFile').textContent.includes(XLSX), '结束后显示生成的 Excel 文件名',
        el('sessFile').textContent);
  check(/本轮写入 5 行新客户/.test(el('sessFile').textContent)
        && /另有 2 条已在客户库/.test(el('sessFile').textContent),
        '结果行说清「表里写了几行、为什么比已采数少」', el('sessFile').textContent);
  check(/✅ 上一轮已生成结果文件/.test(el('sessStatus').textContent), '状态行转「上一轮已生成」',
        el('sessStatus').textContent);
  check(el('btnFinish').textContent === FINISH_LABEL, '按钮文案已还原',
        el('btnFinish').textContent);
  check(el('btnFinish').disabled === true, '本轮已关 → 按钮禁用');
  check(el('sessCount').textContent === '有效 0 / 共 0', '本轮清空后徽章归零', el('sessCount').textContent);
  check(el('sessEmpty').style.display === 'block', '空态重新显示', String(el('sessEmpty').style.display));

  // 7b 点击过程中：立刻禁用 + 换进度文案
  STATE = mkState({ session_active: true, session_rows: [R1] });
  TIMERS[0].fn();
  await settle(40);
  let slowResolve = null;
  setHandler('DP_SESSION_FINISH', () => new Promise((res) => { slowResolve = res; }));
  el('btnFinish').emit('click');
  await tick(10);
  check(el('btnFinish').disabled === true, '点下去立刻禁用（防重复提交）');
  check(el('btnFinish').textContent === '正在生成 Excel…', '按钮显示进度文案', el('btnFinish').textContent);
  slowResolve({ ok: true, saved: true, rows: 1, file: 'output/x.xlsx' });
  await settle();
  check(el('btnFinish').textContent === FINISH_LABEL, '回来后文案还原',
        el('btnFinish').textContent);
  check(el('btnFinish').disabled === false, '本轮仍开着 → 按钮恢复可用');

  // 7c 空轮：saved=false 不产文件，属正常，不能报错
  STATE = mkState({ session_active: false });
  setHandler('DP_SESSION_FINISH', () => ({ ok: true, saved: false, rows: 0,
    msg: '本轮没有采到新客户，未生成结果文件' }));
  el('btnFinish').emit('click');
  await settle();
  check(/本轮没有采到新客户/.test(el('sessFile').textContent), '空轮给中性提示，不当失败',
        el('sessFile').textContent);
  check(!/⚠️/.test(el('sessStatus').textContent), '空轮不把状态行染红', el('sessStatus').textContent);

  // 7d 落盘失败：后端置 session_error 且**保留本轮** → 红字 + 按钮可重试
  STATE = mkState({ session_active: true, session_error: '保存失败：Permission denied',
    session_rows: [R1] });
  setHandler('DP_SESSION_FINISH', () => ({ ok: false, msg: '保存失败：Permission denied' }));
  el('btnFinish').emit('click');
  await settle();
  check(el('sessStatus').className === 'live-status err', '保存失败 → 状态行红字');
  check(/结果文件保存失败/.test(el('sessStatus').textContent), '提示可重试', el('sessStatus').textContent);
  check(el('sessFile').textContent === '保存失败：Permission denied', '结果行显示后端原始错误',
        el('sessFile').textContent);
  check(el('btnFinish').disabled === false, '保存失败后按钮仍可点（重试）');

  // 7e 批量还在跑：后端置 finish_pending、由 worker 收尾 → 提示必须留住
  STATE = mkState({ session_active: true, session_finish_pending: true, session_rows: [R1] });
  setHandler('DP_SESSION_FINISH', () => ({ ok: true, pending: true,
    msg: '正在停止批量并收尾，稍候会自动生成 Excel…' }));
  el('btnFinish').emit('click');
  await settle();
  check(/正在停止批量并收尾/.test(el('sessFile').textContent), '批量中结束 → 提示由 worker 收尾',
        el('sessFile').textContent);
  check(el('sessStatus').className === 'live-status', '收尾期间状态行不报错',
        el('sessStatus').textContent);

  // 7f 后台无应答：提前 return、不走刷新，提示必须一直留着
  setHandler('DP_SESSION_FINISH', () => null);
  el('btnFinish').emit('click');
  await settle();
  check(/关掉再打开这个面板重试/.test(el('sessFile').textContent), '后台无应答时给出重试指引',
        el('sessFile').textContent);
  check(el('btnFinish').disabled === false, '无应答后按钮恢复可点');

  // 7g 后端拒绝（如「没有进行中的本轮采集」）：原因不能被随后那次刷新吃掉
  STATE = mkState({});
  setHandler('DP_SESSION_FINISH', () => ({ ok: false, msg: '当前没有进行中的本轮采集，无需结束' }));
  el('btnFinish').emit('click');
  await settle();
  check(/无需结束/.test(el('sessFile').textContent),
        '后端拒绝的原因要留在结果行（不能被刷新覆盖成空白）', el('sessFile').textContent);

  section('⑧ 状态行四态回顾');
  const cases = [
    [mkState({ session_active: true, session_rows: [R1] }), /🟢 进行中/, 'live-status'],
    [mkState({ session_active: false, session_excel: 'output/a.xlsx' }), /✅ 上一轮已生成/, 'live-status'],
    [mkState({}), /本轮未开始/, 'live-status'],
    [mkState({ session_error: 'x' }), /保存失败/, 'live-status err'],
  ];
  for (const [st, re, cls] of cases) {
    setHandler('DP_MANUAL_STATE', () => st);
    TIMERS[0].fn();
    await tick(25);
    check(re.test(el('sessStatus').textContent) && el('sessStatus').className === cls,
          '状态行分支：' + String(re).replace(/[/^$\\]/g, ''), el('sessStatus').textContent);
  }

  section('⑨ 五个链接的去向');
  setHandler('DP_MANUAL_STATE', () => mkState({ session_active: true, session_rows: [R1] }));
  el('lnkManual').emit('click');
  await tick(40);
  check(CREATED.includes('http://127.0.0.1:8000/manual'), '「手动采集页」→ /manual', CREATED.join(','));
  el('lnkHome').emit('click');
  await tick(40);
  check(CREATED.includes('http://127.0.0.1:8000/'), '「自动搜索主页」→ /', CREATED.join(','));
  // /db 客户库查询页：走的是与上面两个链接同一条 toolUrls() 路径（popup 里零 fetch）
  el('lnkDb').emit('click');
  await tick(40);
  check(CREATED.includes('http://127.0.0.1:8000/db'), '「客户库查询」→ /db', CREATED.join(','));
  el('lnkOptions').emit('click');
  await tick(10);
  check(optionsOpened === 1, '「设置」→ 打开选项页', String(optionsOpened));
  const beforeAlerts = alerts.length;
  SENT.length = 0;
  el('lnkReprobe').emit('click');
  await tick(40);
  check(SENT.includes('DP_FORGET_PORT'), '「重新探测端口」发了 DP_FORGET_PORT', SENT.join(','));
  check(/已连接 127\.0\.0\.1:8000/.test(el('connText').textContent), '探测结果回写了连接状态',
        el('connText').textContent);
  check(alerts.length === beforeAlerts, '在线时点链接不弹 alert');

  section('⑩ 工具离线时：跳转要拦住并提示，不能给出坏 URL');
  setHandler('DP_URLS', () => null);
  const createdBefore = CREATED.length;
  el('lnkManual').emit('click');
  await tick(40);
  check(CREATED.length === createdBefore, '离线时不打开任何标签页', String(CREATED.length));
  check(alerts.length > beforeAlerts && /启动客户开发工具/.test(alerts[alerts.length - 1]),
        '改用 alert 告诉用户去启动工具', alerts[alerts.length - 1]);

  section('⑪ 删除单条：点行尾 ✕ → 明细 + 客户库双删（confirm 把关、原因留痕）');
  const RD1 = row({ rid: 1, title: 'Leaside Pets', url: 'https://leasidepets.com/',
    emails: ['leasidepets@gmail.com'], score: 65, rating: '普通客户' });
  const RD2 = row({ rid: 2, title: 'Flat Bag GmbH', url: 'https://flatbag-maker.de/',
    emails: ['sales@flatbag-maker.de'], score: 75, rating: '重点客户' });
  STATE = mkState({ session_active: true, session_industry: '宠物用品', session_country: '德国',
    session_rows: [RD1, RD2], added: 2 });
  setHandler('DP_MANUAL_STATE', () => STATE);
  TIMERS[0].fn();
  await settle(50);
  check(/data-rid="1"/.test(el('sessList').innerHTML) && /data-rid="2"/.test(el('sessList').innerHTML),
        '每行都带 data-rid（按行号删，不按 url）');
  check(/class="li-del"/.test(el('sessList').innerHTML), '每行都有 ✕ 删除钮');
  check((el('sessList').innerHTML.match(/✕/g) || []).length === 2,
        '一共两个 ✕（每行一个）', String((el('sessList').innerHTML.match(/✕/g) || []).length));

  // 桩里不必实现 closest —— 直接给一个会把它交出来的假 target
  const clickDel = (rid) => el('sessList').emit('click', {
    target: { closest: (s) => (s === '[data-rid]' ? { dataset: { rid: String(rid) } } : null) },
  });

  // 11a 用户在 confirm 里点「取消」→ 一个请求都不能发
  CONFIRM_RETURN = false;
  SENT.length = 0;
  clickDel(1);
  await settle();
  check(!SENT.includes('DP_SESSION_DELETE'), 'confirm 选取消 → 不发删除请求', SENT.join(','));

  // 11b 确认删除 → 发消息、结果行给回执、徽章跟随后端状态
  CONFIRM_RETURN = true;
  STATE = mkState({ session_active: true, session_industry: '宠物用品', session_country: '德国',
    session_rows: [RD2], added: 1 });
  setHandler('DP_SESSION_DELETE', () => ({ ok: true, deleted: 1, rows: 1,
    backup: '客户库_删除前_20260930_150000.sqlite3' }));
  SENT.length = 0;
  clickDel(1);
  await settle();
  check(SENT.includes('DP_SESSION_DELETE'), '确认后发了 DP_SESSION_DELETE', SENT.join(','));
  check(/已删除/.test(el('sessFile').textContent), '结果行给出删除回执', el('sessFile').textContent);
  check(/已备份/.test(el('sessFile').textContent), '回执里带上备份文件名', el('sessFile').textContent);
  check(el('sessCount').textContent === '有效 1 / 共 1', '徽章跟随后端状态变成「有效 1 / 共 1」', el('sessCount').textContent);
  check(/flatbag-maker\.de/.test(el('sessList').innerHTML)
        && !/leasidepets\.com/.test(el('sessList').innerHTML),
        '被删那条从列表消失、剩下那条还在', el('sessList').innerHTML.slice(0, 120));
  check(el('sessStatus').className === 'live-status', '删除不会把状态行染红', el('sessStatus').className);

  // 11c 后端拒绝（如「这条已不在本轮明细里」）→ 原因必须留在结果行，不能被刷新吃掉
  setHandler('DP_SESSION_DELETE', () => ({ ok: false,
    msg: '这条已不在本轮明细里（可能已被删除，或本轮已结束）' }));
  clickDel(1);
  await settle();
  check(/已不在本轮明细里/.test(el('sessFile').textContent),
        '后端拒绝的原因留在结果行（不会被刷新覆盖）', el('sessFile').textContent);

  // 11d 后台无应答 → 给重试指引
  setHandler('DP_SESSION_DELETE', () => null);
  clickDel(1);
  await settle();
  check(/关掉再打开这个面板重试/.test(el('sessFile').textContent), '后台无应答给重试指引',
        el('sessFile').textContent);

  // 11e 点到没有 data-rid 的地方（老数据/空白）→ 不动作
  SENT.length = 0;
  el('sessList').emit('click', { target: { closest: () => null } });
  await settle();
  check(!SENT.includes('DP_SESSION_DELETE'), '点空白/无 rid 的行不触发删除', SENT.join(','));

  section('⑫ 轮询纪律');
  check(TIMERS.length === 1, '只有一个轮询定时器（重复 init 不会叠加）', String(TIMERS.length));
  check(aliveTimers.has(TIMERS[0].id), '轮询在跑');
  emitWindow('pagehide');
  await tick(10);
  check(!aliveTimers.has(TIMERS[0].id), 'pagehide 时停掉轮询（popup 关掉后不留定时器）');

  console.log('\n==============================================================');
  if (fails) {
    console.log(`FAIL —— ${checks - fails}/${checks} 通过，${fails} 项失败`);
    process.exit(1);
  }
  console.log(`ALL PASS (${checks} checks) —— popup 的明细渲染/状态分支/结束流程/链接去向都符合预期`);
  process.exit(0);
})().catch((e) => {
  console.error('\n💥 测试自身崩了：', e && e.stack || e);
  process.exit(2);
});
