/* 外贸客户采集助手 —— background service worker（扩展的神经中枢）
 *
 * 三件事，缺一不可：
 *   ① 端口发现：本工具每次启动端口都可能不一样（Windows TCP 保留段每次开机漂移），
 *      所以逐个试 DP_PREFERRED_PORTS、用 /api/ping 的 app 字段确认身份，探到的端口缓存起来。
 *   ② 【唯一 fetch 出口】所有对 127.0.0.1 的请求都在这里发。
 *      ⚠️ 这是必须踩对的一步：内容脚本的 fetch 用的是**页面源**（https://某客户站），
 *         会走该页面的 CORS，被我们自己的严格 CORS（只回显 chrome-extension://）拒掉；
 *         而且 https 页面请求 http://127.0.0.1 还会撞 Private Network Access 限制。
 *         Service worker 的源是 chrome-extension://<id>，配合 host_permissions 才是正路。
 *   ③ 页面内容获取：优先问内容脚本要（它本来就在页面上，零额外权限），
 *      拿不到才用 chrome.scripting.executeScript 注入一次性函数兜底。
 *
 * 权限最小化：activeTab + scripting + contextMenus + storage。
 *   · 不用 notifications（采集结果用 toolbar 徽标 + 页面内小提示反馈，不打扰）
 *   · 不用 alarms（端口发现是「用时才探」）
 *   · host_permissions 只写 127.0.0.1 / localhost（match pattern 不含端口，一条覆盖所有端口）
 */
importScripts('ports.js');

const STORE_PORT = 'dpPort';            // 上次探到的端口（跨 SW 重启保留）
const STORE_SETTINGS = 'dpSettings';    // 用户默认值
const STORE_LAST = 'dpLastResult';      // 上次采集结果（popup 打开时回显）

const DEFAULTS = {
  industry: '',        // 默认行业；空 = 让后端自动判断
  country: '',         // 默认国家/地区
  upgrade: true,       // 秒级抓不到邮箱时，是否升级到 Chromium 完整抓
  remember: true,      // popup 上「记住上面的行业/国家」是否默认勾上（勾着才把下面三个值写回）
  fabEnabled: true,    // 是否在网页右下角显示「采集」悬浮按钮
  port: 0,             // 0 = 自动探测；非 0 = 优先用这个端口（用户手动指定）
};

const MENU_PAGE = 'dp-collect-page';
const MENU_LINK = 'dp-collect-link';

/* ================= 小工具 ================= */

/** 把 chrome.* 的回调式 API 包成 Promise。
 *  不用原生 Promise 支持是因为部分 API（tabs.query / sendMessage）的 Promise 形态到较晚
 *  的 Chrome 版本才有，回调式 + 这个包法在 96+ 全版本都稳。 */
function cb(fn) {
  return new Promise((resolve, reject) => {
    fn((...args) => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(args.length > 1 ? args : args[0]);
    });
  });
}

function storeGet(keys) { return cb((r) => chrome.storage.local.get(keys, r)); }
function storeSet(obj) { return cb((r) => chrome.storage.local.set(obj, r)); }

async function getSettings() {
  const o = await storeGet([STORE_SETTINGS]).catch(() => ({}));
  return Object.assign({}, DEFAULTS, (o && o[STORE_SETTINGS]) || {});
}

async function setSettings(patch) {
  const next = Object.assign({}, await getSettings(), patch || {});
  await storeSet({ [STORE_SETTINGS]: next });
  return next;
}

/* ================= 徽标反馈（替代通知，不打扰） ================= */

let _badgeTimers = {};

function badge(tabId, text, color) {
  if (tabId == null) return;
  try {
    chrome.action.setBadgeText({ text: text || '', tabId });
    if (color) chrome.action.setBadgeBackgroundColor({ color, tabId });
  } catch (e) { /* 标签页已关闭等，忽略 */ }
  if (text) {
    clearTimeout(_badgeTimers[tabId]);
    _badgeTimers[tabId] = setTimeout(() => badge(tabId, ''), 4000);
  }
}

/** 把结果也回传给页面里的内容脚本，让悬浮按钮就地弹个小提示（按钮没挂载就自动忽略）。 */
function toast(tabId, result) {
  if (tabId == null) return;
  try {
    chrome.tabs.sendMessage(tabId, { type: 'DP_RESULT', result }, () => void chrome.runtime.lastError);
  } catch (e) { /* 内容脚本不在，忽略 */ }
}

/* ================= ① 端口发现 ================= */

let _cache = null;   // { port, tool, at } —— SW 可能随时被回收，所以同时落 storage

async function ping(port) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), DP_PING_TIMEOUT_MS);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/ping`, {
      signal: ctl.signal,
      cache: 'no-store',
      credentials: 'omit',
    });
    if (!res.ok) return null;
    const d = await res.json();
    return (d && d.ok === true && d.app === DP_APP_ID) ? d : null;
  } catch (e) {
    return null;                       // 没监听 / 不是本工具 / 超时，一律当作「没有」
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 找出本工具在哪个端口。返回 { port, tool } 或 null。
 * 顺序：用户手动指定 → 上次探到的 → 候选表。全部并行探，按上面的优先级取第一个命中的
 *（本机拒绝连接是瞬间的，所以并行 9 个也只是百毫秒级，不需要串行省资源）。
 */
async function discover({ force = false } = {}) {
  if (!force && _cache && Date.now() - _cache.at < 15000) return _cache;

  const st = await getSettings();
  const o = await storeGet([STORE_PORT]).catch(() => ({}));
  const cands = [];
  if (st.port) cands.push(Number(st.port));
  if (o && o[STORE_PORT]) cands.push(Number(o[STORE_PORT]));
  DP_PREFERRED_PORTS.forEach((p) => cands.push(p));

  const uniq = [...new Set(cands.filter((p) => Number.isInteger(p) && p > 0 && p < 65536))];
  const hits = await Promise.all(uniq.map(async (p) => ({ port: p, tool: await ping(p) })));
  const hit = hits.find((h) => h.tool);

  if (!hit) {
    _cache = null;
    return null;
  }
  _cache = { port: hit.port, tool: hit.tool, at: Date.now() };
  await storeSet({ [STORE_PORT]: hit.port });
  return _cache;
}

async function forgetPort() {
  _cache = null;
  await storeSet({ [STORE_PORT]: 0 });
}

/* ================= ② 唯一 fetch 出口 =================
 * 全扩展对 127.0.0.1 的请求只有这几个函数：postCollect / fetchKeywords /
 * getManualState / finishManualSession。popup 与内容脚本里**一个 fetch 都不许有**
 * （`_check_ext.py` 的 D1 会硬查），它们只能 sendMessage 到这里代发。
 */

async function postCollect(payload) {
  const found = await discover();
  if (!found) {
    return {
      ok: false, offline: true,
      msg: '没找到本机「谷歌客户开发工具」。请先启动它（双击 启动客户开发工具.bat），'
         + '再回到这个网页点采集。',
    };
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), DP_COLLECT_TIMEOUT_MS);
  try {
    const res = await fetch(`http://127.0.0.1:${found.port}/api/collect`, {
      method: 'POST',
      // 自定义头 X-DP-Ext 是有意为之：它必然触发 CORS 预检，而后端只给
      // chrome-extension:// 来源发 ACAO —— 网页里伪造的请求连预检都过不去。
      headers: { 'Content-Type': 'application/json', 'X-DP-Ext': '1' },
      body: JSON.stringify(payload),
      signal: ctl.signal,
    });
    const d = await res.json().catch(() => null);
    if (!d) return { ok: false, msg: `本工具返回了非法响应（HTTP ${res.status}）` };
    return d;
  } catch (e) {
    if (e && e.name === 'AbortError') return { ok: false, msg: '采集超时（超过 60 秒），已放弃' };
    return { ok: false, msg: `请求本工具失败：${(e && e.message) || e}` };
  } finally {
    clearTimeout(timer);
  }
}

async function fetchKeywords() {
  const found = await discover();
  if (!found) return null;
  try {
    const res = await fetch(`http://127.0.0.1:${found.port}/api/keywords`, { cache: 'no-store' });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

/** 本轮手动采集的状态与明细。popup 的「本轮采集明细」卡就靠它。
 *
 *  返回体 = 后端 MANUAL_STATE（`running/done/total` 是批量语义；`added/existed/...` 与
 *  `session_*` 是本轮会话语义）+ 后端补的 `recent` 与 `now`。
 *  ⚠️ 失败一律降级成 {ok:false,...}，**不抛** —— popup 是每秒轮询的，抛异常会刷屏。
 */
async function getManualState() {
  const found = await discover();
  if (!found) {
    return { ok: false, offline: true, msg: '没找到本机「谷歌客户开发工具」，请先启动它' };
  }
  try {
    const res = await fetch(`http://127.0.0.1:${found.port}/api/manual/state`, {
      cache: 'no-store',
      credentials: 'omit',
    });
    if (!res.ok) return { ok: false, msg: `本轮明细接口返回 HTTP ${res.status}` };
    const d = await res.json();
    return Object.assign({ ok: true }, d || {});
  } catch (e) {
    return { ok: false, msg: `读取本轮明细失败：${(e && e.message) || e}` };
  }
}

/** 结束本轮手动采集：把本轮明细落成一份结果 Excel，并设为「最新结果文件」。
 *
 *  后端四种返回（popup 要分别处理）：
 *    {ok:true, pending:true, msg}         批量还在跑 → 置 stop，由 worker 的 finally 落盘
 *    {ok:true, saved:true, file, rows}    成功落盘，file 是相对路径（如 output/xx.xlsx）
 *    {ok:true, saved:false, msg}          本轮回合没有新客户（空轮不产文件，属正常）
 *    {ok:false, msg}                      保存失败（多半 Excel 被占用）→ 数据保留可重试
 */
async function finishManualSession() {
  const found = await discover();
  if (!found) {
    return { ok: false, offline: true, msg: '没找到本机「谷歌客户开发工具」，请先启动它' };
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), DP_COLLECT_TIMEOUT_MS);
  try {
    const res = await fetch(`http://127.0.0.1:${found.port}/api/manual/session/finish`, {
      method: 'POST',
      // X-DP-Ext 后端不校验（门禁只加在 /api/collect），写上是为了与 postCollect 同款、
      // 并强制走 CORS 预检，跟其余扩展请求保持一致的调用口径。
      headers: { 'Content-Type': 'application/json', 'X-DP-Ext': '1' },
      body: JSON.stringify({}),
      signal: ctl.signal,
    });
    const d = await res.json().catch(() => null);
    if (!d) return { ok: false, msg: `本工具返回了非法响应（HTTP ${res.status}）` };
    return d;
  } catch (e) {
    if (e && e.name === 'AbortError') return { ok: false, msg: '生成 Excel 超时，已放弃' };
    return { ok: false, msg: `生成 Excel 失败：${(e && e.message) || e}` };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 删掉本轮明细里的某一条，**并同时从客户库删掉它**（后端删除前会自动备份客户库）。
 * 返回后端原样响应：{ok, deleted, rows, backup} 或 {ok:false, msg}
 *   deleted=1 客户库真删掉了 1 条；deleted=0 库里本来就没有这条（只从明细移除）
 *   backup  本次生成的备份文件名；空串表示被节流了（本轮已有备份）
 * 用法：popup 的「本轮明细」每行 ✕。popup 自己不许 fetch（唯一出口纪律），必须走这里。
 */
async function deleteManualSessionRow(rid) {
  const found = await discover();
  if (!found) {
    return { ok: false, offline: true, msg: '没找到本机「谷歌客户开发工具」，请先启动它' };
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), DP_COLLECT_TIMEOUT_MS);
  try {
    const res = await fetch(`http://127.0.0.1:${found.port}/api/manual/session/delete`, {
      method: 'POST',
      // 同 finishManualSession：X-DP-Ext 后端不校验（门禁只在 /api/collect），写上是为了
      // 与其余扩展请求同款并强制走 CORS 预检。body 里的 rid 必须在，否则后端一律拒绝。
      headers: { 'Content-Type': 'application/json', 'X-DP-Ext': '1' },
      body: JSON.stringify({ rid }),
      signal: ctl.signal,
    });
    const d = await res.json().catch(() => null);
    if (!d) return { ok: false, msg: `本工具返回了非法响应（HTTP ${res.status}）` };
    return d;
  } catch (e) {
    if (e && e.name === 'AbortError') return { ok: false, msg: '删除超时，已放弃' };
    return { ok: false, msg: `删除失败：${(e && e.message) || e}` };
  } finally {
    clearTimeout(timer);
  }
}

/* ================= ③ 取页面内容 ================= */

/** 注入到页面里跑的一次性函数。
 *  ⚠️ 用 chrome.scripting 的 func 形式注入时，这个函数会被**序列化**后送到页面执行，
 *     所以它不能引用外面任何变量/常量 —— 下面全部是局部字面量，这是刻意的。 */
function grabPage() {
  try {
    var MAX = 400000;                       // 后端 MAX_PAGE_HTML=500000，这里留点余量
    var root = document.documentElement;
    if (!root) return { ok: false, msg: '页面还没有 DOM' };
    var clone = root.cloneNode(true);
    // 与后端 _sanitize_page_html 剥掉的是同一批标签，保持口径一致
    var junk = clone.querySelectorAll('script,style,noscript,svg,template');
    for (var i = 0; i < junk.length; i++) junk[i].remove();
    var html = '<!DOCTYPE html>' + clone.outerHTML;
    if (html.length > MAX) html = html.slice(0, MAX);
    return { ok: true, url: location.href, title: document.title || '', html: html };
  } catch (e) {
    return { ok: false, msg: String((e && e.message) || e), url: location.href, title: document.title || '', html: '' };
  }
}

function injectable(url) { return /^https?:\/\//i.test(url || ''); }

async function grabFromTab(tabId) {
  // ① 先问内容脚本 —— 它已经在页面上跑着，不需要任何额外权限（浮窗按钮那条路走的就是它）
  try {
    const r = await cb((done) => chrome.tabs.sendMessage(tabId, { type: 'DP_GRAB' }, done));
    if (r && r.ok && r.url) return r;
  } catch (e) { /* 内容脚本不在（chrome:// 页、扩展页、注入失败）→ 走兜底 */ }
  // ② 兜底：一次性注入（依赖 activeTab —— 点图标/右键菜单都会授予该标签页的临时权限）
  try {
    const out = await cb((done) => chrome.scripting.executeScript({ target: { tabId }, func: grabPage }, done));
    const first = Array.isArray(out) ? out[0] : out;
    if (first && first.result) return first.result;
  } catch (e) {
    return { ok: false, msg: '这个页面不允许注入脚本（chrome:// 与扩展商店页面都禁止采集）' };
  }
  return { ok: false, msg: '没能读取页面内容' };
}

/* ================= 采集主流程 ================= */

async function runCollect(tab, opts) {
  if (!tab || tab.id == null) return { ok: false, msg: '没有找到当前标签页' };
  const tabId = tab.id;
  if (!injectable(tab.url)) {
    badge(tabId, '!', '#d93025');
    return { ok: false, msg: '只能在普通网页（http/https）上采集' };
  }

  badge(tabId, '…', '#5f6368');
  const grabbed = await grabFromTab(tabId);
  if (!grabbed || !grabbed.ok) {
    badge(tabId, '!', '#d93025');
    return { ok: false, msg: (grabbed && grabbed.msg) || '读取页面失败' };
  }

  const st = await getSettings();
  const r = await postCollect({
    url: grabbed.url,
    title: grabbed.title,
    html: grabbed.html,
    industry: (opts && opts.industry) || st.industry || '',
    country: (opts && opts.country) || st.country || '',
    upgrade: (opts && typeof opts.upgrade === 'boolean') ? opts.upgrade : st.upgrade,
    product_words: (opts && opts.product_words) || null,
  });

  if (r && r.ok) badge(tabId, r.existed ? '=' : '✓', r.existed ? '#5f6368' : '#188038');
  else badge(tabId, '!', '#d93025');

  await storeSet({ [STORE_LAST]: { at: Date.now(), url: grabbed.url, result: r || null } });
  return r;
}

/* ================= 右键菜单 ================= */

function installMenus() {
  chrome.contextMenus.removeAll(() => {
    void chrome.runtime.lastError;
    chrome.contextMenus.create({
      id: MENU_PAGE,
      title: '采集本页为客户（外贸客户开发工具）',
      contexts: ['page'],
      documentUrlPatterns: ['http://*/*', 'https://*/*'],
    });
    // 顺手加一个链接菜单：翻搜索结果时不用点进去，直接在链接上右键就能采集
    chrome.contextMenus.create({
      id: MENU_LINK,
      title: '采集此链接网站为客户',
      contexts: ['link'],
    });
  });
}

chrome.runtime.onInstalled.addListener(installMenus);
chrome.runtime.onStartup.addListener(installMenus);

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === MENU_PAGE) {
    const r = await runCollect(tab);
    toast(tab && tab.id, r);
    return;
  }
  if (info.menuItemId === MENU_LINK) {
    const tabId = tab && tab.id;
    badge(tabId, '…', '#5f6368');
    // 链接这条路没有页面 HTML（用户还没打开那个站），交给后端走
    // 二级（requests 抓首页/联系页）→ 三级（升级 Chromium）抓
    const st = await getSettings();
    const r = await postCollect({
      url: info.linkUrl, title: info.selectionText || '', html: '',
      industry: st.industry || '', country: st.country || '', upgrade: st.upgrade,
    });
    if (r && r.ok) badge(tabId, r.existed ? '=' : '✓', r.existed ? '#5f6368' : '#188038');
    else badge(tabId, '!', '#d93025');
    await storeSet({ [STORE_LAST]: { at: Date.now(), url: info.linkUrl, result: r || null } });
    toast(tabId, r);
  }
});

/* ================= 消息路由 ================= */

async function stateReply() {
  const found = await discover();
  const st = await getSettings();
  const last = await storeGet([STORE_LAST]).catch(() => ({}));
  return {
    online: !!found,
    port: found ? found.port : 0,
    tool: found ? found.tool : null,
    settings: st,
    last: (last && last[STORE_LAST]) || null,
  };
}

async function urlsReply() {
  const found = await discover();
  if (!found) return { ok: false };
  const base = `http://127.0.0.1:${found.port}`;
  // db = 客户库查询页（第三个页面）。与 manual/home 同款拼接：端口由 discover() 实测得到，
  // 不写死 —— 用户机器上端口会漂移（见 客户开发工具.py 的 pick_port）。
  return { ok: true, base, manual: `${base}/manual`, home: `${base}/`, db: `${base}/db` };
}

async function activeTab() {
  const tabs = await cb((done) => chrome.tabs.query({ active: true, currentWindow: true }, done));
  return (tabs && tabs[0]) || null;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg.type !== 'string') return;
  (async () => {
    switch (msg.type) {
      case 'DP_PING':
        sendResponse(await stateReply());
        return;
      case 'DP_STATE':
        sendResponse(await stateReply());
        return;
      case 'DP_SETTINGS_GET':
        sendResponse(await getSettings());
        return;
      case 'DP_SETTINGS_SET':
        sendResponse(await setSettings(msg.patch));
        return;
      case 'DP_KEYWORDS': {
        const d = await fetchKeywords();
        sendResponse({ ok: !!d, names: d ? Object.keys(d) : [] });
        return;
      }
      case 'DP_URLS':
        sendResponse(await urlsReply());
        return;
      case 'DP_FORGET_PORT':
        await forgetPort();
        sendResponse(await stateReply());
        return;
      case 'DP_COLLECT_TAB': {
        const tab = await activeTab();
        const r = await runCollect(tab, msg.opts);
        toast(tab && tab.id, r);
        sendResponse(r);
        return;
      }
      case 'DP_COLLECT_PAYLOAD': {
        // 内容脚本自己点悬浮按钮那条路。2026-09 修复：以前它**既不设徽标也不写
        // STORE_LAST**（老注释说「页内已经弹了提示，徽标留给扩展发起的两条路」），
        // 结果是用户点完悬浮按钮、再打开扩展面板**什么都看不到**，以为采集失败了。
        // 现在三条入口一视同仁：都设徽标、都写 STORE_LAST。
        const r = await postCollect(msg.payload);
        const tabId = (sender && sender.tab && sender.tab.id != null) ? sender.tab.id : null;
        // 用 sender.tab.id 而不是 activeTab()：内容脚本从哪个标签页发的就反馈到哪个，不会串页
        if (tabId != null) {
          if (r && r.ok) badge(tabId, r.existed ? '=' : '✓', r.existed ? '#5f6368' : '#188038');
          else badge(tabId, '!', '#d93025');
        }
        await storeSet({ [STORE_LAST]: {
          at: Date.now(),
          url: (msg.payload && msg.payload.url) || '',
          result: r || null,
        }});
        sendResponse(r);
        return;
      }
      case 'DP_MANUAL_STATE':
        sendResponse(await getManualState());
        return;
      case 'DP_SESSION_FINISH':
        sendResponse(await finishManualSession());
        return;
      case 'DP_SESSION_DELETE':
        sendResponse(await deleteManualSessionRow(msg.rid));
        return;
      case 'DP_RECOLLECT_URL': {
        const st = await getSettings();
        sendResponse(await postCollect({
          url: msg.url, title: msg.title || '', html: '',
          industry: st.industry || '', country: st.country || '', upgrade: true,
        }));
        return;
      }
      default:
        sendResponse({ ok: false, msg: `未知消息：${msg.type}` });
    }
  })();
  return true;                       // 异步回复，必须返回 true 保持通道打开
});
