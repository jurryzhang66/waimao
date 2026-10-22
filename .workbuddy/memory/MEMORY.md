# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

搜客户 → 补邮箱电话 → 评分 → 存 SQLite → 导出 Excel/飞书。
> 本文件只列「不看会静默出错」的一句话约束。**为什么 / 复现条件 / 字段行号 / 完整展开** → `MEMORY_DETAIL.md`（§A~§M）；静默陷阱 → `TRAPS.md`；结构与设计 → `AI_PROJECT_CONTEXT.md`。
> ⚠️ 本文件有注入体积上限（超了会被静默截断）→ **新知识写 DETAIL，这里最多加一行**。

## ⛔ 硬不变量
1. `website_key` ≡ `normalize_domain(website)`（`_check_db_keys.py` 只读守）；跳过判据只查它。
2. 结果 Excel **10 列硬契约**（公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家），按**下标**读；摘要可加 `[标记] ` 前缀，⛔ 不许加列。
3. `ui/page.html` **双 sha256**：改模板两个都重算，只改注入数据只重算 `_BUILT_SHA`；第一个 `<style>` 注入 `/manual` `/db` → 专有样式写**第二个**。
4. `output/` 产物必落子目录：`find_latest_result()` 只 glob 一层 + 文件名 8 位日期，落根下会**劫持飞书导出**。

## ⚠️ 工程纪律（§A）
- **锁**：`STATE_LOCK` 不可重入且 `log()` 内要抢 → `log`/DB/文件 IO 一律在锁**外**；四段式（样板 `api_live_delete`）：锁内定位 → 锁外删库 → 锁内改内存 → 锁外 log。导出用 `EXCEL_LOCK`。R9/R12 用 AST 钉住。
- **改完必须重启/重载**：`ui/*`、`*.py` → 重启工具；`extension/` → 点「重新加载」（否则 popup 新/SW 旧 → 见「0 条」）。旧实例打新路由是 404。
- **页面三坑**：⛔ 禁原生 `confirm()`/`alert()`（用 `#delModal`/`#liveDelModal`）；JS 要取的 DOM 在 `<script>` **之前**；行 `innerHTML` 重画 → 行内按钮**事件委托** + `rows[last][key] !== renderedTail`。
- **回归 24 项** `_run_all_reg.py` 全 EXIT=0（单项传名字子串）；smoke 必须 `m.db.db_path = m.db_path` + `_under_tmp()`，打桩库**同时打桩 `paths.ENRICH_FILE`**；⛔ 禁止并行 Edit 同一文件。解释器 `D:/Users/admin/AppData/Local/Programs/Python/Python313/python.exe`。
- 只两项扫真实库：`_check_db_keys.py`（只读）、`补历史欠账.py --dry`；别拿固定条数当基线。静态断言用 `ast`（`STATE['x']` 是 `Subscript`+`Constant`）。
- `PREFERRED_PORTS` 逐字等于 `extension/ports.js::DP_PREFERRED_PORTS`；`_smoke_ext_live.py` 靠 `DP_SHADOW_PORTS` 遮蔽。M22 起看 `calls['saved']` 必须先 `export_now()`。
- `_check_page.py` R4/R12 verbatim 清单、`_smoke_ext_popup.js` DOM 桩局限 → `TRAPS.md`。**该改断言就别改代码**。

## ⛔ 本轮明细共享组件（M18，§B）
`ui/live-table.js` 的 `makeLiveTable(cfg)` 被主页与 `/manual` 共用，表头 9 列逐字一致，差异只走 cfg。
- ⛔ 闭包、全局只暴露 `makeLiveTable`：跨 `<script>` 顶层重名 = SyntaxError → 控件全空白（`node --check` 抓不到）。组件内禁写 `confirm(`/`delModal`/`row-del`/`live-del`/`modal-t`/`btn-danger`/`btn-plain`（注释也不行），类名一律 `livedel-`，外部契约不许改。
- 主页 `showExisted:false`；显示「已在库」得**另开 key 空间**，不能混进 `STATE['rows']`。`popup.js` 是第三份（未动）。

## ⛔ 入库时机：采集阶段不写库/不落盘（M22/M20，§C）
采集只往 `STATE['rows']` 攒行、`finally` 置 `pending_export=True`，点导出才 ①逐条入库 ②全成功才落 Excel（手动链路 `_flush_manual_session()` 同骨架）。代价（已拍板）：没点导出/结束就关工具＝丢一轮。
- ⛔ **Excel 的行客户库里必须都有** → 先库后表、入库失败**不产出** Excel；`pending_export` 必须放 `finally`（「停止」在 try 里 return）；`/api/export_feishu` 硬挡 `pending_export`。
- ⛔ 去重靠内存 `_live_has_url()`/`_session_has_url()`（`db_has_customer()` 此时看不见）；行号取 `STATE['n_seq']` 而非 `len(rows)`。
- ⛔ 删除三路：`/api/live/delete` **只删内存绝不碰库**（`deleted` 恒 0，`n=True` 会变 1 → 先 `isinstance(raw,bool)`）；`/manual` 仅 `kind='added'` 且 `db_has_customer` 才删库、灰字永不碰库；`/db` 按 `id`。三条都挡空输入（→ 返回 0），都不做 email 兜底。
- `backup_db_before_delete()`：**必须 sqlite3 在线 `backup()`，禁 `shutil.copy2`**（WAL 漏 `-wal`）。

## ⛔ 分隔符：邮箱 `', '` / 电话 `' / '`（M21，§D）
写侧 `EMAIL_SEP`；展示侧 `content.js`/`popup.js`×2/`live-table.js`。
- ⛔ **读侧必须同步**（`split_emails()`、`同步数据库到飞书.py`、`gen_import.py` 一律 `re.split(r'\s*[,/]\s*')`）：只改写侧 → `EMAIL_OK` 失配 → **邮箱整列静默丢光**。

## ⛔ 计数报两组数「有效 / 采集总数」（M19，§E）
有效＝新增（＝Excel 行数）；总数＝明细行数（含在库灰字）。⛔ 只报「已采 N 条」＝把重复当成功数。
- ⛔ 徽章按 `session_active` 门禁取（否则「有效 5 / 共 0」）；`badgeText(st,n)` 须能在 `st=null` 求值。

## ⛔ 卡片顺序 & 采集数量强必填（M17，§F）
- 编号**硬编码在 `<h3>`** → 插/挪卡必须整轮重排 + 同步三处提示语（`start()` 两条 alert、`#comboSummary`、`#rawCard`）。
- 强必填 = **两道兜底一起删**：前端只许 `el.valueAsNumber`，后端只许 `data.get('target_count')`；仍预填 `value="10"`，文案逐字保留（含「按新增个数计」）。

## ⛔ 自定义搜索词 / 国家限定（M23·M24/M15，§G）
- 自定义（第 8 卡）：查询**一字符不加**、`china_filters=set()`、与标准模式互斥。四个坑：**三处校验一起放宽**；`cond_list` 必须给 `[('自定义','{p}')]`（空 → 静默 0 条）；预览同步切分支；`is_blocked()` 仍生效。
- ⛔ M24 两步：①抓取前 `domain_rule_hit()` 命中 `continue`，判据是**域名段相等**（`amazon.de` 中、`amazonas.com` 不中，⛔ 不能子串）；②补全后只判联系方式 4 项，命中**只标记不删行**。**只给自定义模式**。
- 国家限定 `none`/`cr`/`site`/`both`：默认关、`custom_mode` → `none`；`cr` 只挂 URL、`site:` 只进搜索词。坑：兜底轮丢 `cr`；`site:` 与领英条件互斥。

## ⛔ 过滤项分卡：域名（5 卡）/ 联系方式（7 卡）（M23，§H）
- **只是界面分组**，提交的仍是 `china_filters` key 数组；分组真源 `config.CONTACT_FILTER_KEYS` 经 `core/ui.py` 作为 JSON **第 5 字段**注入，前端按 `e[4]` 分流（⛔ 前端不许另写 key 列表）。域名组 6+14（含 temu）、联系组 4 项 query 必须空。原「7.」→ **8.**。
- ⛔ 地图只藏 `#excludesWrap`，两个 filter 区仍生效；`value` 必须 `esc()`（否则截断成 `"-"` → 预览少项但实搜照拼）。清单是注入数据 → 加一项只有 `_BUILT_SHA` 变；计数在 H 段（14/4/18/8/6）。`BLOCK_DOMAINS` 只挡 `.com` 会漏 `youtu.be`/`fb.com`。

## ⛔ 主页「上次参数」记忆（M25，§I）
1/2/4/5 卡 → `DB/ui_prefs.json`（`/api/ui_prefs`），**不用 localStorage**（端口避让＝换 origin，静默全丢）；回归每个测试注入独立临时文件。
- 恢复必须在 `loadKeywords()` **之后**，顺序：国家→行业→品类→产品→**`lang` 最后**；白名单 15 项（⛔ `products` 不记），加字段改四处（收集/恢复/白名单/R15）。

## ⛔ 监听 `0.0.0.0`（M26，§J）
`HOST='0.0.0.0'`，⛔ 别改回 `127.0.0.1`；启动日志本机那行格式被 `_check_startup.py` 抓，`lan_ip()` 另起一行。
- ⛔ `pick_port()` 每个候选要**同时探 `127.0.0.1` 和 `host`**（Windows 回环已占时 `bind('0.0.0.0')` 仍成功 → 两实例抢端口、落到先启动的进程）。

## ⛔ 主页心跳调度（M27·M28，§K）
一条 `setTimeout` 自调度链是全页唯一定时器。间隔：运行中电脑 1s / 手机 2s / 后台 10s / 失败退避 2→15s。
- ⛔ **空闲彻底停链、一个请求都不发**（2026-10-20 拍板）：`finally` 按 `shouldKeepTicking()` 分支，否则 `stopPolling()` 且**必须复位 `pollStarted=false`**（不复位＝下次点开始直接 return，永不刷新）。重拉只有三条路：点开始/导出、切回前台或网络恢复、刷新页面。
- ⛔ `pollTick` 必须 **async + `await pollOnce()`**（不 await 就拿上一帧 `pollRunning` → 从空闲拉起第一拍误判「没在跑」→ 立刻停链，K2b 真机红）。
- ⛔ 后台只降频**不停摆**（老 Safari 不派 `visibilitychange`）；四个事件各绑**恰好一次**、切回即 `kickPoll()`。设备判定只许 `pointer: coarse`/`maxTouchPoints`/UA，**不许 `innerWidth`**。
- ⛔ `since` 自愈靠 `STATE['round']`：`lastRound===null` 首帧**只采纳不清屏**，换轮那帧立刻 `pollRefetch`。`/api/export_excel` 不许 `round+1`，`exportExcel()` 不许 `since=0`。`#updatedAt` 必须是 `#status` 的**兄弟**。
- 守卫 `_check_page.py` R16/R17（按列 0 判）、`_check_live_ui.py` K/K2/K3/K4。手机留完全操作权限；`/manual` **不套**。

## ⛔ 反爬 · 停止 · 读 DOM（M29/M30/M31，2026-10-21，**细节必读 §L/§N/§O**）
- ⛔ **反爬不是提交频率**（拼 URL 直接导航，不在搜索框打字；一轮只 4~6 次 SERP）。真因：空白 profile 无 cookie + 认不出外语拦截页 → 15s 内同 URL 连发 3 次。对策：`persistent=True` **只两处**（`run_search`/`run_maps`，目录 `DB/_chrome_profile`，⛔ `.gitignore` 必须排除——仓库 public）；`has_captcha` 三级判据（⛔ 绝不用 `'recaptcha' in html`，正常页也加载该资源；看 `/sorry/` URL → 4 个选择器 → `deep` 才查文案）；`serp_pace` 节奏（page 6~14s / query 20~50s / 每 8 次长休息 60~120s，走 `sleep_check` 可打断）；撞码 60s/180s 两轮 + `retry()`，两轮不通 → 锁内置 `stop` 后**锁外** `log()`。
- ⛔ **导航全项目零 `page.get`/`tab.get`**（ast 守），一律 `nav()` = CDP `Page.navigate(_timeout=NAV_FIRE)` 点火 + 0.3s 轮询本地字段 `ready_state`/`is_loading`。⛔ 它一超时就 `Page.stopLoading()` 掐死页面 —— 这是 M31 血案。
- ⛔ **读 DOM 只许 `raw_html()`**（`DOM.getOuterHTML`）/ `raw_url()`（`Target.getTargetInfo`）。`page.html`/`page.url`/`tab.url` 内部都 `doc_loaded()` → 阻塞到 base(6s) 再掐加载；`run_js` 导航中上下文会丢（只返 20 字节）。
- ⛔ **联系方式晚渲染**（实测 shopping-bags 2.4s、ecohound 8s）：`enrich` 必须 `_grab_html()` 边等边看（抓到邮箱即走），⛔ 只读一次 DOM = 成功率腰斩；`ENRICH_WAIT` ≥ 8s。联系页先跟页面自己的 contact 链接（`_contact_candidates`，限同域名）再退回 `CONTACT_PATHS`。
- ⛔ **停止慢在读侧**，不是 `/api/stop`（毫秒级、不持锁、不做 IO）。三字段别合并：`stop`/`stopping`/`stopped`；`running` 仍等 `quit()` 后才 False；`wait_results` **四态**含 `'stopped'`；半截数据（`info['stopped']`）**调用方必须丢行**。前端 `stop()` 三件事：压灰 + 立刻「正在停止…」+ `kickPoll()`。守卫 `_check_stop.py`／`_check_serp.py`。

## ⛔ 产物目录默认不读
`output/` 与 `DB/backups/` 是运行产物 → 条数可以瞄，**内容一律不读不比对**，除非用户点名。

## ⛔ 海关编码采集（2026-10-06，§M）
`海关商品编码采集.py`（+.bat）→ `output/海关编码/`；**不 import `core.*`**。站点挂**瑞数防护** → 普通 HTTP 一律 412，**只能真浏览器**；就绪判据须含「`hidPageNum` == 目标页号」否则**静默取上一页**。

## 关键约定速查
- 库 `DB/客户库.sqlite3`（WAL）；结果 Excel 落 `output/` 根；`find_latest_result()` 从**文件名**解析时间（字典序≠时间序）。哨兵 `QUERY_EMPTY='__empty__'` 前后端一字不差；筛选选项由 `db_facet_counts()` 生成，**页面零硬编码行业名**。
- 拆包遗留：入口只许**绝对导入** + `sys.path` 自举；`_app_dir()` 不许写 `dirname(abspath(__file__))`；`ENRICH_FILE` 是唯一被重赋值的模块级变量（内部一律 `paths.ENRICH_FILE`）。`.workbuddy/` 零耦合别删；`.gitignore` 白名单式 → 新脚本要确认放行。
- 词库：UTF-8 无 BOM / **纯 CRLF** / 2 空格 / 末尾无换行；三级下拉 `sorted(keys)`。脚本 `补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py` / `标注空行业.py` / `修正国家.py` / `清理噪音.py`（多数默认 dry-run，加 `--apply` 才写库）。
- 库内噪音已清（2026-10-22 `清理噪音.py`）：1209→**1110**，删 99 条（平台/比价/目录/机构/内容站/本地生活/B2C 品牌站）。⛔ 规则只按**域名段相等**判；⛔ `wordpress/wixsite/blogspot` 子域**不许**进规则表（背后是真实小公司）；政府段要带「末段 2 位国码」；边界保留 17 条（单店商户/免费域名真公司/B2B 餐饮供应）。详见 `2026-10-22.md`。
- ⛔ `country` 采集时写的是「**搜索时选的目标国家**」，不是实际所在国。2026-10-22 已用 `修正国家.py` 按**域名后缀**重标全库（145 改 + 5 错别字 + 13 条 `.org` 删除，1222→1209）。⛔ TLD 取 `website_key` 末段（`website` 带路径会判错）；⛔ `.org` 用**末段相等**判定，`LIKE '%.org%'` 会误删 `comceoccte.org.mx`/`ssfn.org.sa`；`.com/.net` 不推断、`.co/.re/.gov/.edu/.eu` 歧义不动（详见 `2026-10-22.md`）。

## git / 远端
- 附注标签 V1.0–V1.4；用户会打**轻量** `v1.5`/`v1.5.1` → 别只认大写 `V1.x`。**M16–M29 全未提交**。
- `origin=https://github.com/jurryzhang66/waimao.git`（public）。⛔⛔ 已含真实客户库、`output/`、`DB/backups/`、飞书 BASE_TOKEN → 收口只能 `git filter-repo` + 强推 + 轮换 token。

## ⛔ 功能坑 / 回归脆弱点 / 本机环境
飞书「官网」字段与 `HERMES_HOME`、词库 `cond_template`、`open_search`/`_back_to_search`、扩展唯一 fetch 出口与 CORS、地图 `div[role="feed"]`、bash 残缺/端口漂移/`C:` 盘、评分方向反、数据待办 → 见 `AI_PROJECT_CONTEXT.md` §7/§9.4 与 `TRAPS.md`，别凭记忆动手。
