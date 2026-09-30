/* 设置页脚本。
 *
 * 对 127.0.0.1 的网络请求一律走 background（见 background.js 顶部说明）；
 * 只有「读/写 chrome.storage」是本机存储、不涉及网络，就直接在本文件里做，
 * 免得为了一个列表再往 background 里加一对消息。
 */

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

const HIDE_PREFIX = 'dpHide:';

/* ---------- 连接 ---------- */

function renderConn(st) {
  const p = $('connState');
  if (!st || !st.online) {
    p.className = 'pill off';
    p.textContent = '未连接';
    $('connNote').innerHTML = '没探测到本机工具。请先双击项目里的 <code>启动客户开发工具.bat</code>，'
      + '然后点「测试连接」。';
    return;
  }
  p.className = 'pill on';
  p.textContent = '已连接 127.0.0.1:' + st.port;
  const t = st.tool || {};
  const bits = [];
  if (t.name) bits.push('识别为「' + t.name + '」');
  if (t.running) bits.push('自动搜索/采集运行中');
  if (t.manual_running) bits.push('手动采集运行中');
  if (t.enrich_file) bits.push('本轮结果：' + t.enrich_file);
  $('connNote').textContent = bits.length ? bits.join(' · ') : '连接正常。';
}

async function testConn() {
  $('connState').className = 'pill busy';
  $('connState').textContent = '探测中…';
  renderConn(await send('DP_PING'));
}

/* ---------- 已隐藏网站 ---------- */

function readHidden() {
  return new Promise((resolve) => {
    chrome.storage.local.get(null, (all) => {
      void chrome.runtime.lastError;
      resolve(Object.keys(all || {}).filter((k) => k.indexOf(HIDE_PREFIX) === 0)
        .map((k) => k.slice(HIDE_PREFIX.length)).sort());
    });
  });
}

async function renderHidden() {
  const hosts = await readHidden();
  $('hideList').innerHTML = hosts.length
    ? hosts.map((h) => esc(h)).join('<br>')
    : '（空）';
}

async function clearHidden() {
  const hosts = await readHidden();
  if (!hosts.length) return;
  await new Promise((resolve) => {
    chrome.storage.local.remove(hosts.map((h) => HIDE_PREFIX + h), () => {
      void chrome.runtime.lastError;
      resolve();
    });
  });
  renderHidden();
}

/* ---------- 载入 / 保存 ---------- */

async function loadKeywords() {
  const kw = await send('DP_KEYWORDS');
  const sel = $('industry');
  if (kw && kw.names && kw.names.length) {
    kw.names.forEach((n) => sel.insertAdjacentHTML('beforeend',
      '<option value="' + esc(n) + '">' + esc(n) + '</option>'));
  }
}

async function loadSettings() {
  const s = (await send('DP_SETTINGS_GET')) || {};
  if (s.industry) $('industry').value = s.industry;
  $('country').value = s.country || '';
  $('upgrade').checked = s.upgrade !== false;
  $('fabEnabled').checked = s.fabEnabled !== false;
  if (s.port) {
    $('pmFixed').checked = true;
    $('portFixed').value = s.port;
  } else {
    $('pmAuto').checked = true;
  }
}

async function save() {
  const fixed = $('pmFixed').checked;
  const port = fixed ? parseInt($('portFixed').value, 10) : 0;
  if (fixed && (!Number.isInteger(port) || port < 1024 || port > 65535)) {
    alert('固定端口要填 1024–65535 之间的整数。');
    return;
  }
  await send('DP_SETTINGS_SET', {
    patch: {
      industry: $('industry').value,
      country: $('country').value.trim(),
      upgrade: $('upgrade').checked,
      fabEnabled: $('fabEnabled').checked,
      port: port || 0,
    },
  });
  const m = $('savedMsg');
  m.textContent = '✓ 已保存（已打开的网页需刷新后生效）';
  setTimeout(() => { m.textContent = ''; }, 4000);
  // 端口设置变了，清掉缓存重新探测一次
  renderConn(await send('DP_FORGET_PORT'));
}

/* ---------- 绑定 ---------- */

$('btnTest').addEventListener('click', testConn);
$('btnReprobe').addEventListener('click', async () => {
  $('connState').className = 'pill busy';
  $('connState').textContent = '重新探测中…';
  renderConn(await send('DP_FORGET_PORT'));
});
$('btnClearHide').addEventListener('click', clearHidden);
$('btnSave').addEventListener('click', save);
$('pmAuto').addEventListener('change', () => { $('portFixed').disabled = true; });
$('pmFixed').addEventListener('change', () => { $('portFixed').disabled = false; });
$('portFixed').disabled = true;

(async function init() {
  await loadKeywords();
  await loadSettings();
  $('portFixed').disabled = !$('pmFixed').checked;
  await renderHidden();
  renderConn(await send('DP_PING'));
})();
