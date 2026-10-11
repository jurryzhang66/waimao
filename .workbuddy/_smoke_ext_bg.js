/* background.js 端到端冒烟测试：真实的 background.js × 真实的 Flask 后端。
 *
 * 桩只打在「浏览器那一边」（chrome.* API 与 fetch 出口），后端是真的：
 *   _smoke_ext_live.py 会用临时数据库/临时 output 起一个真 Flask，把端口写进 DP_TEST_PORT。
 * 所以这轮跑通就等价于证明了扩展与工具的**接口契约**成立：
 *   /api/ping 的身份字段、端口发现优先级、/api/collect 的自定义头与 payload 形状、
 *   后端 collect_from_html 的返回结构、以及 popup 那三条消息
 *   （DP_MANUAL_STATE → /api/manual/state、DP_SESSION_FINISH → /api/manual/session/finish、
 *     DP_SESSION_DELETE → /api/manual/session/delete）
 *   —— 全都在真实 HTTP 上过了一遍。
 * ⚠️ ⑨ 会先真的删掉一条明细（连带客户库），再调用「结束本轮」把结果 Excel 落盘，
 *    所以 python 侧（_smoke_ext_live.py）不能再点一次：
 *    第二次会拿到 {ok:false,'当前没有进行中的本轮采集，无需结束'}；而且落盘行数是删过之后的 1 行。
 *
 * 环境变量：
 *   DP_TEST_PORT   真实后端端口（必填）
 *   DP_MOCK_PORTS  逗号分隔：这些端口由桩冒充一个「别的服务」（app 字段不对）
 *   DP_DEAD        1 = 把真实端口也拦掉（模拟「工具没在运行」）
 *   DP_STALE_PORT  逗号分隔：写进 dpSettings.port，模拟「用户填了个过期的固定端口」
 *   DP_SHADOW_PORTS 逗号分隔：这些端口上真有本工具的另一个实例（用户自己开着的），
 *                  测试期间在 fetch 层当它不可达 —— 否则扩展会优先发现它，把假数据写进真实库
 *   DP_CONTENT_SCRIPT 1 = 让 tabs.sendMessage 假装内容脚本在场（验证优先走内容脚本）
 *
 * 运行：DP_TEST_PORT=8000 node .workbuddy/_smoke_ext_bg.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const EXT = path.join(__dirname, '..', 'extension');
const REAL_PORT = Number(process.env.DP_TEST_PORT || 0);
const MOCK_PORTS = (process.env.DP_MOCK_PORTS || '').split(',').map(Number).filter(Boolean);
const STALE_PORTS = (process.env.DP_STALE_PORT || '').split(',').map(Number).filter(Boolean);
// 「影子端口」：环境里真的有本工具的另一个实例在这些端口上跑着（多半是用户自己开着的那个）。
// ⚠️ 必须处理，实测踩过：扩展是按 PREFERRED_PORTS 顺序逐个试的，如果那个实例排在测试端口
//    之前（本机 5000 在系统保留段、8000 上跑着用户的工具），扩展会优先发现它 ——
//    于是测试的假网址被写进**真实客户库**，且所有端口断言都失败。
//    这里在 fetch 层当它不可达，等价于「本次测试期间该实例不存在」。
const SHADOW_PORTS = (process.env.DP_SHADOW_PORTS || '').split(',').map(Number).filter(Boolean);
const DEAD = process.env.DP_DEAD === '1';
const DEAD_ONLY = process.env.DP_DEAD_ONLY === '1';    // 只跑「工具没在运行」那一段
const HAS_CONTENT_SCRIPT = process.env.DP_CONTENT_SCRIPT === '1';
const DECOY_PORT = MOCK_PORTS[0] || 5555;

if (!REAL_PORT) { console.error('缺少 DP_TEST_PORT'); process.exit(2); }

// 候选端口个数直接从 ports.js 读出来，别在断言里写死
const PREFERRED_COUNT = ((fs.readFileSync(path.join(EXT, 'ports.js'), 'utf8')
  .match(/DP_PREFERRED_PORTS\s*=\s*\[([^\]]*)\]/) || [, ''])[1].match(/\d+/g) || []).length;

let fails = 0, checks = 0;
function check(cond, label, detail) {
  checks++;
  if (cond) console.log('  OK   ' + label);
  else { fails++; console.log('  FAIL ' + label + (detail ? '  -- ' + detail : '')); }
}
function section(t) { console.log('\n========== ' + t + ' =========='); }

/* ================= 浏览器侧桩 ================= */

const realFetch = globalThis.fetch;

const state = {
  store: {},                 // chrome.storage.local
  dpPortHistory: [],         // dpPort 的写入序列（用来验证「清掉 → 又探到」）
  menus: [],
  badges: [],
  toasts: [],
  outbound: [],              // 所有出站请求（含 headers）
  exec: 0,                   // executeScript 被调次数
  activeTab: { id: 7, url: 'https://plasticbagpc.com/' },
  grabHtml: '<html><head><title>Trash Bags Wholesale Supplier</title>'
    + '<meta name="description" content="Leading wholesale trash bag manufacturer"></head><body>'
    + '<a href="mailto:info@plasticbagpc.com">info@plasticbagpc.com</a></body></html>',
  grabTitle: 'Trash Bags Wholesale Supplier',
};

function fakeFetch(url, opts) {
  const u = String(url);
  const port = Number(new URL(u).port || 80);
  state.outbound.push({ url: u, port, method: (opts && opts.method) || 'GET', headers: (opts && opts.headers) || {} });

  if (DEAD && port === REAL_PORT) throw new TypeError('fetch failed');   // 工具没在运行
  if (SHADOW_PORTS.indexOf(port) >= 0) throw new TypeError('fetch failed');   // 环境里别的实例，测试期间视为不存在
  if (MOCK_PORTS.indexOf(port) >= 0) {
    // 冒充者：HTTP 200 + ok:true，但 app 字段不是本工具 → 扩展必须无视它
    return Promise.resolve(new Response(JSON.stringify({
      ok: true, app: 'some-other-service', name: '别的服务', port,
    }), { status: 200, headers: { 'content-type': 'application/json' } }));
  }
  return realFetch(url, opts);
}

function makeChrome() {
  const listeners = { msg: [], ctx: [], installed: [], startup: [] };
  const chrome = {
    runtime: {
      lastError: undefined,
      onMessage: { addListener: (f) => listeners.msg.push(f) },
      onInstalled: { addListener: (f) => listeners.installed.push(f) },
      onStartup: { addListener: (f) => listeners.startup.push(f) },
      getURL: (p) => 'chrome-extension://stub/' + p,
      openOptionsPage: () => {},
    },
    storage: {
      local: {
        get(keys, cb) {
          const out = {};
          if (keys == null) Object.assign(out, state.store);
          else if (Array.isArray(keys)) keys.forEach((k) => { if (k in state.store) out[k] = state.store[k]; });
          else if (typeof keys === 'string') { if (keys in state.store) out[keys] = state.store[keys]; }
          else Object.keys(keys).forEach((k) => { out[k] = (k in state.store) ? state.store[k] : keys[k]; });
          cb(out);
        },
        set(obj, cb) {
          if ('dpPort' in obj) state.dpPortHistory.push(obj.dpPort);
          Object.assign(state.store, obj);
          if (cb) cb();
        },
        remove(keys, cb) { (Array.isArray(keys) ? keys : [keys]).forEach((k) => delete state.store[k]); if (cb) cb(); },
      },
    },
    contextMenus: {
      removeAll(cb) { state.menus.length = 0; if (cb) cb(); },
      create(o) { state.menus.push(o); },
      onClicked: { addListener: (f) => listeners.ctx.push(f) },
    },
    action: {
      setBadgeText(o) { state.badges.push(o); },
      setBadgeBackgroundColor() {},
    },
    tabs: {
      query(q, cb) { cb([state.activeTab]); },
      sendMessage(tabId, msg, cb) {
        if (msg && msg.type === 'DP_GRAB' && HAS_CONTENT_SCRIPT) {
          cb({ ok: true, url: state.activeTab.url, title: state.grabTitle, html: state.grabHtml });
        } else {
          cb(undefined);                    // 模拟「内容脚本不在」→ 逼它走 executeScript 兜底
        }
      },
      create() {},
    },
    scripting: {
      executeScript(o, cb) {
        state.exec += 1;
        cb([{ result: { ok: true, url: state.activeTab.url, title: state.grabTitle, html: state.grabHtml } }]);
      },
    },
  };
  return { chrome, listeners };
}

function loadBackground() {
  const { chrome, listeners } = makeChrome();
  const sandbox = {
    chrome, fetch: fakeFetch, console, setTimeout, clearTimeout,
    AbortController, Response, URL, Promise, Object, Array, JSON, Number, String,
    Boolean, Math, Date, Error, RegExp, Set, Map, isNaN, parseInt,
  };
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  sandbox.importScripts = function () {
    for (const f of arguments) {
      vm.runInContext(fs.readFileSync(path.join(EXT, f), 'utf8'), context, { filename: f });
    }
  };
  vm.runInContext(fs.readFileSync(path.join(EXT, 'background.js'), 'utf8'), context, { filename: 'background.js' });
  return { sandbox, listeners };
}

/** 走真实的 chrome.runtime.onMessage 分发（等价于 popup/内容脚本发消息）。
 *  sender 可选：内容脚本自己发的消息天然带 sender.tab，background 用它决定徽标设到哪个标签页。 */
function msg(listeners, type, extra, timeoutMs, sender) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('等待 ' + type + ' 回复超时')), timeoutMs || 30000);
    const payload = Object.assign({ type }, extra || {});
    for (const h of listeners.msg) {
      h(payload, sender || {}, (r) => { clearTimeout(t); resolve(r); });
    }
  });
}

function lastBadge() {
  const b = state.badges.filter((x) => x.text !== undefined).pop();
  return b ? b.text : undefined;
}

/* ================= 用例 ================= */

/** 「工具没在运行」这一组：单独一个模式跑（其余用例全都会因为这个前提而失败）。 */
async function deadSuite() {
  section('⑨ 工具没在运行时的行为');
  state.store = {};
  const { listeners } = loadBackground();

  const stDead = await msg(listeners, 'DP_PING');
  check(stDead && stDead.online === false, '探测结果 online=false', JSON.stringify(stDead && { online: stDead.online }));
  check(stDead && stDead.port === 0, '端口为 0', 'port=' + (stDead && stDead.port));
  check(stDead && stDead.tool === null, 'tool 为 null');

  state.badges.length = 0;
  const r = await msg(listeners, 'DP_COLLECT_PAYLOAD', {
    payload: { url: 'https://x.com', title: 'X', html: '<html></html>' },
  }, 30000, { tab: { id: 7 } });          // 内容脚本发来的消息天然带 sender.tab
  check(r && r.ok === false && r.offline === true, '采集返回 ok=false / offline=true', JSON.stringify(r));
  check(r && /启动客户开发工具/.test(r.msg || ''), '提示里明确告诉用户去启动工具', r && r.msg);
  // ⚠️ 2026-09 行为翻转：这条路（内容脚本自己点的悬浮按钮）以前**刻意不设徽标、不写 STORE_LAST**，
  //    理由是「页内已经弹了提示」—— 结果用户点完悬浮按钮、再打开扩展面板**什么都看不到**，
  //    以为采集失败。现在三条入口一视同仁：都设徽标、都写 dpLastResult。
  check(lastBadge() === '!', '内容脚本那条路失败时也设徽标 !', 'badge=' + lastBadge());
  check(state.store.dpLastResult && state.store.dpLastResult.url === 'https://x.com',
        '内容脚本那条路失败时也写 dpLastResult',
        JSON.stringify(state.store.dpLastResult && state.store.dpLastResult.url));

  const urlsOff = await msg(listeners, 'DP_URLS');
  check(urlsOff && urlsOff.ok === false, '「打开手动采集页」离线时不给出坏 URL', JSON.stringify(urlsOff));

  state.badges.length = 0;
  const collectOff = await msg(listeners, 'DP_COLLECT_TAB', { opts: {} }, 30000);
  check(collectOff && collectOff.ok === false && collectOff.offline === true,
        '面板点采集也拿到 offline 提示', JSON.stringify(collectOff && { ok: collectOff.ok, offline: collectOff.offline }));
  check(lastBadge() === '!', '面板/右键那条路失败时徽标是 !', 'badge=' + lastBadge());
}

(async function main() {
  console.log(`真实后端端口 ${REAL_PORT}；冒充端口 [${MOCK_PORTS.join(',') || '无'}]；`
            + `工具离线=${DEAD}；内容脚本在场=${HAS_CONTENT_SCRIPT}`);
  if (SHADOW_PORTS.length) {
    console.log(`影子端口 [${SHADOW_PORTS.join(',')}]：这些端口上有别的本工具实例，本次视为不可达`);
  }

  if (DEAD_ONLY) {
    await deadSuite();
    console.log('\n' + '='.repeat(62));
    if (fails) { console.log(`FAIL ${fails} / ${checks}`); process.exit(1); }
    console.log(`ALL PASS (${checks} checks) —— 离线态行为符合预期`);
    process.exit(0);
  }

  const { listeners } = loadBackground();

  /* ---------- ① 右键菜单 ---------- */
  section('① 右键菜单');
  check(listeners.installed.length === 1, '注册了 onInstalled 监听');
  listeners.installed.forEach((f) => f({ reason: 'install' }));
  check(state.menus.length === 2, '装好 2 个菜单项', 'n=' + state.menus.length);
  const mp = state.menus.find((m) => m.id === 'dp-collect-page');
  const ml = state.menus.find((m) => m.id === 'dp-collect-link');
  check(!!mp && mp.contexts.indexOf('page') >= 0, '「采集本页为客户」挂在 page 上');
  check(!!mp && (mp.documentUrlPatterns || []).indexOf('https://*/*') >= 0,
        '「采集本页」限定 http/https（chrome:// 页不出现）');
  check(!!ml && ml.contexts.indexOf('link') >= 0, '「采集此链接网站为客户」挂在 link 上');

  /* ---------- ② 端口发现 ---------- */
  section('② 端口发现：身份校验优先于优先级');
  state.store = {};
  let st = await msg(listeners, 'DP_PING');
  check(st && st.online === true, '探到本机工具在线', JSON.stringify(st && { online: st.online, port: st.port }));
  check(st && st.port === REAL_PORT, `选中的是真实端口 ${REAL_PORT}`, 'port=' + (st && st.port));
  check(st && st.tool && st.tool.app === 'waimao-dp', '/api/ping 身份字段正确');
  check(st && st.tool && !!st.tool.name, '/api/ping 带回了工具名', st && st.tool && st.tool.name);
  check(state.store.dpPort === REAL_PORT, '探到的端口落进 chrome.storage.local（SW 被回收也不丢）',
        'dpPort=' + state.store.dpPort);

  const pingReqs = state.outbound.filter((r) => r.url.indexOf('/api/ping') >= 0);
  check(pingReqs.length >= PREFERRED_COUNT, `确实打了 /api/ping（${pingReqs.length} 次）`);
  check(pingReqs.every((r) => r.method === 'GET'), '端口探测用 GET');

  section('②b 冒名的「别的服务」必须被无视（身份校验优先于端口优先级）');
  if (!MOCK_PORTS.length) {
    console.log('  （跳过：未提供 DP_MOCK_PORTS）');
  } else {
    // dpSettings.port 优先级最高，这里把它指成一个「冒充者」端口 ——
    // 如果扩展只看「能不能连通」而不校验 app 字段，就会挑中它。
    state.store = { dpSettings: { port: DECOY_PORT } };
    state.outbound.length = 0;
    const decoy = loadBackground();
    const st2 = await msg(decoy.listeners, 'DP_PING');
    check(st2 && st2.port === REAL_PORT,
          `dpSettings.port 指向冒充端口 ${DECOY_PORT} 时，仍挑中真实端口 ${REAL_PORT}`,
          'port=' + (st2 && st2.port));
    check(st2 && st2.tool && st2.tool.app === 'waimao-dp',
          '选中的那个确实是 app=waimao-dp 的服务',
          st2 && st2.tool && st2.tool.app);
    check(state.outbound.some((r) => r.port === DECOY_PORT && r.url.indexOf('/api/ping') >= 0),
          `冒充端口 ${DECOY_PORT} 确实被探过（证明它是被「身份」挡掉而不是没探到）`);
  }

  /* ---------- ③ 固定端口填错 → 回退到扫描 ---------- */
  section('③ 用户填的固定端口已失效 → 自动回退到扫描');
  if (STALE_PORTS.length) {
    state.store = { dpSettings: { port: STALE_PORTS[0] } };
    const staleLoad = loadBackground();
    const st3 = await msg(staleLoad.listeners, 'DP_PING');
    check(st3 && st3.online === true && st3.port === REAL_PORT,
          `固定端口 ${STALE_PORTS[0]} 连不上 → 回退扫描并找到 ${REAL_PORT}`,
          JSON.stringify(st3 && { online: st3.online, port: st3.port }));
  } else {
    console.log('  （跳过：未提供 DP_STALE_PORT）');
  }

  /* ---------- ④ 默认设置与关键词 ---------- */
  section('④ 设置与关键词');
  state.store = {};                    // 清掉 ②b/③ 塞进去的 dpSettings，看真正的默认值
  const settings = await msg(listeners, 'DP_SETTINGS_GET');
  check(settings && settings.upgrade === true && settings.fabEnabled === true && settings.port === 0,
        '默认设置符合预期（升级开、悬浮按钮开、端口自动）', JSON.stringify(settings));

  const kw = await msg(listeners, 'DP_KEYWORDS');
  check(kw && kw.ok === true && Array.isArray(kw.names) && kw.names.length >= 8,
        `从 /api/keywords 取到行业列表（${kw && kw.names ? kw.names.length : 0} 个）`);
  check(kw && kw.names.indexOf('塑料包装袋') >= 0, '行业列表里含「塑料包装袋」（词库改动会立刻反映过来）');

  const urls = await msg(listeners, 'DP_URLS');
  check(urls && urls.ok === true && urls.manual === `http://127.0.0.1:${REAL_PORT}/manual`,
        '「打开手动采集页」拼出了正确 URL', urls && urls.manual);

  /* ---------- ⑤ 采集当前页（走 scripting 兜底） ---------- */
  section('⑤ 采集当前页（executeScript 兜底路径）');
  state.badges.length = 0;
  const before = state.outbound.length;
  const tab = await msg(listeners, 'DP_COLLECT_TAB', {
    opts: { industry: '', country: '德国', upgrade: false },
  }, 60000);
  console.log('  返回：', JSON.stringify({ ok: tab && tab.ok, added: tab && tab.added,
    existed: tab && tab.existed, tier: tab && tab.tier, score: tab && tab.row && tab.row.score,
    industry: tab && tab.row && tab.row.industry }));
  check(tab && tab.ok === true, '采集请求 ok=true', tab && tab.msg);
  check(tab && tab.added === true && tab.existed === false, '首次采集 → added=true');
  check(tab && tab.tier === 1, '有页面 HTML → 走①级秒级路径（不开浏览器）', 'tier=' + (tab && tab.tier));
  check(tab && tab.row && tab.row.emails && tab.row.emails.indexOf('info@plasticbagpc.com') >= 0,
        '邮箱被后端抽出来了', tab && tab.row && JSON.stringify(tab.row.emails));
  check(tab && tab.row && tab.row.score > 0, '拿到了评分', 'score=' + (tab && tab.row && tab.row.score));
  check(tab && tab.row && tab.row.country === '德国', 'opts.country 透传到了后端', tab && tab.row && tab.row.country);
  check(tab && tab.row && !!tab.row.formula && tab.row.formula.indexOf('[手动采集]') === 0,
        '公式带 [手动采集] 前缀（供飞书豁免低分门槛）', tab && tab.row && tab.row.formula);
  check(HAS_CONTENT_SCRIPT ? state.exec === 0 : state.exec === 1,
        HAS_CONTENT_SCRIPT ? '内容脚本在场时**不**注入（省一次 executeScript）'
                           : '内容脚本不在时用 executeScript 兜底（恰 1 次）',
        'exec=' + state.exec);

  const collectReq = state.outbound.slice(before).find((r) => r.url.indexOf('/api/collect') >= 0);
  check(!!collectReq, '确实向 /api/collect 发了 POST');
  check(collectReq && collectReq.method === 'POST', '方法为 POST');
  check(collectReq && collectReq.headers['X-DP-Ext'] === '1',
        '带了自定义头 X-DP-Ext: 1（后端 403 门禁的钥匙）',
        JSON.stringify(collectReq && collectReq.headers));
  check(collectReq && /application\/json/i.test(String(collectReq.headers['Content-Type'] || '')),
        'Content-Type 是 application/json（强制走 CORS 预检）');
  check(lastBadge() === '✓', '成功后徽标是 ✓', 'badge=' + lastBadge());

  /* ---------- ⑥ 同页再采一次 → 去重 ---------- */
  section('⑥ 同一页再采一次 → 去重');
  state.badges.length = 0;
  const dup = await msg(listeners, 'DP_COLLECT_TAB', { opts: { upgrade: false } }, 60000);
  check(dup && dup.ok === true && dup.existed === true && dup.added === false,
        '第二次返回 existed=true / added=false', JSON.stringify(dup && { ok: dup.ok, existed: dup.existed }));
  check(lastBadge() === '=', '去重时徽标是 =', 'badge=' + lastBadge());

  /* ---------- ⑦ 内容脚本那条路（DP_COLLECT_PAYLOAD） ---------- */
  section('⑦ 内容脚本直接送 HTML（DP_COLLECT_PAYLOAD）');
  state.activeTab = { id: 7, url: 'https://flatbag-maker.de/' };
  state.grabTitle = 'Trash Bag Wholesale GmbH';
  state.grabHtml = '<html><head><title>Trash Bag Wholesale GmbH</title></head><body>'
    + '<a href="mailto:sales@flatbag-maker.de">sales@flatbag-maker.de</a></body></html>';
  state.badges.length = 0;
  const payloadRes = await msg(listeners, 'DP_COLLECT_PAYLOAD', {
    payload: {
      url: 'https://flatbag-maker.de/', title: 'Trash Bag Wholesale GmbH',
      html: state.grabHtml, industry: '塑料包装袋', country: '德国', upgrade: false,
      product_words: ['trash bag'],
    },
  }, 60000, { tab: { id: 7 } });
  check(payloadRes && payloadRes.ok === true && payloadRes.added === true,
        '内容脚本这条路也能入库', JSON.stringify(payloadRes && { ok: payloadRes.ok, msg: payloadRes.msg }));
  check(payloadRes && payloadRes.row && payloadRes.row.industry === '塑料包装袋',
        'industry 原样透传（扩展面板里手选的行业生效）',
        payloadRes && payloadRes.row && payloadRes.row.industry);
  check(payloadRes && payloadRes.row && payloadRes.row.score === 75,
        'product_words 生效 → 评分拿到产品词那 +10（75 分）',
        'score=' + (payloadRes && payloadRes.row && payloadRes.row.score));
  // 2026-09 起：这条路也要设徽标 + 写 dpLastResult（否则用户点完悬浮按钮打开面板是空的）
  check(lastBadge() === '✓', '内容脚本那条路成功后也设徽标 ✓', 'badge=' + lastBadge());
  check(state.store.dpLastResult && state.store.dpLastResult.url === 'https://flatbag-maker.de/',
        '内容脚本那条路也写 dpLastResult（popup 打开时能回显结果卡）',
        JSON.stringify(state.store.dpLastResult && state.store.dpLastResult.url));

  /* ---------- ⑧ 端口缓存与忘记 ---------- */
  section('⑧ DP_FORGET_PORT：清掉缓存重新探测');
  state.dpPortHistory.length = 0;
  const afterForget = await msg(listeners, 'DP_FORGET_PORT');
  check(state.dpPortHistory[0] === 0, '先把 dpPort 清成 0', JSON.stringify(state.dpPortHistory));
  check(state.dpPortHistory.indexOf(REAL_PORT) > 0,
        '紧接着重新探测又把真实端口写回去（清空只是「不再信任旧值」，不是「关掉服务」）',
        JSON.stringify(state.dpPortHistory));
  check(afterForget && afterForget.online === true && afterForget.port === REAL_PORT,
        '清掉后立刻重新探到了真实端口', JSON.stringify(afterForget && { port: afterForget.port }));

  /* ---------- ⑨ 本轮采集明细（popup 新卡的数据源）与「结束并生成 Excel」 ----------
   * 这两条消息就是 popup 的「本轮采集明细」卡与「🏁 结束并生成 Excel」按钮发出来的。
   * ⚠️ 这里调 finish 会**真的落盘**，所以 _smoke_ext_live.py 里 python 侧不能再点一次
   *    （第二次会拿到 {ok:false,'当前没有进行中的本轮采集'}）。 */
  section('⑨ 本轮明细（DP_MANUAL_STATE）/ 删除单条（DP_SESSION_DELETE）/ 结束本轮（DP_SESSION_FINISH）');
  const ms = await msg(listeners, 'DP_MANUAL_STATE');
  console.log('  本轮明细：', JSON.stringify(ms && ms.session_rows));
  check(ms && ms.ok === true, '拿到本轮状态', JSON.stringify(ms && { ok: ms.ok, msg: ms.msg }));
  check(ms && ms.session_active === true, '本轮已自动开轮（第一条采集进来时就开了）',
        'active=' + (ms && ms.session_active));
  const sessUrls = ((ms && ms.session_rows) || []).map((r) => r.url);
  check(sessUrls.indexOf('https://plasticbagpc.com/') >= 0
        && sessUrls.indexOf('https://flatbag-maker.de/') >= 0,
        '本轮明细里能看到刚采的 2 个站（扩展采的也计入）', JSON.stringify(sessUrls));
  check(ms && ms.added === 2, '本轮新增计数 = 2', 'added=' + (ms && ms.added));
  check(ms && ms.existed === 1, '本轮「已在库」计数 = 1（⑥ 那次去重）', 'existed=' + (ms && ms.existed));
  check(ms && ((ms.session_rows || []).filter((r) => r.kind === 'existed')).length === 1,
        '「已在库」那条带 kind=existed（面板据此渲染灰字，且没有邮箱/电话）');
  check(ms && Array.isArray(ms.recent), '状态里带 recent（/manual 页顺带在用的字段）');
  check(ms && typeof ms.now === 'number' && typeof ms.ext_last_seen === 'number',
        '状态里带 now / ext_last_seen（面板可据此算扩展心跳）');

  // ---- 删除单条（popup 行尾 ✕ 发出来的 DP_SESSION_DELETE）----
  // ⚠️ 2026-10-11 起手动采集是「点『结束并生成 Excel』才一次性入库」，所以本轮 kind='added'
  //    的行**此刻还不在客户库里** → 删它只从「待入库清单」里拿掉：deleted=0、不该产生备份。
  //    （「已入库但 Excel 没写成功」那种例外行才需要双删，覆盖见 _smoke_manual_session.py ⑪c。）
  const delRow = ((ms && ms.session_rows) || []).find((r) => r.url === 'https://flatbag-maker.de/');
  check(delRow && typeof delRow.rid === 'number', '明细行带 rid（删除按行号定位，不按 url）',
        JSON.stringify(delRow && { rid: delRow.rid, url: delRow.url }));
  const del = await msg(listeners, 'DP_SESSION_DELETE', { rid: delRow && delRow.rid });
  console.log('  删除返回：', JSON.stringify(del));
  check(del && del.ok === true, '删除单条 → ok', JSON.stringify(del));
  check(del && del.deleted === 0, '本轮还没入库 → 客户库删 0 条',
        'deleted=' + (del && del.deleted));
  check(del && del.rows === 2, '删完明细剩 2 条（3 条里拿掉 1 个 added）', 'rows=' + (del && del.rows));
  check(del && del.backup === '', '没动库就不该平白备份一份', 'backup=' + (del && del.backup));
  const msDel = await msg(listeners, 'DP_MANUAL_STATE');
  const delUrls = ((msDel && msDel.session_rows) || []).map((r) => r.url);
  check(delUrls.indexOf('https://flatbag-maker.de/') < 0, '被删的那条已不在明细里',
        JSON.stringify(delUrls));
  check(msDel && msDel.added === 1, 'added 计数跟着回退到 1', 'added=' + (msDel && msDel.added));
  check(msDel && msDel.session_active === true, '删完本轮仍在进行中（没被误关）');
  const delBad = await msg(listeners, 'DP_SESSION_DELETE', { rid: 999999 });
  check(delBad && delBad.ok === false, '删不存在的 rid → ok=false', JSON.stringify(delBad));
  const delNone = await msg(listeners, 'DP_SESSION_DELETE', {});
  check(delNone && delNone.ok === false, '不带 rid 的请求也被拒（不会退化成删全部）',
        JSON.stringify(delNone));

  const fin = await msg(listeners, 'DP_SESSION_FINISH');
  console.log('  结束返回：', JSON.stringify(fin));
  check(fin && fin.ok === true && fin.saved === true, '结束本轮 → 成功落盘', JSON.stringify(fin));
  check(fin && fin.rows === 1, '落盘 1 行（被删的那条与「已在库」那条都不进 Excel）',
        'rows=' + (fin && fin.rows));
  check(fin && /output\//.test(fin.file || ''), '返回最新结果文件的相对路径', fin && fin.file);

  const ms2 = await msg(listeners, 'DP_MANUAL_STATE');
  check(ms2 && ms2.session_active === false, '结束后本轮关闭');
  check(ms2 && (ms2.session_rows || []).length === 0, '结束后明细清空');
  check(ms2 && !!ms2.session_excel, '结束后记下生成的文件名（面板显示它）',
        ms2 && ms2.session_excel);

  console.log('\n' + '='.repeat(62));
  if (fails) { console.log(`FAIL ${fails} / ${checks}`); process.exit(1); }
  console.log(`ALL PASS (${checks} checks) —— background.js 与真实后端接口契约成立`);
  process.exit(0);
})().catch((e) => {
  console.error('\n异常：', e && e.stack || e);
  process.exit(1);
});
