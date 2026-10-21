/* 「本轮明细」共享组件 —— 主页「📥 本轮采集明细（实时 · 待核对）」与 /manual「③ 本轮采集明细」
   共用这一份「渲染 + 逐行删除」实现。

   为什么要抽出来：这两块原来是两份近逐字重复的代码，改一边传不到另一边 —— 主页上一轮修的
   两处（末行判据、居中确认框）在 /manual 上一直没生效，而 /manual 的「行业 / 国家」两列主页
   也没有。重复的真实代价就是这个。

   ⛔ 改这个文件前先读这五条：
   1. 它是**工厂**，全局只暴露 makeLiveTable 一个名字；其余（esc / domainOf / ratingCls /
      游标 renderedRows / renderedTail / 只读态）全部关在闭包里。原因：两页各自的 <script>
      里有同名函数，而跨 <script> 的顶层 let/const 与 function 重名会直接 SyntaxError ——
      整段脚本不执行，症状是「页面控件全空」，极难排查。
   2. livedel-btn / livedel-cell / livedel-ro / liveDelModal 这几套样式是**共享的**（写在
      ui/page.html 第一个 <style> 里，由 core/ui.py 注入 /manual 与 /db），所以这里硬编码；
      只有「两页确实不一样」的东西才走 cfg（见文件末尾的 cfg 说明）。
   3. 确认框的 DOM 由本组件在初始化时建好 —— 两页都不用再手写标记，也顺带避开「弹窗必须放在
      脚本之前」那个老坑（/db 页踩过：放到脚本后面会拿到 null，绑事件时抛错把整页初始化带崩）。
      代价是**本文件必须先于各页自己的脚本执行**（模板里就是这么排的）。
   4. ⛔ 注释里别写出 /db 或本组件替代掉的那些专有选择器字面量（尤其别加前导的点或井号），
      也不要用原生确认框：ui/page.html 里有一条负向断言是按子串判的，写上就假红
      （这个坑踩过两次）。同理，类名一律 livedel- 前缀，别复用其它页的删除按钮类名。
   5. 两张表的**外部契约一个字都不能改**：轮询接口、删除接口路径、请求体的键、返回体的字段名
      （ok / deleted / rows / backup / msg）都由回归脚本按名断言；行主键按页传（主页 n、手动 rid）。
*/

function makeLiveTable(cfg){
  var tbodyId = cfg.tbodyId, emptyId = cfg.emptyId, badgeId = cfg.badgeId;
  var wrapId = cfg.wrapId || '', hintId = cfg.hintId || '';
  var attr = cfg.attr, keyField = cfg.keyField, endpoint = cfg.endpoint;
  var showExisted = !!cfg.showExisted;
  var canDelete = cfg.canDelete || function(){ return true; };
  var badgeTitle = cfg.badgeTitle || null;
  // 徽章文案：默认「N 条」（主页实时表用，它只列本轮新增，N 天然就是有效数）；
  // /manual 传 badgeText → 显示「有效 X / 共 Y」两组数（有效=新增，共=明细行数）。
  // reset() 也会用它（st 传 null）—— 所以这个回调必须能在 st 为 null 时安全求值。
  var badgeText = cfg.badgeText || function(st, n){ return n + ' 条'; };
  var afterRemove = cfg.afterRemove || function(){ return Promise.resolve(); };
  var editHint = cfg.editHint || '';
  var readHint = cfg.readHint || '';
  var removeTitle = cfg.removeTitle || '从本轮明细里删掉这一条';
  // 删除成功后的日志文案。默认这一段是**给 /manual 写的**：手动链路里 `kind='added'` 的行
  // 若已在库，删除会连客户库一起删（并可能落一份删前备份）—— 所以按 d.deleted / d.backup 报。
  // ⛔ 主页自动链路不同：采集阶段一条都没入库，d.deleted 恒为 0 —— 报「客户库里没有这条记录」
  //    会让人以为「库里有但不匹配」，所以主页自己传一段（见 ui/page.html 的 cfg.removeMsg）。
  var removeMsg = cfg.removeMsg || function(d){
    return '🗑️ 已删除一条' +
      (d.deleted ? '（客户库同步删掉 1 条）' : '（客户库里没有这条记录）') +
      (d.backup ? '，已备份：' + d.backup : '（本轮已有备份，未重复备份）');
  };
  var modalCfg = cfg.modal || {};

  // 游标：已渲染行数 + 已渲染末行的主键。两个必须一起用 ——
  // 只比长度会漏判「同一秒里删 1 条 + 又新增 1 条」（净长度不变 → 增量跳过 → 表格与后端不一致）。
  // ⚠️ 重置时两个必须一起清零，否则新一轮首帧会以为「无需重画」→ 表格永久空白。
  var renderedRows = 0;
  var renderedTail = null;
  var editable = cfg.editable !== false;
  var modal = null, okBtn = null, resolveAsk = null;

  // ---------- 闭包内小工具（行为与两页原有的同名函数一致，但不挂全局）----------
  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  function domainOf(url){
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch(e){ return url || ''; }
  }
  function ratingCls(r){
    return r === '重点客户' ? 'tag-r1' : r === '普通客户' ? 'tag-r2' : 'tag-r3';
  }
  function byId(id){ return id ? document.getElementById(id) : null; }
  function say(msg){
    try { if (typeof logBox === 'function') logBox(msg); } catch(e){}
  }

  // ---------- 居中确认框：初始化时就建好（两页都不用手写标记）----------
  function buildModal(){
    if (modal) return;
    // ⛔ 这套默认文案是**给主页自动链路写的**（/manual 在 ui/manual.html 里传了自己的 modal.body）：
    //    2026-10-13 起自动链路也是「点『📥 导出 Excel』才入库」，所以此刻这些行**还没进客户库** ——
    //    删掉只是从「待导出清单」里拿掉，客户库不动、也没有备份这回事。
    var bullets = modalCfg.body || [
      '删除后不可撤销（这会从下方「本轮明细」里永久移除）',
      '本轮明细里的行<b>还没写进客户库</b>，删掉它不影响客户库、也不会进本轮结果 Excel',
      '同一个网站的其它记录（若有）不受影响'
    ];
    var holder = document.createElement('div');
    holder.innerHTML =
      '<div id="liveDelModal" aria-hidden="true">' +
        '<div class="livedel-box" role="dialog" aria-modal="true" ' +
             'aria-labelledby="liveDelModalTitle">' +
          '<div class="livedel-t" id="liveDelModalTitle">' +
            esc(modalCfg.title || '确定删掉这一条吗？') + '</div>' +
          '<ul class="livedel-b" id="liveDelModalBody">' +
            bullets.map(function(li){ return '<li>' + li + '</li>'; }).join('') +
          '</ul>' +
          '<div class="livedel-f">' +
            '<button type="button" class="livedel-plain" id="liveDelModalCancel">' +
              esc(modalCfg.cancelText || '取消') + '</button>' +
            '<button type="button" class="livedel-danger" id="liveDelModalOk">' +
              esc(modalCfg.okText || '确定删除') + '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    modal = holder.firstChild;
    document.body.appendChild(modal);
    okBtn = modal.querySelector('#liveDelModalOk');
    modal.querySelector('#liveDelModalCancel').addEventListener('click', function(){ close(false); });
    okBtn.addEventListener('click', function(){
      this.disabled = true;                       // 防双击重复提交
      close(true);
    });
    modal.addEventListener('click', function(e){
      if (e.target === this) close(false);        // 点遮罩空白 = 取消
    });
    document.addEventListener('keydown', function(e){
      if (!modal.classList.contains('show')) return;
      if (e.key === 'Escape') close(false);
      else if (e.key === 'Enter') okBtn.click();
    });
  }

  function ask(){
    buildModal();
    return new Promise(function(resolve){
      resolveAsk = resolve;
      modal.classList.add('show');
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';    // 弹窗期间别让底下的长页面跟着滚
      okBtn.disabled = false;
      setTimeout(function(){ okBtn.focus(); }, 0); // 默认焦点给「确定删除」→ Enter 即确认
    });
  }

  function close(ok){
    if (!modal || !modal.classList.contains('show')) return;   // 防重复关闭（Esc 与点击可能同时到）
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    var fn = resolveAsk;
    resolveAsk = null;
    if (fn) fn(!!ok);
  }

  // ---------- 行渲染（统一 9 列，两页表头一致）----------
  function buildRow(r, i){
    var old = showExisted && r && r.kind === 'existed';   // 「已在客户库，跳过」的轻量行
    var mails  = (!old && r.emails && r.emails.length) ? r.emails.join(', ') : '';
    var phones = (!old && r.phones && r.phones.length) ? r.phones.join(' / ') : '';
    // 「只标记不删除」的徽章（自定义搜索词模式命中联系方式过滤时有值）。
    // 后端已把 reason 串换成短标签（core/config.py 的 MARK_LABELS），这里只负责渲染。
    // 灰字的老客户行不显示标记 —— 它本来就没进本轮结果。
    var marks  = (!old && r.marks && r.marks.length)
      ? r.marks.map(function(m){ return '<span class="live-mark">' + esc(m) + '</span>'; }).join('')
      : '';
    var key = r ? r[keyField] : null;
    var tr = document.createElement('tr');
    tr.className = 'row-new';
    // 主键用后端发的本轮内唯一值（主页 n / 手动 rid）—— 不能用位次：删完之后位次会整体前移。
    // 缺主键的行（人工造的假数据）留空串，点了不动作。
    tr.innerHTML =
      '<td>' + (key == null ? (i + 1) : esc(key)) + '</td>' +
      '<td><a class="live-co" href="' + esc(r.url) + '" target="_blank" rel="noopener" ' +
        'title="' + esc(r.title) + '">' + esc(r.title) + '</a>' + marks + '<br>' +
        '<span class="live-dom">' + esc(domainOf(r.url)) + '</span></td>' +
      '<td class="live-cell" title="' + esc(old ? '' : mails) + '">' +
        (old ? '<span class="live-miss">已在客户库</span>'
             : (mails ? '<span class="live-mail">' + esc(mails) + '</span>'
                      : '<span class="live-miss">未抓到</span>')) + '</td>' +
      '<td class="live-cell" title="' + esc(old ? '' : phones) + '">' +
        (old ? '<span class="live-miss">—</span>'
             : (phones ? esc(phones) : '<span class="live-miss">未抓到</span>')) + '</td>' +
      '<td class="live-sc">' + (old ? '' : (r.score == null ? '' : esc(r.score))) + '</td>' +
      '<td>' + (old ? '' : '<span class="tag-r ' + ratingCls(r.rating) + '">' +
                          esc(r.rating) + '</span>') + '</td>' +
      '<td>' + esc(r.industry || '') + '</td>' +
      '<td>' + esc(r.country || '') + '</td>' +
      '<td class="livedel-cell"><button type="button" class="livedel-btn" ' + attr + '="' +
        esc(key == null ? '' : String(key)) + '" title="' + esc(removeTitle) + '">✕</button></td>';
    return tr;
  }

  // 只追加新增行（增量），避免每秒整体重绘导致滚动位置和 hover 状态丢失。
  function render(rows, st){
    var tb = byId(tbodyId);
    if (!tb) return;
    var empty = byId(emptyId), badge = byId(badgeId);
    if (!Array.isArray(rows)) rows = [];
    var tail = rows.length ? rows[rows.length - 1][keyField] : null;
    // 需要整体重画（不能用增量）的两种情况：
    //   ① 条数变少 —— 新一轮从 0 开始，或被删过；
    //   ② 已渲染的末行在后端列表里的主键变了 —— 说明中间有行被删/被换过（位次整体前移）。
    if (rows.length < renderedRows || (rows.length && tail !== renderedTail)){
      tb.innerHTML = ''; renderedRows = 0;
    }
    for (var i = renderedRows; i < rows.length; i++){
      tb.appendChild(buildRow(rows[i] || {}, i));
    }
    renderedRows = rows.length;
    renderedTail = tail;
    if (badge){
      badge.textContent = badgeText(st, rows.length);
      // 「有效数」可能不等于「采集总数」—— 让页面把算式写在悬停里，别让人以为表漏写了。
      badge.title = badgeTitle ? (badgeTitle(st, rows.length) || '') : '';
    }
    if (empty) empty.style.display = rows.length ? 'none' : 'block';
    var sc = tb.closest ? tb.closest('.live-scroll') : null;
    if (sc) sc.scrollTop = sc.scrollHeight;       // 有新行时自动滚到底部
  }

  // ---------- 只读态：由各页传进来的 canDelete() 决定 ----------
  function syncEditable(n){
    editable = !!canDelete();
    var wrap = byId(wrapId), hint = byId(hintId);
    if (wrap) wrap.classList.toggle('livedel-ro', !editable && n > 0);
    if (hint){
      if (editable) hint.textContent = editHint;
      else if (n > 0) hint.textContent = readHint;
      else hint.textContent = '';
    }
  }

  // ⚠️ 事件委托挂在 tbody 上，不要逐行绑：行是 innerHTML 拼好再 appendChild 的，
  //    删行后整表会重画、换轮时也会清空，逐行绑的监听会跟着丢。
  function onClick(e){
    var btn = (e.target && e.target.closest) ? e.target.closest('.livedel-btn') : null;
    if (!btn) return;
    if (!editable) return;                        // 采集已结束 / 正在导出 → 整表只读
    var raw = btn.getAttribute(attr);
    if (raw === null || raw === '') return;       // 没有主键的行不动作
    var key = Number(raw);
    if (!isFinite(key)) return;
    return remove(key);
  }

  function remove(key){
    return ask().then(function(yes){
      if (!yes) return;                           // 取消 → 一个请求都不发（不做「先发后撤」的假动作）
      var body = {};
      body[keyField] = key;
      return fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      }).then(function(r){ return r.json(); }).then(function(d){
        if (!d.ok){ say('⚠️ 删除失败：' + (d.msg || '未知原因')); return; }
        say(removeMsg(d));
        return afterRemove();                     // 立刻重拉一次，表格/徽章不用等下一个整秒
      });
    });
  }

  // 换一轮时清零：游标两个必须**一起**清（只清 renderedRows 会让新一轮首帧判定「无需重画」→ 永久空白表）
  function reset(){
    renderedRows = 0;
    renderedTail = null;
    var tb = byId(tbodyId);
    if (tb) tb.innerHTML = '';
    var badge = byId(badgeId);
    if (badge){ badge.textContent = badgeText(null, 0); badge.title = ''; }
    var empty = byId(emptyId);
    if (empty) empty.style.display = 'block';
  }

  buildModal();                                   // 初始化即建好，保证 #liveDelModal 始终存在

  return {
    render: render,
    syncEditable: syncEditable,
    remove: remove,
    onClick: onClick,
    reset: reset
  };
}
