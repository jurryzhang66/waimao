/* 悬浮采集按钮 —— 注入到每个普通网页（http/https），用 Shadow DOM 与页面样式彻底隔离。
 *
 * 三条硬约束（都踩过，别改回去）：
 *   1. 本文件**不直接 fetch** 127.0.0.1 —— 内容脚本的 fetch 用页面源，会被后端严格的 CORS
 *      拒掉，还会撞 Private Network Access。所有请求都发消息给 background，由它发。
 *   2. 样式走**构造式样式表**（见 floating-css.js 顶部说明），不用 manifest 注入的 .css、
 *      不在 shadow 里塞 <style>、更不写 style="..." —— 后两者会被页面的 style-src 拦掉。
 *   3. 本文件里拼 HTML 字符串时**只能给 class，绝不能出现 style="..."**，同理会被拦。
 *
 * 工具没启动时不显示按钮（避免一个永远点不动的按钮），启动后刷新页面即出现；
 * 页面加载后 0s / 3s / 10s 各探一次，切回该标签页时再探一次。
 */
(function () {
  'use strict';

  var HOST_ID = 'dp-collect-fab-host';
  var MAX_HTML = 400000;                 // 与 background 的 grabPage 保持一致
  var PROBE_DELAYS = [0, 3000, 10000];   // 第 n 次探测前的等待

  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
    + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M12 3v11"></path><path d="M7.5 10.5 12 15l4.5-4.5"></path>'
    + '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"></path></svg>';

  var st = {
    online: false, port: 0, fabAllowed: false, busy: false,
    settings: null, ui: null, toastTimer: null, probing: false,
  };

  /* ---------- 与 background 通信 ---------- */

  function ask(type, extra) {
    return new Promise(function (resolve) {
      try {
        var msg = Object.assign({ type: type }, extra || {});
        chrome.runtime.sendMessage(msg, function (r) {
          // 扩展被重载后旧的内容脚本会失联，此时 lastError 有值，一律当作「拿不到」
          resolve(chrome.runtime.lastError ? null : r);
        });
      } catch (e) {
        resolve(null);                 // Extension context invalidated
      }
    });
  }

  function hideKey() { return 'dpHide:' + location.hostname; }

  /* ---------- 抓当前页 ---------- */

  function grabHere() {
    try {
      var root = document.documentElement;
      if (!root) return { ok: false, msg: '页面还没有 DOM' };
      var clone = root.cloneNode(true);
      // 剥掉与后端 _sanitize_page_html 相同的标签；顺便把自己的宿主节点摘掉，
      // 免得把「采集本页」按钮一起送进解析器
      var junk = clone.querySelectorAll('script,style,noscript,svg,template,#' + HOST_ID);
      for (var i = 0; i < junk.length; i++) junk[i].remove();
      var html = '<!DOCTYPE html>' + clone.outerHTML;
      if (html.length > MAX_HTML) html = html.slice(0, MAX_HTML);
      return { ok: true, url: location.href, title: document.title || '', html: html };
    } catch (e) {
      return { ok: false, msg: String((e && e.message) || e) };
    }
  }

  /* ---------- UI ---------- */

  function mount() {
    if (st.ui || !st.fabAllowed) return;
    if (!document.documentElement) return;

    var host = document.createElement('div');
    host.id = HOST_ID;
    var shadow;
    try {
      shadow = host.attachShadow({ mode: 'closed' });   // closed：页面脚本摸不到我们的影子树
    } catch (e) {
      return;
    }

    // 构造式样式表：纯 CSSOM，页面 CSP 管不到，也不会漏进页面样式表
    var sheet = null;
    try {
      if (typeof CSSStyleSheet === 'function' && CSSStyleSheet.prototype.replaceSync) {
        sheet = new CSSStyleSheet();
        sheet.replaceSync(DP_FLOATING_CSS);
        shadow.adoptedStyleSheets = [sheet];
      }
    } catch (e) {
      sheet = null;
    }
    if (!sheet) {
      // 兜底（老 Chrome）：塞 <style>，严格 CSP 的站点可能拦掉，按钮会没样式但功能正常
      var s = document.createElement('style');
      s.textContent = DP_FLOATING_CSS;
      shadow.appendChild(s);
    }

    var wrap = document.createElement('div');
    wrap.className = 'dp-wrap';
    // ⚠️ 只给 class，不要 style="..."（页面 style-src 会拦）
    wrap.innerHTML =
      '<div class="dp-toast"></div>' +
      '<div class="dp-row">' +
        '<button class="dp-btn" type="button" title="把当前页采集进客户库">' +
          '<span class="dp-ico">' + ICON + '</span>' +
          '<span class="dp-label">采集本页</span>' +
        '</button>' +
        '<button class="dp-hide" type="button" title="在这个网站上隐藏按钮（可在扩展设置里恢复）">&times;</button>' +
      '</div>';

    var btn = wrap.querySelector('.dp-btn');
    btn.addEventListener('click', doCollect);
    wrap.querySelector('.dp-hide').addEventListener('click', hideHere);

    shadow.appendChild(wrap);
    (document.body || document.documentElement).appendChild(host);

    st.ui = {
      host: host,
      shadow: shadow,
      btn: btn,
      ico: wrap.querySelector('.dp-ico'),
      label: wrap.querySelector('.dp-label'),
      toast: wrap.querySelector('.dp-toast'),
    };
  }

  function unmount() {
    if (!st.ui) return;
    try { st.ui.host.remove(); } catch (e) { /* ignore */ }
    st.ui = null;
  }

  function hideHere() {
    try { chrome.storage.local.set({ [hideKey()]: true }); } catch (e) { /* ignore */ }
    unmount();
  }

  function setBusy(on) {
    if (!st.ui) return;
    st.ui.btn.disabled = !!on;
    st.ui.btn.className = 'dp-btn' + (on ? ' is-busy' : '');
    st.ui.label.textContent = on ? '采集中…' : '采集本页';
    st.ui.ico.innerHTML = on ? '<span class="dp-spin"></span>' : ICON;
  }

  function restoreBtn() {
    if (!st.ui) return;
    st.ui.btn.disabled = false;
    st.ui.btn.className = 'dp-btn';
    st.ui.label.textContent = '采集本页';
  }

  function hideToast() {
    clearTimeout(st.toastTimer);
    if (st.ui) st.ui.toast.className = 'dp-toast';
  }

  function showToast(kind, text) {
    if (!st.ui) return;
    var t = st.ui.toast;
    t.className = 'dp-toast show' + (kind ? ' ' + kind : '');
    t.textContent = text;
    clearTimeout(st.toastTimer);
    st.toastTimer = setTimeout(hideToast, 8000);
  }

  function setBtnState(cls) {
    if (!st.ui) return;
    st.ui.btn.className = 'dp-btn ' + cls;
    setTimeout(restoreBtn, 2600);
  }

  /* ---------- 采集 ---------- */

  function doCollect() {
    if (st.busy) return;
    if (!st.online) {
      showToast('err', '本机「谷歌客户开发工具」没在运行。\n先双击 启动客户开发工具.bat，再回来点采集。');
      return;
    }
    st.busy = true;
    setBusy(true);
    hideToast();

    var grabbed = grabHere();
    if (!grabbed.ok) {
      st.busy = false;
      setBusy(false);
      showToast('err', grabbed.msg);
      return;
    }

    ask('DP_COLLECT_PAYLOAD', {
      payload: {
        url: grabbed.url,
        title: grabbed.title,
        html: grabbed.html,
        industry: (st.settings && st.settings.industry) || '',
        country: (st.settings && st.settings.country) || '',
        upgrade: st.settings ? st.settings.upgrade !== false : true,
      },
    }).then(function (r) {
      st.busy = false;
      setBusy(false);
      if (!r) {
        showToast('err', '和扩展后台联系不上（扩展可能刚被重新加载）。刷新本页再试。');
        return;
      }
      renderResult(r);
    });
  }

  function shortUrl(u) {
    try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u || ''; }
  }

  function renderResult(r) {
    if (!st.ui) return;
    if (!r || !r.ok) {
      setBtnState('is-err');
      showToast('err', (r && r.msg) || '采集失败');
      return;
    }
    if (r.existed) {
      setBtnState('is-dup');
      showToast('dup', '已在客户库，跳过\n' + shortUrl(r.row && r.row.url));
      return;
    }
    var row = r.row || {};
    var lines = ['✓ 已入库 · 评分 ' + (row.score == null ? '-' : row.score)
                 + '（' + (row.rating || '-') + '）',
                 '邮箱 ' + ((row.emails && row.emails.length) ? row.emails.join(' / ') : '未抓到'),
                 '电话 ' + ((row.phones && row.phones.length) ? row.phones.join(' / ') : '未抓到')];
    if (row.industry) lines.push('行业 ' + row.industry);
    lines.push('第 ' + (r.tier || '?') + ' 级抓取' + (r.upgraded ? '（升级到浏览器）' : ''));
    setBtnState('is-ok');
    showToast('ok', lines.join('\n'));
  }

  /* ---------- 启动 ---------- */

  function probeAndMount(i) {
    if (st.probing) return;
    st.probing = true;
    setTimeout(function () {
      ask('DP_PING').then(function (r) {
        st.probing = false;
        if (r && r.online) {
          st.online = true;
          st.port = r.port || 0;
          mount();
          return;
        }
        if (i + 1 < PROBE_DELAYS.length) probeAndMount(i + 1);
      });
    }, PROBE_DELAYS[i] || 0);
  }

  function boot() {
    ask('DP_SETTINGS_GET').then(function (s) {
      st.settings = s || {};
      if (st.settings.fabEnabled === false) return;      // 用户在设置里关了悬浮按钮
      try {
        chrome.storage.local.get(hideKey(), function (o) {
          if (chrome.runtime.lastError) return;
          if (o && o[hideKey()]) return;                 // 这个网站上被用户手动隐藏过
          st.fabAllowed = true;
          probeAndMount(0);
        });
      } catch (e) { /* ignore */ }
    });
  }

  // 切回本标签页时再探一次：常见场景是「先打开网页，才发现工具没启动，于是去启动它」
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    if (st.ui || !st.fabAllowed) return;
    probeAndMount(0);
  });

  try {
    chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
      if (!msg) return;
      if (msg.type === 'DP_GRAB') {
        sendResponse(grabHere());                      // 同步回复，供 background 兜底取页面
        return;
      }
      if (msg.type === 'DP_RESULT') {
        // 右键菜单 / popup 触发的采集，把结果也在这页弹一下（没挂载就先挂上）
        if (!st.fabAllowed) return;
        mount();
        renderResult(msg.result);
      }
    });
  } catch (e) { /* ignore */ }

  boot();
})();
