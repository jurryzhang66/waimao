# 细节备份：功能坑 / 回归脆弱点 / 本机环境 / 外部站点

> MEMORY.md 有注入长度上限，超了会被截断 → 「细节」放这里，「硬约束」留在 MEMORY.md。
> **改 飞书 / 搜索 / 地图 / 扩展 / 词库 / 本机环境 / 回归脚本 / 海关采集 之前，先读本文件。**

## 飞书 / 搜索 / 地图 / 扩展（坑全在档案 M1/M2/M5/M8/M9，动手前必读）
- ① 飞书调用前 `pop('HERMES_HOME')`，**字段名就叫 `官网`**，`+field-update` 是**全量 PUT**，结果 Excel **无来源列** → `build_feishu_records()` 按 domain 回库查来源（**50 分门槛对 `[手动采集]` 豁免**）。
- ② 词库 `cond_template(key, lang)` 是**唯一出口**，模板 `{p}` **别加引号**、含 OR **必须用括号**；`COUNTRIES` 是 **4 元组**而前端按 **5 元组**注入（改长度炸两处）；改库后跑 `_kwlib_check.py`。
- ③ 开页必须走 `open_search()`，判跳转必须用 `_is_search_engine_url()`（硬编码 `google.com/goto` 在 `.com.hk` 上一页 10 条全丢）；`enrich()` 用 `new_tab()` 而 `open_search` 用 `get()` → 补全后必须 `_back_to_search()`（`ChromiumTab` **没有 `new_tab()`**）。
- ④ 扩展 `background.js` 是**唯一 fetch 出口**（`popup.js` 里 `fetch(` 必须为 **0**）；CORS 只回显 `chrome-extension://`（**绝不 `*`**）；地图滚 `div[role="feed"]` **本身不是 window** 且**身份词必须拼进查询词**（`maps_role_word`）。
- ⑤ **邮箱噪声过滤**（`_is_noise_email()`，2026-10-10 加）两处**别改回去**：
  - 倍图规则 `NOISE_EMAIL_DIM_RE = ^(?:\d+x|x\d+)$` **绝不能加裸数字分支 `^\d+$`** —— 会误杀 `163.com` / `126.com` / `139.com` 这类**纯数字 label 的合法邮域**（实测确认）。
  - 宿主黑名单**必须后缀匹配**（`dom == h or dom.endswith('.' + h)`），老写法 `n in dom` 会把 `mywix.com` / `shopwix.com` 一起误杀。
  - 过滤判据**只加在 `clean_emails` 这一处**即可覆盖全部 4 条链路；**不要去剥 `<script>`**（会让 JSON-LD 里的真实联系邮箱一起丢）。`EMAIL_OK` 有 3 份独立副本，改抽取不改导出（老脏数据仍会进 Excel/飞书）。

## 本机环境 / 数据待办（清单见档案 §7、§7.5、§9.4）
- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c`；**别从 Bash 里 invoke PowerShell**；`wmic` 屏蔽 → `Get-CimInstance Win32_Process`。项目解释器 `D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`（managed 3.13.12 没装 DrissionPage/Flask）；启动 = 根目录 `python 客户开发工具.py`。TCP 保留段每次开机漂移 → **别把「某端口被保留」写进断言**（`_check_startup` 原 `assert got_port != 5000` 就是这类假红；2026-10-06 已改成 `can_bind(got_port)` + Flask 能起来。查证：`netsh int ipv4 show excludedportrange protocol=tcp` 现在最早一段是 **5357**，5000 已可用）。`C:` 紧张 → 回归临时目录已钉 D:。
- ⛔ **评分在非英语场景方向是反的**（法国实锤，未修）：`CTYPE_WORDS` 全英文、`score_item()` **只有加分无减分**。其余待办：平台垃圾域名 25~38 条未清、`重标行业.py` 待改 **23 条**（未 `--apply`）、评分/冷会话/飞书垃圾/阶段 B 拆包未拍板、**M16/M17/M18 未 commit**。
- ✅ 已拍板（别再当待办）：`DB/backups/` 少掉的几份 + `关键词库.json.bak*` 是用户自己删的，不恢复、不排查。

## 回归脆弱点（假红 ≠ 产品 bug）—— 红了先看错误类型
- 别写死端口原因 `'10013'`；**也别写死「某端口被保留」**（`_check_startup` 原 `assert got_port != 5000`，TCP 排除区间随开机漂移 → 环境变好了反而报红；已改 `can_bind(got_port)`）。
- ⚠️ `_check_startup` B 段在**工具开着**的时候跑：`5000` 被用户实例占着 → 子进程顺延到 8000，`can_bind(got_port)` 依然能过（Werkzeug 有 `SO_REUSEADDR`）。但**别把 `pick_port` 的探测简化成只探 `host`**：`host='0.0.0.0'` 时会绑上被回环占用的端口（见 M26）。
- 别写死 managed 运行时的**版本号目录**：`_check_ext.py` / `_run_all_reg.py` 原写死 `node\versions\22.22.2-3\node.exe`，本机升到 `22.22.2-6` 后 `_check_ext` 的 B 组与两个 JS 冒烟**全部 FileNotFoundError**（看着像「回归红了」，其实是环境漂移）→ 已改成扫 `versions/*/node.exe` 取最新，末位才退回旧写死路径。
- 别 sleep 等 async → 轮询；截图只当证据（`try/except`）且**固定定位元素必须视口截图**。
- `_smoke_ext_live` 两遍共用 `core.db` → 时间戳要清零；`<select>` 赋不存在的 value 会被忽略 → 用 `createElement('option')`。
- `send_file` 持句柄 → 删前 `dl.close()`；别沿用上一段页面状态；行名/数量动态取。
- 临时库默认落 `C:`（满则 `disk I/O error`、一批 DB 项集体假红）→ 已钉 `TMPDIR/TEMP/TMP` 到 `.workbuddy/_reg_tmp`。
  - ⚠️ 同类症状还有 **`sqlite3.OperationalError: attempt to write a readonly database`**（杀软/IO 抖动锁住刚建出来的 sqlite，或 `-wal/-shm` 建不出来）—— **单跑一遍往往就绿**，别去改产品代码。判据：红了先看错误类型，再看**单跑能不能复现**。
  - 注意：`TEMP` 的钉扎只在**走 `_run_all_reg.py`** 时生效；**单跑某个脚本**时它仍落 `C:\Users\admin\AppData\Local\Temp`（所以单跑更容易撞见这类假红）。
- **备份名只到秒** → 同秒删两次覆盖同名 → 「文件名差集」断言假红 → 改判 **mtime**。

## verbatim / 静态断言注意
- `_check_page.py` R4 glue：`'from core.ui import PAGE_HTML, _build_page'` 必须**单独一行**。
- R12 一批 verbatim 断言（`renderedTail`/`closest('.livedel-btn')`/`id="liveDelModal"`/两条 CSS 规则/`Escape`/`Enter`/两页 `<thead>` 逐字相等…）—— 泛化后要**逐条对着新代码重对**，**该改断言就别改代码**。
- 静态断言看**代码**不看源码文本：用 `ast`；`STATE['xxx']` 是 `ast.Subscript`+`ast.Constant`，不是 `ast.Name`。
- `_smoke_ext_popup.js` 的 DOM 桩很薄（无 `dataset/classList/closest`，`document` 只有 `getElementById`）。

## 「本轮明细」计数口径（M19，2026-10-10）
- 徽章 / 状态行报**两组数**：`有效` = 新增（`st.added`，＝结果 Excel 的行数）/ `共` = 明细行数（`session_rows.length` = 新增 + 已在库）。
- ⛔ **本轮已结束时**（`session_active == false`）`_flush_manual_session` 会把 `session_rows` 清空、但**刻意留着 `added`/`existed`** 给 `roundTally` 拼「本轮写入 X 行新客户」→ 徽章与悬停**必须按 `session_active` 门禁取这两个数**，否则会显示 **「有效 5 / 共 0」**（自相矛盾）。`_smoke_ext_popup.js` 7a 段、`_check_manual_ui.py` E 段的 `liveBadgeText(null,0)` / `{session_active:false,…}` 两条断言就是钉这个的（改动前真跑红过一次）。
- 这份口径有**三处独立实现**，改口径要一起改：`ui/manual.html::liveBadgeText()`、`extension/popup.js::renderSession()`、以及共享组件 `ui/live-table.js`（主页那张仍走默认 `n + ' 条'`，它 `showExisted:false`、N 天然＝有效数）。**`popup.js` 那份不在共享组件里**。
- 改 `ui/live-table.js` → **只重算 `_check_page.py` 的 `_BUILT_SHA`**（`_TMPL_SHA` 是 `ui/page.html` 的原文，不动）。

## 海关商品编码采集（`海关商品编码采集.py` + 同名 `.bat`，2026-10-06）
- ⛔ 站点 `stats.customs.gov.cn` 挂**瑞数信息动态防护**：普通 HTTP 客户端一律返回 **412**，响应体是 `$_ts` 变量 + 混淆 JS（`/Qy6JDI4LYvbD/….js`）+ meta refresh + `SF_cookie_251`。**纯 requests / urllib 拿不到任何数据** → 只能真浏览器（复用 `create_browser_page()`，别另写一套 `ChromiumOptions`）。
- 入口：`GET /queryData/selectCodeTs`（**服务端整页渲染**，不是 AJAX）；菜单里的入口是 `/paramManager/selComplexList`（商品参数）。
- 取数配方：在 `#Search_form` 里设 `codeLength=8`（**隐藏域和 4 个同名 radio 都要设**）+ `pageSize=200`（**页面默认是 10**，不设会变成 897 页）+ `yearId` + `codeTsList=''` + `searchKey=''` + `pageNum=n` → `form.submit()` → 整页跳转。
- **参数闸门**：`yearId='2025'` → **8969** 条 / 45 页；`yearId=''`（不限年份）→ **104238** 条 / 522 页。核对：44×200 + 末页 169 = 8969；首行 `01012100 改良种用马`，末行 `99000000 跨境电商B2B简化申报商品`。
- ⛔ 名称取 `.th-line` 的 **`title` 属性**：可见文本被 CSS 截断（8969 条里 35 条形如 `…`）。
- ⛔ 就绪判据 = 「`hidPageNum` == 目标页号 **且** 行数 > 0」；只看「有没有行」会在提交后的一瞬间**静默读到上一页**。
- `page.run_js` 里**裸 IIFE 必须加外层 `return`**（`return (function(){…})();`），否则取不到返回值 → 会被误判成「找不到 `#Search_form`」。
- `.bat` 用 `Write` 工具落盘即 **GBK + CRLF**（实测，与既有两个 `.bat` 一致）；**别用 bash heredoc 拼**（`\\` 会被改写成 `//` → 路径坏掉 + 中文脚本名「找不到文件」）。
- ⛔ `page.get('http://stats.customs.gov.cn/')` 会**偶发**返回 **39 字节空文档**（`<html><head></head><body></body></html>`）。这**不是被封**：同一时刻 `requests` 仍能拿到标准的 412 挑战页（~2440 字节）。空文档**不会自愈，傻等只会超时** → 必须**重新导航**重试（`_open()` 已做 4 轮重开 + 每轮最多 20s 轮询）。
- 断点缓存 `.workbuddy/_海关编码_pages.json`：45 页全命中 → 直接汇总、**不开浏览器**（秒级）；`--fresh` 强制重抓，`--dry` 只探总数。

## 过滤项拆卡 / 页面语法展示（M23，2026-10-19）
- ⛔ **`insertAdjacentHTML` 拼 `value="${...}"` 遇双引号会被截断**：`-"China manufacturer" -"Chinese supplier"` 解析出来只剩 `value="-"`，随后的 `filter(v => v && v !== '-')` 把它当空值丢掉 → **组合预览少 3 个排除词，而后端实搜照样拼上**（这就是「预览与实搜不一致」的隐形来源）。修法只有一个：`value="${esc(e[1])}"`。`_check_page.py` R14 有正负向断言（`value="${e[1]}"` 必须消失）。
- ⛔ **`#excludesWrap` 那一行是逐字契约**：`onSource()` 里 `document.getElementById('excludesWrap').style.display  = maps ? 'none'  : 'block';` —— `display` 与 `=` 之间是**两个空格**，`_check_page.py` 有 verbatim 断言。重排/格式化这行会直接红。
- ⛔ **地图模式只能藏 `#excludesWrap`**：`#chinaFilters`（14 项里多数在结果阶段判断）与 `#contactFilters`（地图直接给电话）**仍生效**，藏了就是静默丢功能。`_check_maps_ui.py` 改用 `getComputedStyle` + `offsetParent`，只读 inline style 抓不到「外层被藏」。
- ⛔ **批量按钮别跨组连坐**：`toggleDomainFilters()` 同时管 `#excludes` + `#chinaFilters`，但在 `curSource() === 'maps'` 时**必须跳过 `#excludes`**（那时它 display:none，用户看不见却会被清空）。
- ⛔ **分组真源在 `core/config.py::CONTACT_FILTER_KEYS`**，经 `core/ui.py` 作为 `CHINA_FILTERS_PLACEHOLDER` JSON 的**第 5 个字段**注入，前端按 `e[4]` 分流。前端**不许**再写一份 key 列表。
- 计数口径：`#chinaFilters .china-filter` = **14**、`#contactFilters` = **4**、`.syn` 共 **18**、`.syn-off` 共 **8**（域名组 4 项 query 为空 + 联系组 4 项）、`#excludes input` = **6**（`EXCLUDE_OPTIONS`）。`_check_live_ui.py` H 段按这几个数断言，改成员时一起改。
- ⛔ **两张清单都是注入数据、不是模板原文**：往 `EXCLUDE_OPTIONS` 或 `CHINA_FILTER_OPTIONS` 加一项（如 2026-10-19/20 的 youtube / facebook / temu）只动 `core/config.py` → `_check_page.py` R5 **只有 `_BUILT_SHA` 变**，`_TMPL_SHA` 不变；项数断言在 `_check_live_ui.py` H 段（`chinaN` / `synN` / `exclOn`）。⚠️ 归属别搞混：YouTube/Facebook 是国际平台 → `EXCLUDE_OPTIONS`；Temu 是中国电商平台 → `CHINA_FILTER_OPTIONS`（用户点名「像淘宝一样」）。

## 主页「上次参数」记忆（M25，2026-10-20）
- ⛔ **点控件会自动存盘**：`ui/page.html` 里 `change`/`input` → `savePrefs()`（400ms 防抖）→ `POST /api/ui_prefs`。
  任何会打开主页并操作控件的测试（`_check_live_ui` / `_check_maps_ui` / `_check_kwlib_ui` / `_check_startup`）
  都**必须**有 `DP_UI_PREFS=<临时文件>`，否则会把测试点出来的国家/条件写进用户真实的 `DB/ui_prefs.json`。
  `_run_all_reg.py` 已统一注入（每个测试一个独立文件）；**单项直跑时脚本自己设**（`_check_live_ui` 开头已设）。
- ⛔ **恢复顺序**：`loadPrefsAndStart()` = `await loadKeywords()` → `GET /api/ui_prefs` → `applyPrefs()`。
  倒过来 → 行业/品类/产品三级下拉还没有 option → `set value` 静默失败，页面表现就是「只记住国家，行业没记住」。
- ⛔ **`lang` 要最后设**：`onIndustry()` 内部会调 `applyCountryLang()`，按国家把语言重置成默认值。
- ⛔ 恢复里**漏一项不报错**（那一项悄悄不记忆）：加字段要同时改「`collectPrefs` / `applyPrefs` /
  `UI_PREF_KEYS` / `_check_page.py` R15 白名单」。`_check_live_ui.py` J 段只覆盖数量/国家/条件三项，
  其余字段靠 `_smoke_search.py` ⑦ 的文件内容断言兜。

## 多端看同一任务（M27，2026-10-20）
- **症状**：电脑点了「开始」看得到进度，手机打开同一个 URL 永远是「本轮已采 0 个网站」、
  明细表空白 —— 用户会怀疑「是不是两个页面 / 两份数据」。**不是**：`STATE` 是进程内单例，
  `/api/status` 直接读它。缺的是**前端订阅**（`poll()` 只在 start/export 里 `setInterval`）。
- ⛔ 别把「完成 / 待核对」分支写成 `if (!d.running && d.done && polling)`：首次 poll 时
  `polling` 还是 null（手机刚打开就是首次）→ 状态行、按钮永远不刷新。`clearInterval` 才需要它非空。
- ⛔ 数据源别只用前端局部变量 `RUN_SOURCE`：没走过 `start()` 的那一端永远是默认 `'google'`
  → 地图任务显示「搜索中 / 个网站」。必须 `STATE['source']` → `/api/status.source` → 前端。
- 收尾要复位 `STATE`（`running=False, source='google', rows=[], n_seq=0`），否则后面的段会看到
  「运行中」残留。

## 主页心跳调度（M28，2026-10-20）
**症状**：手机切到别的 App / 锁屏再回来，页面停在旧数据，只能手动刷；手机先开着页面、电脑才点「开始」，
手机永远不动（原来空闲时`一次都不轮询`）。
- ⛔ **设备判定不许用 `window.innerWidth`**：无头 / 窄窗 Chrome 会被判成手机 → 运行中节奏变 2s →
  `_check_live_ui` K 段那句 `time.sleep(2.2)` 假红。只认 `pointer: coarse` / `maxTouchPoints` / UA。
- ⛔ **后台只许降频（10s），不许 `clearTimeout` 停摆**：老 Safari / 被系统冻结时不派 `visibilitychange`
  → 页面永久不更新，且没有任何报错。
- ⛔ **两个 `finally` 是地基**：`pollBusy = false`（不复位＝永远不再发请求）、续排/停链分支
  （判错要么退化成空闲也在刷、要么任务跑起来也不更新，两个方向都静默）。`renderUpdatedAge()` /
  `pollTick()` 都要能容错，元素取不到直接 return。
- ⛔ **空闲彻底停链**（用户 2026-10-20 拍板「不跑任务的时候不要刷新」）：`shouldKeepTicking()` 为假就
  `stopPolling()`，且**必须复位 `pollStarted=false`** —— 不复位则下次 `startPolling()` 直接 `return`，
  表现为「点了开始却再也不刷新」。别再加空闲间隔常量。
- ⛔ **`pollTick` 必须 `async` + `await pollOnce()`**：不 await 就在 `finally` 里判「继续/停链」，拿到的是
  **上一帧**的 `pollRunning` → 从空闲被 `kickPoll` 拉起的第一拍误判「没在跑」→ 立刻停链（看着像补拉没生效）。
- ⛔ **空闲态「更新于」必须清空**：链停了那个时间戳会冻住（「更新于 刚刚」永远不变 = 骗人）。
- ⛔ `renderUpdatedAge` 里的空闲判据是 `!pollRunning && !pollFails`：断网重试期间要留着「连接中断」提示。
- ⛔ **`since` 自愈**：`api_start` / `api_export_feishu` 会 `logs=[]`，别的设备的 `since` 停在大数字 →
  `logs[since:]` 恒空 → **日志区永久空白**。后端 `STATE['round']` 在这两处 `+1`、`/api/status` 回传。
  ⛔ `lastRound === null` 首帧必须是「只采纳、不清屏」；写成 `round !== lastRound` 会因 `null !== 0` 恒真
  → 每帧清屏 → 同样永远空白。换轮那一帧的 `logs` 是旧 `since` 切的残片，必须 `pollRefetch` 立刻重拉。
- ⛔ `/api/export_excel` 的 `round` **不许** `+1`（它不清 logs）；`exportExcel()` 里**不许** `since=0`
  （原来那行是 bug：整轮日志会重复追加一遍）。
- ⛔ 「更新于」`#updatedAt` 必须是 `#status` 的**兄弟**节点 —— `#status` 每次 `innerHTML` 整块重写。
- ⛔ 新加的顶层名字全带 `POLL_*` / `poll*` / `lastRound` 前缀：与 `ui/live-table.js` 跨 `<script>` 重名
  = SyntaxError 后整段不执行（`node --check` 逐段查抓不到）。R17 按「列 0 声明集合」守，**别把缩进的
  `var esc/domainOf/ratingCls`（在 `makeLiveTable` 闭包里）算成顶层**，那会假红。
- `_check_live_ui.py` K2 段现在分两半：**K2**（空闲 6 秒 `/api/status` 命中数必须为 **0**、`pollStarted` 为假、
  `#updatedAt` 为空）+ **K2b**（dispatch 一次 `visibilitychange` → 恰好 **1** 个请求、跟上运行中并续上 1s 节奏）。
  K2b 的 `sleep` 只等 0.8s：等久了会撞上下一个整拍（多一次请求，`hits==1` 就假红）。
  页面里用 `window.__statusHits` + 包一层 `window.fetch` 计数，**必须在 `page.get()` 之后注入**（导航会清 window）。

## 监听地址 / 手机访问（M26，2026-10-20）
- **症状**：手机打不开工具页面，`127.0.0.1` 和电脑的 `192.168.6.239` 都不行。**根因不是防火墙**（该机防火墙本就关着），
  是 `HOST='127.0.0.1'` —— 回环地址只收本机连接；手机填 `127.0.0.1` 指的是手机自己，填电脑 IP 则没在网卡上监听。
- ⛔ **`pick_port()` 每个候选要探两个地址** `(127.0.0.1, p)` 和 `(host, p)`：
  `host='0.0.0.0'` 时 Windows 上即使回环已被占，通配地址**仍能 bind 成功**（对方有 `SO_REUSEADDR`，
  Werkzeug 默认设）→ 两个实例挑中同一端口、日志打同一个 URL，但访问落到**先启动的进程**（Windows 具体地址优先）→
  用户以为「新实例没生效」。实测：改造前 `pick(0.0.0.0)=5000` 而 `pick(127.0.0.1)=8000`（5000 被正在跑的工具占着）。
- ⛔ 启动日志里 `http://127.0.0.1:{PORT}/` 那行的**格式**被 `_check_startup.py` 正则
  `r'http://127\.0\.0\.1:(\d+)/'` 抓 → 改成 `0.0.0.0` 或删掉，真机 e2e 立刻抓不到 URL 报红。
- `lan_ip()` 用 UDP `connect(('8.8.8.8',80))`（**不发包**）让系统按默认路由选网卡，比 `gethostbyname_ex` 可靠
  ——后者在有 VMware / Hyper-V 虚拟网卡时经常把 `192.168.189.1` 之类排在前面。APIPA（169.254.x）/ 回环 → 返回 `''`。
- 手机仍连不上时按序查：① 是否同一路由器（不是 4G/5G）② 路由器「AP 隔离 / 客户端隔离」③ 地址用 `192.168.6.x`
  那个 ④ `lan_ip()` 可能猜中虚拟网卡 → `ipconfig` 看真实那块。

## 谷歌反爬 / 验证码（M29，2026-10-21）

- **症状**：随便跑两下就出「我们的系统检测到来自你的计算机网络的不寻常流量」。
  **用户第一反应是「搜索框提交频率太高」→ 不是。** `search_url()` 拼好 URL 直接 `page.get()`，
  从不在搜索框打字（只有连续 3 次失败才降级到「点搜索框 + 回车」）；默认参数一轮只发 4~6 次 SERP。
- 真因四件叠一起：① 每次任务全新空白 profile（无 cookie，每次都像从未见过的访客）；
  ② 自动化特征没藏；③ **认不出外语/新版拦截页** → 被 `wait_results` 判成「没渲染」→ 15s 内同 URL 连发 3 次；
  ④ 撞码后 `continue` 跳过延时立刻发下一条，且无请求计数、无熔断。
- ⛔ **持久 profile 的静默风险**（`DB/_chrome_profile`）：
  - `set_user_data_path()` 内部就是 `--user-data-dir`，DrissionPage **不检查目录非空**；
    若另一实例正用同一目录，Chrome 会把新实例的请求转给它、自己立刻退出 → 表现为「启动即失败」。
    所以 `_profile_busy()` 必须**先探活**（读 `DevToolsActivePort` 里的端口 + `socket.create_connection(timeout=0.3)`），
    占用就退回一次性 profile —— **宁可不复用 cookie，也不能让任务起不来**。
  - `_clean_profile_locks()` **只准碰 5 个确切文件名**（`SingletonLock`/`SingletonSocket`/`SingletonCookie`/
    `lockfile`/`DevToolsActivePort`）。⛔ 绝不能用 glob 或删整个 `Default` —— 那是真数据目录（cookie/缓存）。
    干净的 `quit()` 本来就会自己删这些锁，只在崩溃残留时才需要手动清。
  - ⛔ `.gitignore` 必须忽略 `DB/_chrome_profile/`：里面是真实谷歌 cookie（NID 等），
    **本仓库是 public**，提交一次等于把登录态公开。⛔ 别图省事写 `DB/*` —— `客户库.sqlite3` 与 `ui_prefs.json` 是要跟踪的。
- ⛔ **验证码判据的三个错误写法**（都会造成静默故障）：
  - `'recaptcha' in html` → **100% 误报**：正常搜索结果页也加载 reCAPTCHA 资源（`/recaptcha/api.js`）。
    只在 `deep=True` 时取整页 html，且只查「不寻常流量」类**文案**（覆盖英/法/德/西/意/荷）。
  - 只查英文文案 → 德语站、法语站拦截页认不出 → 被当成空结果重发 → **越救越封**。
    所以第一级判据用 **URL 片段**（`/sorry/`、`google.com/sorry`、`/recaptcha/`），语言无关。
  - 不加 `states.is_loading` 门禁就读 `page.url`：加载中读到的是**上一页**地址 → 判据全错。
    该字段是纯本地状态（零 CDP 往返），先读它不花钱。
- ⛔ **`wait_results` 必须三态**（`'ok'`/`'empty'`/`'blocked'`）：旧代码把「被拦截」当「没结果」→
  重开一次再等 12s，等于对拦截页再打一次。`'blocked'` 只能退避，**不许重发**。
  `_check_serp.py` 里有一条静态断言专门禁 `if wait_results(page` 这种布尔用法。
- ⛔ **节奏只能走 `serp_pace()`**：写死 `sleep(...)` 的后果是「点停止后还要硬等 14 秒」，
  而且**翻页、重试、撞码后重发这些路径最容易漏加**——所以计时统一由 `_serp_tick()` 记（所有 SERP 请求都算一次），
  `serp_pace()` 内部再按 `sleep_check()` 睡（可被停止信号打断）。
  偏态随机 `u ** 2.2` 是为了「多数短、偶尔很长」，比均匀分布更像人。
- ⛔ **撞码熔断**：60s / 180s 两轮退避 + `retry()` 重发原 URL；两轮仍不通 →
  `with STATE_LOCK: STATE['stop']=True` 后**在锁外** `log()`。锁内 log 必死锁（`log()` 自己抢 `STATE_LOCK`）。
  调用点必须 `return` 而不是 `continue`：`continue` 会回到 for 循环开头**立刻又发一次**，
  熔断等于白做。撞码重发**不占** attempts 名额（用户手动解完验证应当还能继续跑）。
- ⛔ `--disable-blink-features=AutomationControlled` **全项目只许一处**（`create_browser_page` 里）：
  `add_init_js` 只作用于当前 tab，`enrich()` 里 `new_tab` 出来的页面**不继承**，用它等于半藏半露。
  实测 `navigator.webdriver` 本来就是 `false`（DrissionPage 默认已处理），这个开关只是保险。
- **别对用户承诺「不会再出验证码」**：谷歌风控是多因素加权，**出口 IP 权重很高**。
  本机 IP 若已被标记，慢速 + cookie 只能缓解。诚实说法：大概率有效但不保证；且 10 条会从 1~2 分钟变成 3~6 分钟。
- 关联改动：`db_has_customer()` / `_live_has_url()` **前移到 `enrich` 之前** ——
  重复客户不再白跑一次补全（省请求也省时间）。补全内部开头加 `sleep(0.5~1.5)`。

## 「停止」迟迟不生效（M30，2026-10-21）

- **症状**：任务跑着点「■ 停止」，界面上按钮纹丝不动、状态行还在写「搜索中…」，
  要等十几秒到两分钟才真的停。用户第一反应是「停止接口慢」→ **不是**。
- ⛔ `/api/stop` 只做三件事：置 `stop`/`stopping`/`stopped`，**不持锁、不做 IO**，毫秒级返回。
  千万别在这里加 `with STATE_LOCK`：`log()` 内部也抢同一把锁，worker 正在写日志时两者互等，
  「按了没反应」会从 2 秒变成不可预期。
- 真因全是**读侧**（这些点以前根本不看停止标志）：
  - `page.get()` **一次最坏 126 秒** —— DrissionPage 出厂 `page_load=30s` × `retry_times=3`（4 次尝试）+ 3×2s。
    全项目以前一个 timeout 都没传过。`_wait_loaded()` 是**阻塞**的，期间读不到 `STATE['stop']`。
  - `enrich()` 一个客户要开 3 个页面（首页 + 2 个联系页）→ 最坏压住停止键 **7 分钟**。
  - `wait_results()` 12 秒窗口里不看 stop；`has_captcha(deep=True)` 的 `page.url`/`ele`/`html`
    都可能**隐含** `doc_loaded(base=10)`。
  - `running=False` 写在 `page.quit()` **之后**（quit 还要 kill 进程 + `tasklist` 循环最多 5s）。
  - 前端 `stop()` 只有一行 fetch：不 disable（可以连点，每点真发一个 POST）、不改文案、
    不 `kickPoll()`（还要等下一拍才更新）。
- ⛔ **判据**：界面上一切「停止后还在转」的现象，先问「此刻阻塞在哪个 Python 调用里」，
  再去那个调用里补检查 —— 别去优化 `/api/stop`，它本来就是快的。
- ⛔ **`page.get` 不许再裸写**：全项目只允许 `nav()` 内部出现（`_check_stop.py` 用 ast 遍历
  `page.get`/`tab.get` 的调用点，出现第二个函数名就报红）。裸写一次 = 把 126 秒请回来。
- ⛔ **超时 ≠ 停止**：`nav()` 预算耗尽返回 True（带着已加载内容继续），只有用户停止才返回 False。
  混成一个返回值，慢站一超时就会被上层当成「用户停止」，整轮任务被误杀。
- ⛔ **`retry=0` 别改**：重试是调用方的职责（`open_search`/`maps_open` 的 attempts）。
  在 nav 里重试会让「一次导航」偷偷变成 4 次请求 —— 既拖慢停止，也更容易撞验证码。
- ⛔ **`running` 语义不许动**：它仍要等 `quit()` 之后才 False，因为还兼着「开始按钮能不能点」。
  提前放开会让用户在上一个 Chrome 还没退干净时开新一轮 → 两个实例抢同一个 `--user-data-dir`
  （Chrome 会把请求转给先启动的那个，新实例立刻退出，表现为「启动即失败」）。
  要表达「正在收尾」就用 `stopping`，别去动 `running`。
- ⛔ **轮询会把停止键重新点亮**：`poll()` 每拍都 `setButtons(true)`，所以 `setButtons` 必须判
  `pollStopping`，否则用户刚点完灰掉的按钮 1 秒后又亮了，看起来像没点着。
  `/manual` 是完全一样的坑（`loadManualState` 每秒写 `btnStop.disabled = !st.running`），
  用顶层 `stopPending` 挡，并在 `st.running` 变 false 时复位。
- ⛔ **半截数据必须丢**（用户拍板）：`enrich` 被停止时返回 `{'stopped': True, ...}`，
  调用方看到就 `return`，那一行不进 `STATE['rows']`、不入库。
  只打标记不丢 = 客户库里出现「有邮箱没电话」的残缺记录，事后极难发现。
- ⛔ 改 `ui/page.html` 后**两个 sha256 都要重算**（`_TMPL_SHA` 与 `_BUILT_SHA`），
  并且要重启工具 —— 否则真机看到的还是旧页面，会得出「改了没用」的错误结论。

## 联系方式抓不到 / 抓取成功率突然下降（M31，2026-10-21）

- **症状**：用户说「我打开网站就能看到 email，工具抓不到」，或「改完之后成功率掉了一半」。
  先别怀疑选择器或正则 —— 先确认**读的时候页面到底渲染到哪一步了**。
- ⛔ **`page.get()` 超时会 `Page.stopLoading()`**（DrissionPage 4.1.1.4 的 `_wait_loaded`）：
  ```python
  if err:
      ...
      self.stop_loading()      # 而且 finally 里把 _ready_state 写成 'complete'
  ```
  → 传 `timeout=1` 等于「加载 1 秒就按下停止键」；异步渲染出来的联系方式永远出不来。
  更阴的是 `_ready_state` 被伪造成 `complete`，于是后面那句 `wait.doc_loaded(10)` 直接空转。
  **典型误判**：「我明明等了 10 秒」—— 其实一秒都没等。
- ⛔ **判据不能用「加载完成」**：实测 `shopping-bags.net` 到第 10 秒 `readyState` 还是 `loading`
  （长轮询/统计脚本/慢图），但正文早就可读了。判据只能是**内容**（DOM 里出现邮箱就收工）。
- ⛔ 联系方式是**晚渲染**的：shopping-bags 第 2.4s、ecohound 第 8s。`ENRICH_WAIT` 低于 8 秒
  会重新掉出去，`_check_stop.py` 里有硬断言。
- ⛔ **三个读法都会阻塞**：`page.html`（首行 `wait.doc_loaded()`）、`page.url` / `tab.url`
  （`_run_cdp_loaded` → `doc_loaded`）、`tab.get`（就是 `get`）。加载中调它们 = 白等 base(6s) + 掐掉加载。
- ⛔ **`run_js` 不是万能替代**：导航过程中执行上下文会丢，`return document.documentElement.outerHTML`
  实测返回 20 字节错误串。**排查时如果你用它采样，会误以为「页面是空的」—— 我自己就先踩了这个坑。**
  正解：`DOM.getDocument(depth=0)` 拿 document nodeId → `DOM.getOuterHTML(nodeId=...)`。
- ⛔ 联系页不要只靠 `CONTACT_PATHS` 猜：那张表只有 `/contact`、`/contact-us`、`/pages/contact-us`、
  `/contactus`，漏掉 `/contact-us.html`、`/en/contact`、`/pages/contact`。先跟页面自己的导航链接
  （`_contact_candidates`），再退回固定表。**必须限同域名**，否则会跟着页脚外链抓到服务商的邮箱。
- ⛔ `maps_open` / `maps_detail` 里**不要** `wait.doc_loaded()`：地图页 readyState 常年 loading，
  那 15 秒除了白等，末尾还会 stopLoading 把结果列表掐掉。就绪判据交给 `ele(MAPS_FEED_CSS)`。
- 校验这条链路的最快办法：`python .workbuddy/_probe_enrich.py`（真浏览器抓这两个站，
  应输出 ecohound 1 个邮箱、shopping-bags 2 邮箱 + 2 电话）。
