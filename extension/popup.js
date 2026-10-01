/* popup —— 只负责界面，所有网络请求都发消息交给 background（见 background.js 顶部说明）。 */

const $ = (id) => document.getElementById(id);

function send(type, extra) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(Object.assign({ type }, extra || {}), (r) => {
      void chrome.runtime.lastError;
      resolve(r || null);
    });
  });
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function shortUrl(u) {
  try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u || ''; }
}

/* ---------- 连接状态 ---------- */

function renderConn(st) {
  const dot = $('dot'), txt = $('connText');
  if (!st || !st.online) {
    dot.className = 'dot off';
    txt.textContent = '未连接 · 本机工具没在运行';
    return;
  }
  const t = st.tool || {};
  const bits = ['已连接 127.0.0.1:' + st.port];
  if (t.running) bits.push('自动任务运行中');
  if (t.manual_running) bits.push('手动采集中');
  dot.className = 'dot on';
  txt.textContent = bits.join(' · ');
}

/* ---------- 结果展示 ---------- */

function rowHtml(row, r) {
  const line = (k, v, cls) =>
    '<div>' + k + '：' + (v ? '<b>' + esc(v) + '</b>' : '<span class="miss">' + cls + '</span>') + '</div>';
  return ''
    + '<div>网站：<b>' + esc(shortUrl(row.url)) + '</b></div>'
    + line('标题', row.title, '未取到')
    + line('邮箱', (row.emails || []).join(' / '), '未抓到')
    + line('电话', (row.phones || []).join(' / '), '未抓到')
    + line('联系页', row.contact_url, '无')
    + line('行业', row.industry, '未判断')
    + '<div>评分：<b>' + (row.score == null ? '-' : row.score) + '</b>（' + esc(row.rating || '-') + '）</div>'
    + '<div>抓取：第 <b>' + esc(r.tier == null ? '?' : r.tier) + '</b> 级'
      + (r.upgraded ? '（升级到浏览器）' : '') + '</div>';
}

function showResult(r) {
  const card = $('resultCard'), t = $('rTitle'), b = $('rBody');
  card.hidden = false;
  if (!r) {
    t.className = 'rTitle err';
    t.textContent = '✗ 扩展后台没有应答';
    b.textContent = '关掉再打开这个面板重试；若仍不行，去 chrome://extensions 重新加载本扩展。';
    return;
  }
  if (!r.ok) {
    t.className = 'rTitle err';
    t.textContent = r.offline ? '⚠️ 本机工具没在运行' : '✗ 采集失败';
    b.textContent = r.msg || '';
    return;
  }
  if (r.existed) {
    t.className = 'rTitle dup';
    t.textContent = '= 已在客户库，跳过';
    b.innerHTML = '<div>网站：<b>' + esc(shortUrl((r.row || {}).url)) + '</b></div>'
      + '<div class="miss">想重新抓一遍？先删掉库里那条记录（或在手动采集页粘贴该网址）。</div>';
    return;
  }
  t.className = 'rTitle ok';
  t.textContent = '✓ 已采集入库';
  b.innerHTML = rowHtml(r.row || {}, r);
}

/* ---------- 本轮采集明细 ----------
 * 数据来自工具的 GET /api/manual/state（经 background 代发，popup 里不许 fetch）。
 * 与 /manual 页第③卡同源同口径：session_rows 里 kind='added' 是完整行、kind='existed'
 * 只有 title+url（后端刻意只留这点，够显示「已在客户库」即可）。
 */

let _pollTimer = null, _pollBusy = false, _lastSig = '', _finishing = false;
let _note = '';           // finishSession 的一次性提示，优先级低于「已生成的结果文件名」

function sessRowHtml(r, i) {
  const old = r.kind === 'existed';
  const mails  = (!old && r.emails && r.emails.length) ? r.emails.join(' / ') : '';
  const phones = (!old && r.phones && r.phones.length) ? r.phones.join(' / ') : '';
  return '<div class="li' + (old ? ' li-old' : '') + '">'
    + '<div class="li-top"><span class="li-idx">' + (i + 1) + '</span>'
      + '<b class="li-site" title="' + esc(r.url || '') + '">' + esc(shortUrl(r.url)) + '</b>'
      + '<span class="li-score">' + (old || r.score == null ? '' : esc(r.score) + ' 分') + '</span>'
      // ✕ 删掉这一条（明细 + 客户库双删）。data-rid 是后端发的本轮内唯一行号 ——
      // 同一个网址在同一轮里可能有两条（added + existed），所以不能靠 url 定位。
      + '<span class="li-del" role="button" title="从本轮明细和客户库删掉这一条"'
        + ' data-rid="' + esc(r.rid == null ? '' : String(r.rid)) + '">✕</span></div>'
    + '<div class="li-sub">'
      + '<span class="li-mail">' + (old ? '<span class="miss">已在客户库</span>'
          : (mails ? '<span class="mail">' + esc(mails) + '</span>'
                   : '<span class="miss">邮箱未抓到</span>')) + '</span>'
      + '<span class="li-phone">' + (old ? ''
          : (phones ? esc(phones) : '<span class="miss">电话未抓到</span>')) + '</span>'
    + '</div></div>';
}

/* 轮已结束时，在结果文件那行补一句「这份表到底写了几行」。
 * ⚠️ 只在 !session_active 时显示：新一轮开起来后 added/existed 已清零，
 *    而 session_excel 还挂着上一份文件名，配上新计数会误导。 */
function roundTally(st) {
  if (!st || st.session_active) return '';
  if (st.added == null && st.existed == null) return '';
  const a = st.added || 0, e = st.existed || 0;
  return '；本轮写入 ' + a + ' 行新客户'
    + (e ? '，另有 ' + e + ' 条已在客户库、未重复写入' : '');
}

function renderSession(st) {
  const count = $('sessCount'), status = $('sessStatus');
  const list = $('sessList'), empty = $('sessEmpty'), file = $('sessFile'), btn = $('btnFinish');

  if (!st || st.ok === false) {                    // 离线 / 后台没应答
    status.className = 'live-status err';
    status.textContent = (st && st.msg) || '读不到本机工具';
    btn.disabled = true;
    return;
  }

  const rows = Array.isArray(st.session_rows) ? st.session_rows : [];
  const sig = [rows.length, rows.length ? (rows[rows.length - 1].url || '') : '',
               !!st.session_active, st.session_excel || '', st.session_error || '',
               st.added || 0, st.existed || 0].join('|');
  if (sig !== _lastSig) {                          // 只有变化才重建：否则每秒重置滚动位置
    _lastSig = sig;
    list.innerHTML = rows.map(sessRowHtml).join('');
    count.textContent = rows.length + ' 条';
    // 徽章数的是「明细行数」＝ 新增 + 已在库，而结果 Excel 只写「新增」。
    // 徽章太窄放不下，所以挂悬停提示把这道算式讲清楚（正文在状态行里）。
    count.title = (st.added == null && st.existed == null) ? ''
      : ('已采 ' + rows.length + ' 条 = 新增 ' + (st.added || 0) + ' + 已在库 ' + (st.existed || 0)
         + '；结果 Excel 只写「新增」的 ' + (st.added || 0) + ' 条');
    empty.style.display = rows.length ? 'none' : 'block';
    if (rows.length) list.scrollTop = list.scrollHeight;   // 停在最新一条
  }

  if (st.session_error) {
    status.className = 'live-status err';
    status.textContent = '⚠️ 结果文件保存失败，可重试';
  } else if (st.session_active) {
    const bits = ['已采 ' + rows.length + ' 条'];
    // ⚠️ 必须把「新增 / 已在库」拆开报（与 /manual 页同口径）：明细行数 = 新增 + 已在库，
    //    而 Excel 只写新增。只报一个数会让人以为表漏写了（实测踩过：已采 17 条、表里 13 行）。
    if (st.added != null || st.existed != null) {
      bits.push('新增 ' + (st.added || 0) + ' · 已在库 ' + (st.existed || 0));
    }
    if (st.session_industry) bits.push('行业 ' + st.session_industry);
    if (st.session_country) bits.push('国家 ' + st.session_country);
    if (st.running) bits.push('批量 ' + (st.done || 0) + '/' + (st.total || 0));
    status.className = 'live-status';
    status.textContent = '🟢 进行中 · ' + bits.join(' · ');
  } else {
    status.className = 'live-status';
    status.textContent = st.session_excel ? '✅ 上一轮已生成结果文件' : '本轮未开始';
  }

  if (st.session_error) file.textContent = st.session_error;
  else if (st.session_excel) file.textContent = '本批结果文件：' + st.session_excel + roundTally(st);
  else file.textContent = _note || '';

  btn.disabled = !st.session_active || _finishing;
}

async function refreshSession() {
  if (_pollBusy) return;                           // 上一轮请求还没回来，跳过这一 tick
  _pollBusy = true;
  try { renderSession(await send('DP_MANUAL_STATE')); }
  finally { _pollBusy = false; }
}

function startPolling() {
  if (_pollTimer) return;
  _pollTimer = setInterval(() => { void refreshSession(); }, 1000);
  // popup 关闭即销毁 JS 上下文、定时器自然停；pagehide 只是保险
  window.addEventListener('pagehide', () => { clearInterval(_pollTimer); _pollTimer = null; });
}

async function finishSession() {
  const btn = $('btnFinish'), status = $('sessStatus'), file = $('sessFile');
  if (_finishing) return;
  _finishing = true;
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = '正在生成 Excel…';
  const r = await send('DP_SESSION_FINISH');
  _finishing = false;
  btn.textContent = label;

  if (!r) {
    file.textContent = '扩展后台没有应答，关掉再打开这个面板重试';
    btn.disabled = false;
    return;
  }
  if (r.pending) {                                 // 批量还在跑：后端置 stop，由 worker 收尾
    _note = r.msg || '正在停止批量并收尾，稍候会自动生成 Excel…';
    file.textContent = _note;
  } else if (r.ok && r.saved) {                    // 成功：refresh 会用 session_excel 覆盖
    _note = '';
    file.textContent = '✅ 已生成：' + (r.file || '');
  } else if (r.ok && r.saved === false) {          // 空轮：不产文件，属正常
    _note = r.msg || '本轮没有采到新客户，未生成结果文件';
    file.textContent = _note;
  } else {                                         // 后端拒绝（如「没有进行中的本轮采集」）
    // ⚠️ 不能只写 status：本函数末尾马上会 refreshSession()，状态行会被后端状态覆盖，
    //    原因就彻底不留痕了。写进 _note（它是 file 行的兜底文案）才能留住。
    _note = '⚠️ ' + (r.msg || '生成失败');
    status.className = 'live-status err';
    status.textContent = _note;
    btn.disabled = false;
  }
  await refreshSession();
}

/* ---------- 删除单条明细 ----------
 * ⚠️ 事件委托挂在 #sessList 上，不要逐行绑：列表是 list.innerHTML = rows.map(...) 整表重建的，
 *    逐行绑的监听会跟着节点一起消失。
 * ⚠️ 与 finishSession 同款：一次性提示必须写进 _note（renderSession 里 file 行的兜底文案），
 *    只写 status 会被紧随其后的 refreshSession() 覆盖掉、不留痕。
 */

function onSessionListClick(e) {
  const el = (e.target && e.target.closest) ? e.target.closest('[data-rid]') : null;
  if (!el || !el.dataset) return;
  const rid = el.dataset.rid;
  if (rid == null || rid === '') return;      // 没有 rid 的行不动作（老数据/桩里造的假行）
  void deleteSessionRow(Number(rid));
}

async function deleteSessionRow(rid) {
  const ok = window.confirm('确定删除这一条吗？\n\n会同时从「本轮明细」和「客户库」删掉它，'
    + '\n也不会进入本次生成的结果 Excel。\n（本机工具会先自动备份一份客户库）');
  if (!ok) return;
  const r = await send('DP_SESSION_DELETE', { rid });
  if (!r) {
    _note = '扩展后台没有应答，关掉再打开这个面板重试';
    refreshSession();
    return;
  }
  if (r.ok) {
    _note = '🗑️ 已删除' + (r.deleted ? '（客户库同步删掉 1 条）' : '（客户库里没有这条记录）')
      + (r.backup ? ('，已备份：' + r.backup) : '（本轮已有备份，未重复备份）');
  } else {
    _note = '⚠️ ' + (r.msg || '删除失败');
  }
  await refreshSession();
}

/* ---------- 采集 ---------- */

async function collect() {
  const btn = $('btnCollect');
  btn.disabled = true;
  btn.textContent = '采集中…（慢的话最多 60 秒）';
  $('resultCard').hidden = true;

  const opts = {
    industry: $('industry').value,
    country: $('country').value.trim(),
    upgrade: $('upgrade').checked,
  };
  if ($('remember').checked) {
    await send('DP_SETTINGS_SET', {
      patch: { industry: opts.industry, country: opts.country, upgrade: opts.upgrade },
    });
  }

  const r = await send('DP_COLLECT_TAB', { opts });

  btn.disabled = false;
  btn.textContent = '采集当前页为客户';
  showResult(r);
  renderConn(await send('DP_STATE'));
  await refreshSession();          // 别等下一次轮询（最多 1 秒），立刻让明细表长出这一条
}

/* ---------- 链接 / 初始化 ---------- */

function openUrl(u) { chrome.tabs.create({ url: u }); }

async function toolUrls() {
  const u = await send('DP_URLS');
  if (!u || !u.ok) {
    alert('还没连上本机「谷歌客户开发工具」，请先启动它（双击 启动客户开发工具.bat）。');
    return null;
  }
  return u;
}

function activeTabUrl() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      void chrome.runtime.lastError;
      resolve((tabs && tabs[0] && tabs[0].url) || '');
    });
  });
}

async function init() {
  const st = await send('DP_STATE');
  renderConn(st);

  const s = (st && st.settings) || {};
  $('upgrade').checked = s.upgrade !== false;
  $('country').value = s.country || '';

  const kw = await send('DP_KEYWORDS');
  const sel = $('industry');
  if (kw && kw.names && kw.names.length) {
    // 行业列表从工具的 /api/keywords 动态取，这里不硬编码一份枚举
    kw.names.forEach((n) => sel.insertAdjacentHTML('beforeend',
      '<option value="' + esc(n) + '">' + esc(n) + '</option>'));
  }
  if (s.industry) sel.value = s.industry;

  // 只在「上次结果就是当前这个页面」时回显，避免拿别的页面的旧结果显示给人看
  if (st && st.last && st.last.result) {
    const cur = await activeTabUrl();
    if (st.last.url && st.last.url === cur) showResult(st.last.result);
  }

  await refreshSession();          // 本轮明细：先拉一次，再每秒轮询（popup 关掉即停）
  startPolling();

  $('btnCollect').addEventListener('click', collect);
  $('btnFinish').addEventListener('click', finishSession);
  $('sessList').addEventListener('click', onSessionListClick);
  $('lnkManual').addEventListener('click', async (e) => {
    e.preventDefault();
    const u = await toolUrls(); if (u) openUrl(u.manual);
  });
  $('lnkHome').addEventListener('click', async (e) => {
    e.preventDefault();
    const u = await toolUrls(); if (u) openUrl(u.home);
  });
  // 客户库查询页：/db 是新加的第三个页面。老实例上没有这个路由（返回 404），
  // 所以它和别的页面一样必须靠「重启工具」才生效 —— 不要在这里加兜底判断。
  $('lnkDb').addEventListener('click', async (e) => {
    e.preventDefault();
    const u = await toolUrls(); if (u) openUrl(u.db);
  });
  $('lnkOptions').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
  $('lnkReprobe').addEventListener('click', async (e) => {
    e.preventDefault();
    const dot = $('dot');
    dot.className = 'dot busy';
    $('connText').textContent = '正在重新探测端口…';
    renderConn(await send('DP_FORGET_PORT'));
  });
}

init();
