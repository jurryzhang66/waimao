# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

搜客户 → 补邮箱电话 → 评分 → 存 SQLite → 导出 Excel / 飞书。
> 细节（结构/设计/已知问题/功能坑）→ `AI_PROJECT_CONTEXT.md`（§4.3 锁、§6 设计、§7 问题、§9.4）、`TRAPS.md`。本文件只留「不看会静默出错」的硬约束。

## ⛔ 硬不变量
1. `website_key` ≡ `normalize_domain(website)`（`_check_db_keys.py` 只读守）；跳过判据只查它，错位 → 该网址永久判「新客户」。
2. 结果 Excel **10 列硬契约**（列名列序不可改）：公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家；飞书/建库按**下标**读。摘要可加 `[标记] …` 前缀，⛔ 不许加列。
3. `ui/page.html` **双 sha256**（`_TMPL_SHA` 模板原文 / `_BUILT_SHA` 构建成品）：改模板 → 两个都重算；只改**注入数据**（`live-table.js`、config 的 `*_OPTIONS`）→ 只重算 `_BUILT_SHA`。第一个 `<style>` 注入 `/manual` `/db`（`_STYLE_RE.search()` 只取第一块）→ 专有样式写**第二个**。
4. `output/` 产物一律落子目录（查询导出、海关编码各一档）：`find_latest_result()` 只 glob 一层 + 文件名 8 位日期，落根下会**劫持飞书导出**；产物名不含 8 位连续数字。

## ⚠️ 工程纪律
- **锁**：`STATE_LOCK` 非可重入、`log()` 内也抢 → `log()`/DB/文件 IO 一律在锁**外**。四段式（样板 `api_live_delete`）：锁内定位 → 锁外删库 → 锁内改内存 → 锁外 log。导出用 `EXCEL_LOCK`；`/api/db/delete` 不持锁。R9/R12 用 AST 钉住。
- **改完必须重启/重载**：`ui/*.html`、`ui/live-table.js` → 重启工具（`*_HTML` import 期构建）；`extension/` → 点「重新加载」，否则 popup 新/SW 旧分裂（旧 SW 回「未知消息」→ 用户见「0 条」）。旧实例打新路由是 404。
- **页面三坑**：⛔ 禁原生 `confirm()`/`alert()`（用 `#delModal`/`#liveDelModal`，Esc=取消、Enter=确定）；JS 要取的 DOM 必须在 `<script>` **之前**；行 `innerHTML` 重画 → 行内按钮**事件委托**，增量判据还要 `rows[last][key] !== renderedTail`，reset 两个游标一起清零。
- **回归**：`_run_all_reg.py` **23 项**全 EXIT=0；单项传名字子串。smoke 必须 `m.db.db_path = m.db_path` + `_under_tmp()`，打桩库**同时打桩 `paths.ENRICH_FILE`**；禁止并行 Edit 同一文件。
- 只两项扫真实库：`_check_db_keys.py`（只读）、`补历史欠账.py --dry`。别拿固定数字当基线（用户在持续采）。
- 静态断言看**代码**：用 `ast`；`STATE['x']` 是 `ast.Subscript`+`ast.Constant`，不是 `ast.Name`。
- `PREFERRED_PORTS` 逐字等于 `extension/ports.js::DP_PREFERRED_PORTS`（`_check_ext.py`）。`_smoke_ext_live.py` 会真写库 → 靠 `DP_SHADOW_PORTS` 遮蔽（要看到「检测到……另一个实例」）。
- **M22 起** `_smoke_search/_smoke_maps`：「看到 `calls['saved']`」必须先 `export_now()`；「库里有没有」分导出前（无）/导出后（有）两段断言。
- `_check_page.py` R4/R12 verbatim 清单、`_smoke_ext_popup.js` DOM 桩局限 → `TRAPS.md`。该改断言就别改代码。

## ⛔ 「本轮明细」共享组件（M18）
主页与 `/manual` 同一份 `ui/live-table.js`（`makeLiveTable(cfg)`），经 `LIVE_TABLE_JS_PLACEHOLDER` 注入；表头 9 列逐字一致，✕ 共用居中框。差异只走 cfg（`keyField`/接口/`showExisted`/`badgeText`/`canDelete`/hint/`afterRemove`/`removeMsg`）。
- ⛔ 闭包 + 全局只暴露 `makeLiveTable`：跨 `<script>` 顶层重名 = SyntaxError → 整段不执行 → 控件全空白（`node --check` 逐段查抓不到）。组件内 `var esc/domainOf/ratingCls` 在闭包里，别当顶层。
- ⛔ 组件里别写 `confirm(`/`delModal`/`row-del`/`live-del`/`modal-t`/`btn-danger`/`btn-plain`（注释里也不行）；类名一律 `livedel-`；外部契约（路径/请求体键/返回体字段）不许改。
- 主页 `showExisted:false`；要显示「已在客户库」得**另开 key 空间**，不能混进 `STATE['rows']`。`popup.js` 是第三份（未动）。

## ⛔ 入库时机：采集阶段不写库/不落盘（M22 / M20）
- **自动**：`run_search`/`run_maps` 只往 `STATE['rows']` 攒行，`finally` 置 `pending_export=True` → 用户核对、✕ 掉不要的 → 点「📥 导出 Excel」（`/api/export_excel`）才 ①逐条入库 ②全成功才落 Excel。
- **手动**：点「🏁 结束并生成 Excel」→ `_flush_manual_session()` 走同一骨架。代价（拍板）：没点结束/导出就关工具＝丢一轮。
- ⛔ **结果 Excel 的行客户库里必须都有** → 先库后表、入库失败**不产出** Excel；upsert 幂等。
- ⛔ `pending_export` 必须放 `finally`（「停止」在 try 里是 return），否则卡在 `running=True`。
- ⛔ `/api/export_feishu` 硬挡 `pending_export`（否则把**上一轮**表推进飞书）。
- ⛔ 本轮去重靠内存：`_live_has_url()`（`STATE['rows']`）/ `_session_has_url()`（`session_rows`），按 `normalize_domain`；还没入库，`db_has_customer()` 看不见。两条链路各一个。
- ⛔ 行号取 `STATE['n_seq']` 而**不是** `len(rows)`（删中间一条 → 撞号、✕ 指错行）。墓碑 `rows_deleted` 已下线（M22），别抄回来。
- ⛔ 删除三条路各按各的口径（判据：**该行此刻是否真在客户库**）：
  - 主页 `/api/live/delete`（按 `n`）：**只删内存、绝不碰库**（`deleted` 恒 0、`backup` 恒 `''`；R12 有负向 AST 断言）。窗口 = `(running and phase=='search') or pending_export`。⚠️ `n=True` bool→int 变 1，先 `isinstance(raw,bool)`。
  - `/manual`（按 `rid`）：默认只删内存；仅 `kind='added'` **且** `db_has_customer(url)` 才删库；灰字 `existed` 永不碰库（`kind` 不能丢）。
  - `/db`（按 `id`）→ `db_delete_customers_by_ids()` 返回 `(删除数, 没找到的 id)`；不动 `MANUAL_STATE`。
  - 三条都挡空输入（→ **返回 0**，绝不退化 `DELETE FROM customers`），都不做 email 兜底。
- `backup_db_before_delete()`：**必须 sqlite3 在线 `backup()`，禁 `shutil.copy2`**（WAL 漏 `-wal`）；300s 节流；失败不阻断。

## ⛔ 分隔符：邮箱 `', '` / 电话 `' / '`（M21，刻意不同）
写侧 `EMAIL_SEP`；展示侧 `content.js`/`popup.js`×2/`live-table.js`。
- ⛔ **读侧必须同步**（飞书从结果 Excel 读回再拆）：`split_emails()`、`同步数据库到飞书.py`、`gen_import.py` → 一律 `re.split(r'\s*[,/]\s*')`。只改写侧 → `EMAIL_OK` 失配 → **邮箱整列静默丢光**。

## ⛔ 计数报两组数「有效 / 采集总数」（M19）
有效＝新增（＝Excel 行数）；总数＝明细行数（含已在库灰字）。⛔ 只报「已采 N 条」＝把重复当成功数。
- ⛔ 本轮已结束的陷阱：`_flush_manual_session` 清 `session_rows` 但留着 `added/existed` → 徽章必须按 `session_active` 门禁取（否则「有效 5 / 共 0」）。
- 组件靠 `cfg.badgeText(st,n)`，`reset()` 会传 `(null,0)` → 回调必须能在 null 时求值。

## ⛔ 卡片顺序 & 采集数量强必填（M17）
- 编号**硬编码在 `<h3>`** → 插/挪卡必须整轮重排 + 同步三处提示语（`start()` 两条 alert、`#comboSummary`、`#rawCard`）；漏改只指错步骤、不报错。
- 强必填 = **两道兜底一起删**：前端只许 `el.valueAsNumber`（⛔ 不许 `|| '10'`），后端只许 `data.get('target_count')`（⛔ 不许第二缺省值）。只删一边＝假必填（R13 + G 段守）。
- 仍预填 `value="10"`；后端校验刻意留在产品词校验之后；三条链路共用，别隐藏；文案逐字保留（含「按新增个数计」）。

## ⛔ 自定义搜索词 / 国家限定（M23·M24 / M15）
- 自定义（第 8 卡）：查询**一字符不加**、不做中国过滤（`china_filters=set()`）、与标准模式互斥。四个静默坑：**三处校验一起放宽**（前端两处 + `api_start`）；`cond_list` 必须给 `[('自定义','{p}')]`（空 → 静默 0 条）；预览同步切分支；`is_blocked()` 仍生效。
- ⛔ M24 两步过滤：①**抓取前** `domain_rule_hit()`（紧跟 `is_blocked()`）命中 `continue`；判据是**域名段相等**（`amazon.de` 中、`amazonas.com` 不中），⛔ 不能子串。②补全后只判联系方式 4 项，命中**只标记不删行**（`marks` → `.live-mark` + 摘要前缀）。**只给自定义模式**：标准/地图 `domain_keys` 恒 None、`marks` 恒空。
- 国家限定（`none`/`cr`/`site`/`both`）：默认关；`cr` 只挂 URL、`site:` 只进搜索词；`COUNTRY_LIMITS` 独立；`custom_mode` → `none`。坑：兜底轮丢 `cr`；`site:` 与领英条件互斥；限定更严 ≠ 更准。

## ⛔ 过滤项分卡：域名（第 5 卡）/ 联系方式（第 7 卡）（M23）
- **只是界面分组**：提交的仍是 `china_filters` key 数组。分组真源 = `config.CONTACT_FILTER_KEYS`（`phone_86/wechat/qq/email_cn`），经 `core/ui.py` 作为 `CHINA_FILTERS_PLACEHOLDER` JSON **第 5 字段**注入，前端按 `e[4]` 分流（⛔ 前端不许另写 key 列表）。
- 成员：域名组 = `EXCLUDE_OPTIONS` **6**（amazon/ebay/etsy/wikipedia/youtube/facebook）+ 其余 **14**（含 temu，与 taobao/1688 同类）；联系组 4 项 query 必须为空。原「7.」→ **8.**。
- ⛔ 地图只许藏 `#excludesWrap`，`#chinaFilters`/`#contactFilters` 仍生效（`getComputedStyle` 守）。`toggleDomainFilters()` 管前两组、`toggleContactFilters()` 只管联系组。
- ⛔ `value` 必须 `esc()`（双引号会截断成 `"-"` → 预览少项但实搜照拼）。
- ⛔ 两张清单是注入数据：加一项只动 config → R5 只有 `_BUILT_SHA` 变。计数在 H 段（14 / 4 / `.syn` 18 / `.syn-off` 8 / `#excludes` 6）。Temu 走 `CHINA_FILTER_OPTIONS`；三者都在 `DOMAIN_FAMILY` 挂变体（`youtu`/`youtube-nocookie`/`fb`/`temu`），`BLOCK_DOMAINS` 只挡 `.com` 主域会漏 `youtu.be`/`fb.com`。

## ⛔ 主页「上次参数」记忆（M25）
1/2/4/5 卡 → `DB/ui_prefs.json`（`/api/ui_prefs`），**不用 localStorage**（端口避让＝换 origin，静默全丢）。
- 路径由 `db.db_path()` 推导 + `DP_UI_PREFS` 覆盖；回归给每个测试注入独立临时文件（页面控件会 400ms 防抖自动 POST，不挡就写进用户真实记忆）。
- 恢复必须在 `loadKeywords()` **之后**；顺序：国家 → 行业 → 品类 → 产品 → **`lang` 最后**。白名单 `UI_PREF_KEYS` 15 项（含 `contactFilters`），⛔ `products` 不记；漏字段不报错 → 加字段改四处（收集/恢复/白名单/R15）。

## ⛔ 监听 `0.0.0.0`（M26）
`HOST='0.0.0.0'`，⛔ 别改回 `127.0.0.1`（回环只收本机）。启动日志本机那行格式被 `_check_startup.py` 正则抓，另起一行印 `lan_ip()`（本机 `192.168.6.239`；UDP connect 选网卡，比 `gethostbyname_ex` 可靠）。
- ⛔ `pick_port()` 每个候选要**同时探 `127.0.0.1` 和 `host`**：Windows 上回环已占时 `bind('0.0.0.0')` 仍成功（`SO_REUSEADDR`）→ 两实例抢同端口、访问落到**先启动的进程**。
- 代价（拍板）：同局域网任何设备能开页面、能调 `/api/db/delete`。扩展仍走 `127.0.0.1`。

## ⛔ 主页心跳调度（M27·M28）
`STATE` 是进程内单例、`/api/status` 直接读它 → 同一任务、同一份数据；但**轮询要前端订阅**。
- 一条 `setTimeout` 自调度链（`pollTick` → `schedulePollTick`）是**全页唯一定时器**，顺带驱动「更新于 N 秒前」。间隔：运行中电脑 **1s** / 手机 **2s**、后台 10s、失败退避 2→15s。
- ⛔ **空闲彻底停链、一个请求都不发**（用户 2026-10-20 拍板「不跑任务的时候，不要刷新」，别再加空闲心跳）：`pollTick` 的 `finally` 按 `shouldKeepTicking()`（`pollFails>0` 或 `pollRunning`）分支，否则 `stopPolling()` 且**必须复位 `pollStarted=false`**（不复位＝下次点开始 `startPolling` 直接 return，永不刷新）。重新拉起只有三条路：点开始/导出、切回前台/网络恢复、刷新页面。空闲态「更新于」小字要清空（链停了会冻成「更新于 刚刚」骗人）。
- ⛔ `pollTick` 必须 **async + `await pollOnce()`**：不 await 就在 finally 里判「要不要继续」＝拿上一帧的 `pollRunning`，从空闲被 `kickPoll` 拉起的第一拍误判成「没在跑」→ 立刻停链 → 明明拉到 running 也不再更新（K2b 真机红）。
- ⛔ 后台只降频、**不许停摆**（老 Safari 不派 `visibilitychange` → 永久停更）。`visibilitychange`/`pageshow(persisted)`/`focus`/`online` 各绑**恰好一次**，切回即 `kickPoll()`。
- ⛔ 设备判定只许 `pointer: coarse`/`maxTouchPoints`/UA，**不许 `innerWidth`**（无头/窄窗判成手机 → 2s → `_check_live_ui` 的 2.2s 等待假红）。
- ⛔ 两个 `finally` 是地基：`pollBusy=false`（不复位＝永不发请求）、续排/停链分支（判错＝静默不更新或白耗流量）；成功必须 `pollFails=0`。
- ⛔ **`since` 自愈**：`api_start`/`api_export_feishu` 会 `logs=[]`，别的设备 `since` 停在大数字 → 切片恒空 → **日志永久空白不报错**。靠 `STATE['round']`（这两处 +1、`/api/status` 回传）；`lastRound===null` 首帧**只采纳不清屏**（写成 `!==` → 每帧清屏 → 同样空白）；换轮那帧 `logs` 是旧 `since` 残片 → `pollRefetch` 立刻重拉。
- ⛔ `/api/export_excel` **不许** `round+1`；`exportExcel()` **不许** `since=0`（会重复追加整轮日志）。
- 「更新于」`#updatedAt` 必须是 `#status` 的**兄弟**（那个 div 每次 `innerHTML` 重写）。
- 守卫：`_check_page.py` R16/R17（含跨 script 重名、页内重复声明 —— **按列 0 判**，闭包内的带缩进声明别算）；`_check_live_ui.py` K/K2/K3/K4。
- 拍板：手机保留**完全操作权限**；`/manual` **不套**这套。

## ⛔ 产物目录默认不读
`output/` 与 `DB/backups/` 是运行产物 → 条数可以瞄，**内容一律不读、不比对、不追查「少了几份」**，除非用户点名。

## ⛔ 海关编码采集（2026-10-06）
`海关商品编码采集.py`（+.bat）→ `output/海关编码/`；**不 import `core.*`**。`stats.customs.gov.cn` 挂**瑞数防护** → 普通 HTTP 一律 412，**只能真浏览器**；名称取 `.th-line` 的 `title`；就绪判据须含「`hidPageNum` == 目标页号」否则**静默取上一页**。

## 关键约定速查
- 库 `DB/客户库.sqlite3`（`customers`，WAL）；结果 Excel 落 `output/` 根。`find_latest_result()` 从**文件名**解析时间（字典序≠时间序）；`ts_*_path()` 自带 `_2/_3` 去重。
- 哨兵 `QUERY_EMPTY='__empty__'` 前后端一字不差；筛选选项由 `db_facet_counts()` 生成，**页面零硬编码行业名**。
- 拆包遗留：入口只许**绝对导入** + `sys.path` 自举，搬走的名字同名 re-export；`_app_dir()` 不许写 `dirname(abspath(__file__))`；`ENRICH_FILE` 是唯一被重新赋值的模块级变量（内部一律 `paths.ENRICH_FILE`）。
- `.workbuddy/` 与程序零耦合，**别删**（`memory/*`、回归脚本、`_todo.json`、`_*_before.json`）。`.gitignore` 白名单式（`_*` 全排除再逐条 `!`）→ 新脚本要确认被放行。
- 词库：UTF-8 无 BOM / **纯 CRLF** / 2 空格 / 末尾无换行（`json.dumps` 的 LF 要 `replace` 后二进制写）；三级下拉 = `sorted(keys)`。脚本 `补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py` / `标注空行业.py`（后两个要 `--apply`）。

## git / 远端
- 附注标签 V1.0–V1.4；V1.4 起不写 commit hash。用户自己会打**轻量** `v1.5`/`v1.5.1` 备份 → 别只认大写 `V1.x`。**M16–M28 全未提交**。
- `origin=https://github.com/jurryzhang66/waimao.git`（public）；凭据 `helper-selector`。⛔⛔ 公开仓库已含 ① 真实 `DB/客户库.sqlite3` ② `output/` ③ `DB/backups/` ④ 飞书 BASE_TOKEN → 收口只能 `git filter-repo` + 强推 + 轮换 token。

## ⛔ 功能坑 / 回归脆弱点 / 本机环境
飞书「官网」字段与 `HERMES_HOME`、词库 `cond_template`、`open_search`/`_back_to_search`、扩展唯一 fetch 出口与 CORS、地图 `div[role="feed"]`、bash 残缺/端口漂移/`C:` 盘、评分方向反、数据待办 → 见 `AI_PROJECT_CONTEXT.md` §7/§9.4 与 `TRAPS.md`，别凭记忆动手。
