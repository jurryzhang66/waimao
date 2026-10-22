# MEMORY 详解（不被自动注入，MEMORY.md 里标「→ 详解 §x」的都在这里）

> 本文件是 MEMORY.md 的扩写层：MEMORY.md 只放「一句话硬约束」，为什么、踩过什么坑、具体字段/行号/报文都记在这里。
> 顺序与 MEMORY.md 章节一一对应。TRAPS.md 里按「静默陷阱」另有整理。

---

## §A 工程纪律详解
- **锁的四段式**（样板 `api_live_delete`）：锁内定位要删的行/ID → **锁外**调 `db_delete_*` 落库 → 锁内改内存与计数 → **锁外** `log()`。原因：`STATE_LOCK` 非可重入，而 `log()` 内部自己要抢 `STATE_LOCK` → 锁内调 `log()` 必死锁（表现为页面永久转圈、`/api/status` 不响应）。DB 与文件 IO 放锁外是因为它们慢（backup 可达数十秒），持锁会让轮询卡死。导出路径用独立 `EXCEL_LOCK`；`/api/db/delete` 刻意不持锁（它只碰库、不碰 `STATE`）。R9/R12 用 AST 静态钉住这些位置。
- **重启/重载的边界**：`ui/page.html`、`ui/manual.html`、`ui/query.html`、`ui/live-table.js` 是在 import 期读进内存并做占位符替换的（`*_HTML` 常量）→ 必须重启工具进程。扩展三件套（`content.js`/`popup.js`/`service-worker`）→ 在 `chrome://extensions` 点「重新加载」。只重载扩展容易造成 popup 新代码 + 旧 SW 存活：旧 SW 不认识新消息类型，回「未知消息」→ 用户界面表现为「0 条」。另一条常见困惑：旧进程还在跑，浏览器访问到旧实例、打新加的路由是 404。
- **回归 24 项**：`_run_all_reg.py` 逐个子进程跑 `.workbuddy/_check_*.py` / `_smoke_*.py`，全 `EXIT=0` 才算过。单项调试：`python.exe .workbuddy/_run_all_reg.py <名字子串>`。smoke 里替换数据库路径必须同时 `m.db.db_path = m.db_path`（模块内函数已绑定旧路径）和 `_under_tmp()` 守卫；打桩库时**必须同时打桩 `paths.ENRICH_FILE`**，否则补全缓存会写真实文件。⛔ 禁止对同一文件并行 Edit（后写的覆盖先写的）。
- 只两项扫真实库：`_check_db_keys.py`（纯只读，校验 `website_key` 一致性）、`补历史欠账.py --dry`。别把当前客户库条数写成回归断言基线 —— 用户在持续采集，数字天天变。
- 静态断言用 `ast` 而非正则：`STATE['rows']` 解析成 `ast.Subscript(value=ast.Name('STATE'), slice=ast.Constant('rows'))`，不是 `ast.Name`。断言 `ast.Name('rows')` 会永远假。
- `PREFERRED_PORTS`（入口里的常量）必须逐字等于 `extension/ports.js::DP_PREFERRED_PORTS`，由 `_check_ext.py` 守。`_smoke_ext_live.py` 会真写库，靠环境变量 `DP_SHADOW_PORTS` 把扩展重定向到影子端口；没遮蔽成功时日志会打「检测到……另一个实例」。
- M22 起 `_smoke_search`/`_smoke_maps` 的断言分两段：导出前 `calls['saved']` 必为空、库里没有；`export_now()` 之后才有 saved、库里才有。写错顺序会得到「看起来通过了其实什么都没测」。
- `_check_page.py` 的 R4（列 0 声明 verbatim 清单）/R12 是逐字比对，`_smoke_ext_popup.js` 的 DOM 桩有局限（不实现 layout/style）。遇到这类红灯，**优先改断言/改桩，别去改产品代码迁就测试**。

## §B 「本轮明细」共享组件详解（M18）
`makeLiveTable(cfg)` 由 `ui/live-table.js` 提供，`core/ui.py` 用 `LIVE_TABLE_JS_PLACEHOLDER` 同时注入主页与 `/manual`。表头 9 列逐字一致、✕ 共用居中确认框，所以两页观感完全统一。差异全部走 cfg：`keyField`（主页 `n`、manual `rid`）、接口路径、`showExisted`、`badgeText(st, n)`、`canDelete`、`hint`、`afterRemove`、`removeMsg`。
- 整份组件包在 IIFE 里，全局只暴露 `makeLiveTable` 一个名字。原因：两个 `<script>` 顶层名字重复就是 SyntaxError，整个 `<script>` 不执行 → 控件区全空白，而 `node --check` 逐段检查抓不到（单段语法合法）。组件内部的 `esc`/`domainOf`/`ratingCls` 都在闭包里，不要当成页面顶层函数去调。
- 组件内禁用一批关键词（`confirm(`、`delModal`、`row-del`、`live-del`、`modal-t`、`btn-danger`、`btn-plain`），注释里也不能出现（`_check_page.py` 是纯文本扫）。类名统一 `livedel-`。对外契约（请求路径、请求体键名、返回体字段）不许改，扩展与 `/manual` 都依赖。
- 主页 `showExisted:false`：本轮只显示新增。若要显示「已在客户库」的灰字行，必须另开 key 空间，不能塞进 `STATE['rows']`（那是导出与计数的唯一来源）。`extension/popup.js` 是第三份独立实现（未迁移，尚未动）。

## §C 入库时机详解（M22/M20）
采集阶段**不写库、不落盘**，这是用户拍板的流程：
- 自动链路：`run_search`/`run_maps` 只把结果攒在 `STATE['rows']`，`finally` 里置 `pending_export=True`。用户在页面上核对、✕ 掉不要的，点「📥 导出 Excel」→ `/api/export_excel` → ① 逐条 upsert 入库 ② 全部成功才写 Excel 文件。
- 手动链路：点「🏁 结束并生成 Excel」→ `_flush_manual_session()`，走同一骨架。
- 代价（已拍板接受）：没点导出/结束就关工具 = 这一轮全丢。
- 硬约束的理由：结果 Excel 里的每一行，客户库里必须都有 —— 否则飞书/建库按行回查会错位。所以先入库、后落表；入库有失败就**不产出 Excel**（宁可不给，也不给一张对不上的表）。upsert 幂等，重复导出同一轮不会产生重复客户。
- `pending_export` 必须写在 `finally`：「停止」按钮的实现在 `try` 里 `return`，写在 `try` 末尾会漏掉停止路径 → 状态卡在 `running=True`，页面上永远转圈。
- `/api/export_feishu` 硬挡 `pending_export`：否则用户还没核对完，就把上一轮的表推进飞书了。
- 本轮去重靠内存：`_live_has_url()` 查 `STATE['rows']`，`_session_has_url()` 查 `session_rows`，都按 `normalize_domain` 比。这阶段还没入库，`db_has_customer()` 必然看不见本轮数据 → 两条链路各需要一个自己的判断函数，别互相替代。
- 行号必须取 `STATE['n_seq']` 自增，而不是 `len(rows)`：用户删掉中间一条后 `len` 会回退 → 撞号 → ✕ 删错行。旧方案 `rows_deleted` 墓碑表已在 M22 下线，别抄回来。
- 删除三条路的删除口径不同，判据统一为「**该行此刻是否真的在客户库里**」：
  - 主页 `/api/live/delete`（按 `n`）：只删内存，绝不碰库（`deleted` 恒 0、`backup` 恒 `''`，R12 有负向 AST 断言）。允许窗口 `(running and phase=='search') or pending_export`。⚠️ JSON 里 `n: true` 会被 Python 当 `1`，必须先用 `isinstance(raw, bool)` 挡掉。
  - `/manual`（按 `rid`）：默认只删内存；只有 `kind='added'` **且** `db_has_customer(url)` 为真才删库；灰字行 `kind='existed'` 永不碰库（所以 `kind` 字段不能丢）。
  - `/db`（按 `id`）→ `db_delete_customers_by_ids()` 返回 `(删除数, 没找到的 id 列表)`；不动 `MANUAL_STATE`。
  - 三条都必须挡空输入：空列表要**返回 0**，绝不能退化成 `DELETE FROM customers`；都不做 email 兜底匹配（邮箱可空、可重复）。
- `backup_db_before_delete()` 必须用 sqlite3 在线 `backup()` API，禁用 `shutil.copy2`：库是 WAL 模式，复制主文件会漏 `-wal`，恢复出来是坏库。300s 节流（连续删不重复备份），备份失败不阻断删除。

## §D 分隔符详解（M21）
邮箱多值用 `', '`、电话多值用 `' / '` —— 刻意不同，因为邮箱里不可能出现斜杠、电话里不可能出现逗号，反向拆解才安全。写侧常量 `EMAIL_SEP`；展示侧要同步的有 `content.js`、`popup.js`（两处）、`live-table.js`。
- ⛔ 读侧必须一起改：飞书流程是把结果 Excel 读回来再拆，涉及 `split_emails()`、`同步数据库到飞书.py`、`gen_import.py`，统一用 `re.split(r'\s*[,/]\s*')`。只改写侧不改读侧 → `EMAIL_OK` 正则失配 → **邮箱整列静默丢光**（不报错，就是空的）。

## §E 计数口径详解（M19）
永远报两组：「有效 / 采集总数」。有效 = 新增 = Excel 行数；总数 = 明细行数（含已在库的灰字行）。⛔ 只报一个「已采 N 条」等于把重复当成功数，用户会误判产能。
- 陷阱：`_flush_manual_session` 会清 `session_rows` 但把 `added`/`existed` 留着 → 徽章必须按 `session_active` 门禁取值，否则出现「有效 5 / 共 0」这种自相矛盾的显示。
- 组件通过 `cfg.badgeText(st, n)` 渲染，`reset()` 会传 `(null, 0)` → 回调必须能在 `st` 为 null 时求值，不能在回调里直接读 `st.added`。

## §F 卡片顺序 / 强必填详解（M17）
- 步骤编号硬编码在 `<h3>` 里（「1. 选择国家」这种）。插入或挪动卡片必须整轮重排编号，并同步三处提示语：`start()` 里的两条 alert、`#comboSummary` 文案、`#rawCard` 文案。漏改不会报错，只会把用户指错步骤。
- 「采集数量」强必填 = 两道兜底**必须一起删**：前端只许 `el.valueAsNumber`（⛔ 不许 `|| '10'`），后端只许 `data.get('target_count')`（⛔ 不许第二缺省值）。只删其中一边就是假必填（前端能过、后端补默认值），R13 + G 段静态守。
- 仍然预填 `value="10"`（只是预填，不是兜底）；后端校验刻意放在产品词校验**之后**（先报更根本的错）；三条链路（搜索/地图/手动）共用同一张卡，别为某条隐藏它；文案逐字保留（含「按新增个数计」）。

## §G 自定义搜索词 / 国家限定详解（M23·M24 / M15）
- 自定义（第 8 卡）：查询串**一个字符都不加**（不拼 `cond_template`）、不做中国过滤（`china_filters=set()`）、与标准模式互斥。四个静默坑：① 校验要**三处一起放宽**（前端两处 + 后端 `api_start`），漏一处就提交不了；② `cond_list` 必须给 `[('自定义', '{p}')]`，给空列表会静默搜出 0 条；③ 预览同步切分支，否则预览与实搜不一致；④ `is_blocked()` 仍然生效（黑名单域名照挡）。
- M24 两步过滤：第一步**抓取前** `domain_rule_hit()`（紧跟 `is_blocked()` 之后），命中直接 `continue`；判据是**域名段相等**（`amazon.de` 命中、`amazonas.com` 不命中），⛔ 不能用子串。第二步补全后只判联系方式 4 项，命中**只标记不删行**（`marks` → 页面 `.live-mark` + 摘要 `[标记]` 前缀）。**只给自定义模式**：标准/地图的 `domain_keys` 恒 None、`marks` 恒空。
- 国家限定取值 `none`/`cr`/`site`/`both`，默认 `none`。`cr` 只挂到 URL 参数、`site:` 只进搜索词、`both` 两者都做；`COUNTRY_LIMITS` 与黑名单独立维护；`custom_mode` 强制降为 `none`。坑：兜底轮会丢 `cr`；`site:` 与领英专用条件互斥（拼一起搜不到）；限定更严 ≠ 更准（过度收窄会掉结果）。

## §H 过滤项分卡详解（M23）
- 只是**界面分组**，提交的仍然是 `china_filters` 的 key 数组，后端一字未改。分组真源是 `config.CONTACT_FILTER_KEYS`（`phone_86`/`wechat`/`qq`/`email_cn`），经 `core/ui.py` 作为 `CHINA_FILTERS_PLACEHOLDER` 的 JSON **第 5 个字段**注入，前端按 `e[4]` 分流。⛔ 前端不许另写一份 key 列表（两份必漂移）。
- 成员：域名组 = `EXCLUDE_OPTIONS` 的 6 项（amazon/ebay/etsy/wikipedia/youtube/facebook）+ `CHINA_FILTER_OPTIONS` 其余 14 项（含 temu）；联系组 4 项，它们的 query 必须为空（纯标记型）。
- ⛔ 地图只许藏 `#excludesWrap`，`#chinaFilters`/`#contactFilters` 仍生效（用 `getComputedStyle` 断言）。`toggleDomainFilters()` 管前两组，`toggleContactFilters()` 只管联系组，别混。
- ⛔ `value` 必须过 `esc()`：不转义时双引号会把属性截断成 `"-"`，表现为预览少项但实搜照旧拼（最难查的一类不一致）。
- 两张清单都是注入数据：加一项只动 config → R5 只有 `_BUILT_SHA` 变，`_TMPL_SHA` 不动。计数断言在 H 段（14 / 4 / `.syn` 18 / `.syn-off` 8 / `#excludes` 6）。Temu 走 `CHINA_FILTER_OPTIONS`；三者都要在 `DOMAIN_FAMILY` 挂变体（`youtu`/`youtube-nocookie`/`fb`/`temu`）—— `BLOCK_DOMAINS` 只挡 `.com` 主域，会漏 `youtu.be`/`fb.com`。

## §I 主页「上次参数」记忆详解（M25）
- 1/2/4/5 卡的控件值存 `DB/ui_prefs.json`，走 `/api/ui_prefs`。**不用 localStorage**：端口避让会换 origin，localStorage 按 origin 隔离 → 静默全丢。
- 路径由 `db.db_path()` 推导 + `DP_UI_PREFS` 环境变量覆盖。回归必须给每个测试注入独立临时文件：页面控件有 400ms 防抖自动 POST，不注入就会把测试值写进用户真实记忆。
- 恢复必须在 `loadKeywords()` **之后**（要先有选项才能设值）；恢复顺序：国家 → 行业 → 品类 → 产品 → **`lang` 最后**（`lang` 变化会触发品类列表重建，放前面会被覆盖）。白名单 `UI_PREF_KEYS` 15 项（含 `contactFilters`），⛔ `products` 不记。漏字段不报错只是不生效 → 加字段必须改四处（收集 / 恢复 / 白名单 / R15）。

## §J 监听 0.0.0.0 详解（M26）
- `HOST='0.0.0.0'`，⛔ 别改回 `127.0.0.1`（回环只收本机，手机就开不了页面）。启动日志里本机那行格式被 `_check_startup.py` 正则抓，别动；局域网地址另起一行印 `lan_ip()`（UDP connect 选网卡，比 `gethostbyname_ex` 可靠；本机当前 `192.168.6.239`）。
- ⛔ `pick_port()` 每个候选端口要**同时探 `127.0.0.1` 和 `host`**：Windows 上回环已被占用时 `bind('0.0.0.0')` 仍会成功（`SO_REUSEADDR`）→ 两个实例抢同一端口，局域网访问会落到**先启动的那个进程**（改代码后看起来「没生效」）。
- 已拍板的代价：同局域网任何设备能打开页面、能调 `/api/db/delete`。扩展仍只走 `127.0.0.1`（扩展的 host_permissions 不含局域网 IP）。

## §K 主页心跳调度详解（M27·M28）
- 架构：`STATE` 是进程内单例，`/api/status` 直接读它 → 同一任务在同一份数据上跑；但「谁来看」要前端主动订阅。全页**只有一个定时器**：`pollTick` 结尾调 `schedulePollTick()` 排下一次（自调度链），顺带驱动「更新于 N 秒前」。
- 间隔：运行中桌面 1s / 手机 2s / 后台 10s / 失败退避 2→15s。
- ⛔ 空闲彻底停链（用户 2026-10-20 拍板「不跑任务的时候，不要刷新」）：`pollTick` 的 `finally` 按 `shouldKeepTicking()`（`pollFails > 0` 或 `pollRunning`）分支，不满足就 `stopPolling()`，且**必须复位 `pollStarted=false`**（不复位 → 下次点开始 `startPolling()` 第一行判断「已在跑」直接 return → 页面永远不刷新）。重新拉起只有三条路：用户点开始/导出、切回前台或网络恢复、刷新页面。空闲时「更新于」小字要清空，否则链停了会冻在「更新于 刚刚」骗人。
- ⛔ `pollTick` 必须 `async` + `await pollOnce()`：不 await 时 finally 里读到的 `pollRunning` 是上一帧的值 → 从空闲被 `kickPoll` 拉起的第一拍会误判「没在跑」→ 立刻停链 → 明明拉到 running 也不再更新（K2b 真机红）。
- ⛔ 后台只降频、**不许停摆**：老 Safari 不派 `visibilitychange`，靠事件驱动会导致永久停更。`visibilitychange`/`pageshow(persisted)`/`focus`/`online` 各绑**恰好一次**，切回即 `kickPoll()`。
- ⛔ 设备判定只许 `pointer: coarse` / `maxTouchPoints` / UA，**不许 `innerWidth`**：无头浏览器与窄窗口会被判成手机 → 2s 间隔 → `_check_live_ui` 的 2.2s 等待假红。
- ⛔ 两个 `finally` 是地基：`pollBusy=false`（不复位 = 永远不再发请求）；续排/停链分支（判错 = 静默不更新或白耗流量）；成功必须 `pollFails=0`。
- ⛔ `since` 自愈：`api_start`/`api_export_feishu` 会 `logs=[]`，别的设备若 `since` 停在大数字 → 切片恒空 → **日志永久空白且不报错**。靠 `STATE['round']`（这两处 +1、`/api/status` 回传）；`lastRound === null` 首帧**只采纳不清屏**（写成 `!==` 会每帧清屏，同样空白）；换轮那帧 `logs` 里是旧 `since` 的残片 → `pollRefetch` 立刻重拉。
- ⛔ `/api/export_excel` **不许** `round+1`（导出不换轮）；`exportExcel()` **不许** `since=0`（会重复追加整轮日志）。
- 「更新于」`#updatedAt` 必须是 `#status` 的**兄弟节点**（`#status` 那个 div 每次 `innerHTML` 重写，子是留不住的）。
- 守卫：`_check_page.py` R16/R17（跨 script 重名、页内重复声明 —— **按列 0 判**，闭包内带缩进的声明不算）；`_check_live_ui.py` K/K2/K3/K4。已拍板：手机保留完全操作权限；`/manual` 不套这套轮询。

## §L 谷歌反爬 / 验证码详解（M29，2026-10-21）
症状：太容易出验证码。**根因不是提交频率** —— `search_url()` 拼好 URL 直接 `page.get()`，从不在搜索框打字（只有连续 3 次失败才降级到输入框回车）；默认参数一轮只发 4~6 次 SERP 请求。真因是四件事叠起来：① 每次任务全新空白 profile（无 cookie，每次都像新访客）；② 自动化特征没藏（实测 `navigator.webdriver` 本就是 false，开关只是保险）；③ 认不出外语/新版拦截页 → 被判定「没渲染」→ 15 秒内同 URL 连发 3 次；④ 撞码后 `continue` 跳过延时立刻发下一条、无请求计数、无熔断。
- ⛔ **持久 profile**：`create_browser_page(persistent=True)` 只在 `run_search`/`run_maps` 两处调用；目录 `paths.chrome_profile_dir()` = `DB/_chrome_profile`（必须经 `_app_dir()` 拼，写 `dirname(abspath(__file__))` 会落到 `core/DB/`）。`_manual_browser()` 与 `enrich_core()` 保持 `persistent=False`（补全是小请求量，共用 profile 反而增加锁冲突）。`set_user_data_path()` 内部即 `--user-data-dir`，对非空目录不做检查；干净 `quit()` 不留锁文件。
  - ⛔ `.gitignore` 必须有 `DB/_chrome_profile/`（里面是谷歌 cookie NID 等，仓库是 public）。⛔ 别写成 `DB/*` —— 客户库与 `ui_prefs.json` 是要跟踪的。
  - `_profile_busy()` 读 `DevToolsActivePort` 的端口做 socket 探活；被占用（另一个实例在跑）就提示后退回临时 profile，宁可不复用也不能崩。`ChromiumPage()` 抛错只降一级（不做多级重试）。`_clean_profile_locks()` 只碰 5 个确切锁文件名，⛔ **不含 `Default`**（那是真数据目录）。
- ⛔ `--disable-blink-features=AutomationControlled` **全项目只许出现一次**（进程级参数）。不能用 `add_init_js`：它只作用于当前 tab，`enrich()` 里 `new_tab` 出来的页面不继承。
- ⛔ `has_captcha(page, deep=False)` 三级判据：① URL 含 `/sorry/`、`google.com/sorry`、`/recaptcha/`（语言无关，外语国家也认得出）② 选择器 `#captcha-form` / `form[action*="sorry"]` / `iframe[src*="recaptcha"]` / `div.g-recaptcha` ③ `deep=True` 才取整页 html 查 8 语言文案。⛔ **绝不用 `'recaptcha' in html`**（正常页也加载该资源，会 100% 误报）。开头有 `page.states.is_loading` 门禁：加载中不碰 `page.url`（那时读会拿到上一页地址）。
- ⛔ `wait_results` **三态**：`'ok'`（可解析）/ `'empty'`（确实没结果，壳页面可重开）/ `'blocked'`（被拦截，**必须退避、不许重发**）；内部不再调 `wait_captcha`（职责分离）。旧写法 `if wait_results(page` 已被 `_check_serp` 静态禁止。
- ⛔ 节奏 `serp_pace(kind='page'|'query')`：page 6~14s、query 20~50s、每 `SERP_LONG_REST_EVERY`=8 次长休息 60~120s；`_serp_tick()` 计数（重试/翻页/撞码重发全算）；`_skew()` 偏态随机（`u ** SERP_SKEW`）；走 `sleep_check` 以便被停止信号打断。⛔ 别写死 `sleep(...)` 固定延时（`_check_serp` 守）。
- ⛔ 撞码熔断 `wait_captcha`：60s / 180s 两轮退避 + `retry()` 重发原 URL，两轮仍不通 → 锁内置 `STATE['stop']=True`，**锁外** `log()`（锁内 log 会死锁）。`run_search` 各调用点改成 `return`（不是 `continue`），且不占 attempts 名额。
- 去重前移：`db_has_customer()` / `_live_has_url()` 移到 `enrich` **之前**（重复客户不再白跑补全，省请求也省时间）；`enrich()` 开头 `sleep(0.5~1.5)`。
- 诚实口径（必须向用户交代）：持久 profile **大概率有效但不是保证** —— 谷歌风控是多因素的，出口 IP 权重很高，本机 IP 若已被标记，慢速与 cookie 都只能缓解。**代价是会变慢**：10 条从 1~2 分钟变成 **3~6 分钟**，且每 8 次搜索有一次 1~2 分钟明显停顿（日志写「☕ 长休息」，点停止可立刻打断）。
- 守卫：`.workbuddy/_check_serp.py`（回归第 2 项）覆盖上述全部静态与行为断言。

## §M 海关编码采集详解（2026-10-06）
`海关商品编码采集.py`（+ `.bat`）→ 产物落 `output/海关编码/`；**不 import `core.*`**（独立脚本，可单独打包）。`stats.customs.gov.cn` 挂**瑞数防护**：普通 HTTP 一律 412，**只能真浏览器**。名称要从 `.th-line` 的 `title` 属性取（可见文本被截断）。分页就绪判据必须含「`hidPageNum` 等于目标页号」，否则**静默取到上一页**（不报错，数据错位）。

## §N 停止链路：为什么按「停止」要等很久（M30，2026-10-21）

- **先分清两件事**：`/api/stop` 只把 `STATE['stop']` 置真，**毫秒级返回**（不持锁、不做 IO，
  且 `threaded=True` 保证它不会被 worker 挡住）。所以「慢」100% 在**读侧** ——
  worker 正在干的活里没人看这个标志。
- 旧账逐项（都是「点了停止还在转」的原因）：

  | 正在执行 | 旧等待 | 原因 |
  |---|---|---|
  | `sleep_check` / 长休息 | ≤0.5s | 本来就是 0.5s 分片轮询，没问题 |
  | `wait_results` | 12~35s | 循环里不看 stop；每轮 `page.eles(timeout=1)` 还会**隐含** `doc_loaded(base=10)` |
  | `has_captcha(deep=True)` | 1~42s | `page.url`/`ele`/`html` 三个都可能隐含 10s 等待 |
  | `page.get` 一次导航 | **最坏 126s** | 全项目没传 timeout → 出厂 `page_load=30s` × `retry_times=3`（4 次尝试）+ 3×2s |
  | `enrich` 一个客户 | **最坏 ~7.3 分钟** | 首页 + 2 个联系页 = 3 次整页导航，函数里 grep 不到 stop |
  | `page.quit()` | 1~8s | `kill()` + `tasklist` 循环最多 5s；`running=False` 还写在它**之后** |

- **`nav()` 的设计**：把「阻塞等待」换成「分片轮询」。
  `page.get(url, timeout=1, retry=0)` 只等 1 秒就返回（Chrome 在后台继续加载，不会中断），
  之后由自己的 `while` 循环每 `NAV_POLL=0.3s` 读一次 `page.states.is_loading`（纯本地字段，零 CDP 往返）。
  → 停止延迟 ≈ 1.3 秒，**与 NAV_BUDGET 无关**。这正是「预算给足 30 秒」和「立刻能停」能同时成立的原因。
  ⛔ 预算耗尽返回 **True**（带着已加载内容继续），只有「用户停止」才返回 False ——
     把超时也当成停止，慢站会让整轮任务被误杀。
  ⛔ `retry=0` 是刻意的：重试是调用方的职责（`open_search` 的 attempts / `maps_open` 的 attempts），
     在 nav 里重试会让一次 nav 偷偷变成 4 次请求 —— 既拖慢停止又更容易撞验证码。
- ⛔ **停止 = 丢弃半截数据**（用户 2026-10-21 拍板）：`enrich` 被打断时返回带 `stopped` 标记的 info，
  `run_search`/`run_maps` 看到就直接 `return`，那一行既不进 `STATE['rows']` 也不入库。
  理由：半截数据（只有邮箱没电话、只抓了一个联系页）在客户库里会变成一条「看着正常其实残缺」的记录，
  事后极难发现。⚠️ 代价：停止那一刻正在补全的那条会少掉，用户已接受。
- ⛔ **三个字段别合并**：`stop`（worker 的开关）/ `stopping`（界面中间态）/ `stopped`（结束文案）。
  `running` 的语义**刻意不动**（仍在 `quit()` 之后才 False）—— 因为它还兼着「开始按钮能不能点」，
  提前放开会让新旧两个浏览器实例抢同一个 `--user-data-dir`。
  `stopped` 在 `/api/export_excel` 成功时一起清掉，否则导出后页面还挂着「已按停止结束」。
- ⛔ **前端三件事要一起做**（原 `stop()` 只有一行 fetch）：① 停止键立刻 `disabled`（原来可以连点，
  每点一次真发一个 POST）② 状态行立刻写「⏹ 正在停止…」③ `kickPoll()` 补一拍。
  另外 `poll()` 每拍都会 `setButtons(true)` 把停止键重新点亮 → `setButtons` 必须判 `pollStopping`；
  `/manual` 是同一个坑，用顶层 `stopPending` 挡（`loadManualState` 在 `st.running` 变 false 时复位）。
- ⛔ 结束文案要区分：现在 `d.stopped` 时写「⏹ 已按你的要求停止」，不再和自然跑完共用「采集完成」。
- ⛔ **浏览器层超时兜底**（`create_browser_page()` 里，任何漏网导航的最后一道闸）：
  `set.timeouts(base=6, page_load=30)` + `set.retry_times(1)` + `set.retry_interval(0.5)`。
  没有它，漏网一次 `page.get` 就是出厂 `30s × 4 次尝试 + 3×2s = 126 秒`；
  有它最坏 31 秒。`base` 从 10 降到 6 还顺带削掉了「半秒的小查询被隐式放大成 10 秒」
  （`page.url` / `page.html` / `doc_loaded` 都吃这个 base）。

## §O 联系方式抓不到：`page.get` 会掐死页面（M31，2026-10-21）

- **症状**：用户报「改了之后抓取联系方式成功率掉下来」，给的例子是
  `https://ecohound.co.uk/` 与 `https://www.shopping-bags.net/`，浏览器里肉眼能看到 email。
- **实测时间线**（真浏览器，每 0.5s 读一次 DOM）：

  | 站点 | 1 秒时 | 邮箱出现的时刻 |
  |---|---|---|
  | ecohound.co.uk | 186KB，0 个邮箱 | 第 **8.0** 秒（358KB）→ `sales@ecohound.co.uk` |
  | shopping-bags.net | 1.8KB 壳 | 第 **2.4** 秒（141KB）→ 2 个邮箱 + 2 个电话 |

- ⛔ **病根在 DrissionPage 的 `_d_connect`/`_wait_loaded`**（4.1.1.4）：
  ```python
  ok = self._wait_loaded(...)
  if not ok: err = TimeoutError(...)
  if err:
      ...
      self.stop_loading()        # Page.stopLoading()
  ```
  而 `stop_loading()` 的 `finally` 里还有 `self._ready_state = 'complete'`。
  所以 M30 的 `page.get(timeout=1, retry=0)` 造成两个后果：
  ① 第 1 秒就 `Page.stopLoading()` —— 异步渲染的内容（联系方式）再也出不来；
  ② `_ready_state` 被伪造成 `complete` —— enrich 里的 `wait.doc_loaded(timeout=10)` 变成空操作，
     于是「读完一次就走」，只拿到壳。
- ⛔ 同类陷阱还有三个入口（都走 `doc_loaded`）：`page.html`、`page.url`（`_run_cdp_loaded`）、
  `tab.url`。读 DOM / 读地址必须用非阻塞版本。
- ✅ `nav()` 的正确姿势：CDP `Page.navigate(url=..., _timeout=NAV_FIRE)` 只点火。
  这条命令超时**不影响**浏览器继续加载（实测 ecohound 上就超时了，页面照样加载完），
  且全程不 stopLoading。之后轮询本地字段 `states.ready_state` / `states.is_loading`（零 CDP 往返）。
- ✅ 判据用「内容」而不是「加载完成」：`_grab_html()` 每 0.4s 取一次 DOM，`clean_emails()` 一命中就走。
  死等 load 事件没用 —— 这些站的 `readyState` 会一直停在 `loading`（长轮询/统计/慢图），
  实测 shopping-bags 到第 10 秒仍是 loading。
- ✅ `raw_html()` = `DOM.getDocument(depth=0)` 拿 document nodeId → `DOM.getOuterHTML(nodeId=...)`。
  ⛔ 别用 `run_js('return document.documentElement.outerHTML')`：导航中执行上下文会丢，
  实测返回 20 字节的错误串，会让人误判「页面是空的」（我自己就先踩了这个坑）。
- 预算：`ENRICH_WAIT=10`（首页）/ `ENRICH_CONTACT_WAIT=6`（联系页）/ `ENRICH_POLL=0.4` /
  `ENRICH_GRACE=2`（真的加载完却还没邮箱 → 再等 2s 转联系页）。
  ⛔ `ENRICH_WAIT` 不能低于 8 秒，`_check_stop.py` 已写成硬断言。
- 联系页：先跟页面自己的导航链接（`_contact_candidates` 正则 contact|kontakt|contacto|contatt，
  限同域名），再退回 `CONTACT_PATHS[:2]`，最多 3 个。固定表只有
  `/contact`、`/contact-us`、`/pages/contact-us`、`/contactus`，漏掉 `/contact-us.html`、`/en/contact` 这类。
- 实测收益：ecohound 0 → 1 个邮箱（8.9s，纯站点渲染耗时）；shopping-bags 0~2 → 2 邮箱 + 2 电话（4.2s）。
