# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

搜客户 → 补邮箱电话 → 评分 → 存 SQLite → 导出 Excel / 飞书。

> 📍 结构 / 设计决定 / 已知问题 / 各功能坑 → `AI_PROJECT_CONTEXT.md`（§4.3 锁纪律、§6 设计、§7 问题、§9.2）。本文件只留「不看会静默出错」的硬约束。

## ⛔ 硬不变量
1. **`website_key` ≡ `normalize_domain(website)`**（`_check_db_keys.py` 只读守）。跳过判据只查它；键错位 → 该网址永久判「新客户」。修：upsert 键自愈 + `db_fix_website_keys(apply=)`。
2. **结果 Excel 10 列硬契约**（列名列序不可改）：`公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家`；飞书与建库按**下标**读。
3. **`ui/page.html` 双 sha256 基线**（`_TMPL_SHA`=模板原文、`_BUILT_SHA`=构建成品）。改 `page.html` → **两个一起重算**；改 `ui/live-table.js`（正文被注入构建结果）→ **只重算 `_BUILT_SHA`**、`_TMPL_SHA` 不变。page.html 第一个 `<style>` 经 `PAGE_CSS_PLACEHOLDER` 注入 `/manual` `/db` → 加规则连带三页；专有样式写各自第二个 `<style>`。
4. **`output/` 下的产物一律落子目录**（查询导出 → `output/查询导出/`；海关编码 → `output/海关编码/`）：`find_latest_result()` 只 glob 一层 + 按文件名 8 位日期筛，落根下会**劫持飞书导出**；文件名也刻意不含 8 位连续数字。

## ⛔ M18：「本轮明细」共享组件（2026-10-03）
主页「📥 本轮已入库明细（实时）」与 `/manual`「③ 本轮采集明细」= **同一份** `ui/live-table.js`（`makeLiveTable(cfg)`），`core/ui.py` 经 `LIVE_TABLE_JS_PLACEHOLDER` import 期注入两页；表头 9 列**逐字一致**（含行业/国家），✕ 共用居中模态框。差异只走 cfg：`keyField`（主页 `n`/手动 `rid`）、接口、`showExisted`、`badgeText`（M19：徽章文案，默认 `n + ' 条'`）、`badgeTitle`、`canDelete`、两个 hint、`afterRemove`。
- ⛔ **闭包 + 全局只暴露 `makeLiveTable`**：跨 `<script>` 的顶层 `let/const` 与另一段 `function` **重名 = SyntaxError → 整段不执行 → 页面控件全空白**（`node --check` 只查单段抓不到）。
- ⛔ 组件里**别写** `confirm(`/`delModal`/`row-del`/`live-del`/`modal-t`/`btn-danger`/`btn-plain`（**注释里也不行**，R12 子串判负向）；类名一律 `livedel-`；外部契约不许改（路径 / 请求体的键 / 返回体字段）。
- 守卫：R12 断言「组件文本两页都在」+「两页 `<thead>` 逐字相等」→ **只改一页立刻红**；`_check_live_ui` F 段按真实 DOM 断言 9 列与行业/国家**数据**。
- 未做（拍板推迟）：主页 `showExisted:false`；要显示「已在客户库」行得**另开 key 空间**，不能混进 `STATE['rows']`（否则 `n == len(all_rows)` 对齐与墓碑全乱）。扩展 `popup.js` 是**第三份**（未动）。

## ⚠️ 锁纪律（踩过 2 次死锁）
`STATE_LOCK` 非可重入且 `log()` 内部也抢 → **`log()` / DB / 文件 IO 一律在 `with STATE_LOCK` 外**。四段式（样板 `api_manual_session_delete`/`api_live_delete`）：①锁内定位 ②锁外 `_delete_customer_and_backup()` ③锁内改内存 ④锁外 log。查询/导出/删除链路**完全不碰** `STATE_LOCK`/`STATE`/`ENRICH_FILE`；导出用 `EXCEL_LOCK`；`/api/db/delete` 不能持锁。R9/R12 用 **AST** 钉住。

## ⚠️ 改完必须「重启 / 重新加载」
改 `ui/*.html` 或 `ui/live-table.js` → **重启工具**（三个 `*_HTML` import 期构建一次）；改 `extension/` → 点「重新加载」，否则「popup 新 / SW 旧」分裂（旧 SW 回「未知消息」→ 用户见「0 条」误判失败）。新功能交付要说：旧实例打新路由是 **404**。

## ⚠️ 页面交互（三个坑）
- **禁原生 `confirm()`/`alert()`** → 用页面自己的居中模态框（`/db` = `#delModal`；主页与 `/manual` 共用 `#liveDelModal`，fixed+flex 居中，Esc/点遮罩=取消、Enter=确定）。R9/R12 断言整页无 `confirm(`。
- **JS 要取的 DOM 节点必须在 `<script>` 之前**（`/db` 是立即执行 IIFE）——否则取 `null` → 抛错 → `init()` 中断、筛选面板全空白。
- **行 `innerHTML` 整表重画 → 行内按钮必须事件委托**（`#resBody`/`#liveBody`/`#sessionBody`）。增量重画失效判据：除 `rows.length < renderedRows` 还要 `rows[last][key] !== renderedTail`；重置时**两个游标一起清零**。

## ⚠️ 打桩 / 回归纪律
- 全量 `_run_all_reg.py` **23 项**，全 EXIT=0 才算过；单项 `_run_all_reg.py <名字子串>`。子模块间必须 `模块.函数()`。
- smoke 必须有 `m.db.db_path = m.db_path` + `_under_tmp()` 护栏；打桩临时库**必须同时打桩 `paths.ENRICH_FILE`**。**禁止并行 Edit 同一文件**。
- **只两项刻意扫真实库**：`_check_db_keys.py`（只读）、`补历史欠账.py --dry`；其余打临时目录 → 红了多半是真实数据要人工修。**别拿固定数字当基线**（用户在持续采）→ 复核看 source 分布 + 测试域名残留。
- **脆弱点（假红≠产品 bug）清单见 `TRAPS.md`**：别写死端口原因 / 别固定 sleep / 临时库落 `C:` / **备份名只到秒**… **红了先看错误类型。**
- 静态断言看**代码**不看源码文本：用 `ast`；`STATE['xxx']` 是 `ast.Subscript`+`ast.Constant`，**不是 `ast.Name`**。
- `_check_ext.py` C 组：`PREFERRED_PORTS` 逐字等于 `extension/ports.js` 的 `DP_PREFERRED_PORTS`。`_smoke_ext_live.py` 走真 Chrome + 真 Flask、**会真写库** → 靠 `DP_SHADOW_PORTS` 遮蔽；**跑全量前先关工具**。
- `_check_page.py` R4/R12 的 verbatim 断言清单、`_smoke_ext_popup.js` DOM 桩的局限 → 见 `TRAPS.md`。**该改断言就别改代码。**

## ⛔ 入库时机分裂：自动「当场落库」，手动「点结束才落库」（2026-10-11，M20）
- **自动**（`run_search`/`run_maps`）：采集那刻就 `db_upsert_customer`。**手动**（`collect_from_html` →
  `_manual_row()`，**已不再写库**）：入库推迟到点「🏁 结束并生成 Excel」时的 `_flush_manual_session()`——
  **先逐条 upsert，全部成功后才写结果 Excel**。动机：填错国家/行业的那一轮可直接丢掉、不污染库。
  代价（用户拍板接受）：没点结束就关工具＝丢一轮。
- ⛔ **不变量：结果 Excel 里的行，客户库里必须都有**（否则下次采到同站又当新客户重复进表）→
  顺序必须**先库后表**、入库失败就**不产出** Excel；upsert 幂等 → 重试不重复。
- ⛔ **本轮内去重靠 `_session_has_url(url)`**（比 `session_rows` 里 kind='added' 行的 `normalize_domain`）：
  本轮采的还没入库，`db_has_customer()` 看不见（踩过：同一个站在一份表里出现 3 次）。
- ⛔ **删除不再三条路都双删**，各按各的口径：
  - `/manual`（按 `rid`）：**默认只删内存明细**；仅当 `kind='added'` **且** `db_has_customer(url)` 为真
    才调 `_delete_customer_and_backup()`（来源＝「已入库但结果 Excel 没写成功」的保留行）。
    **灰字 `kind='existed'` 行永不碰库**（用户明确要求）。`kind` 不能丢——去重/删除都靠它。
  - 主页实时明细（`/api/live/delete`，按 `n`）：**仍双删**（自动链路当场落库）→ 记墓碑
    `STATE['rows_deleted']`，worker `finally` 按 `n` 过滤后落盘；`n` 单调递增不复用，两个 worker
    开头 + `api_start` 都清墓碑。⚠️ **只在 `running and phase=='search'` 时可删**。
    ⚠️ `n=True` bool→int 变 1 → 先 `isinstance(raw,bool)` 置 None。
  - `/db`（按主键 `id`）→ `db_delete_customers_by_ids(ids)` 返回 `(删除数, 没找到的 id)`；
    单行 ✕ 与批量同接口；**不动 `MANUAL_STATE`**。
- 三条删除路都挡空输入（`''`/`[]`/`None`/非法 → **返回 0**，绝不退化成 `DELETE FROM customers`），都不做 email 兜底。
- `backup_db_before_delete()`：**必须 sqlite3 在线 `backup()`；禁 `shutil.copy2`**（WAL 漏 `-wal`）；300 秒节流；失败不阻断；目录由 `db_path()` 推导。
- 文案：`popup.js`/`live-table.js` 按 `d.deleted ? '（客户库同步删掉 1 条）' : '（客户库里没有这条记录）'` 报；`/manual` 的 `modal.body` + `removeTitle` 已在 `ui/manual.html` 按本页语义改写（组件默认那套是给主页写的）。

## ⛔ 多值分隔符：邮箱 `', '` / 电话 `' / '`（M21，2026-10-11）
全链路邮箱一律逗号（用户点名），电话仍是斜杠（用户明确保留，**两者刻意不同**）。
- **写侧**：`EMAIL_SEP`（`_row10` / `_save_enrich_excel` / 两处写库 `email` 字段 / 两处实时明细 JSON）；
  **展示侧**：`content.js` / `popup.js`×2 / `ui/live-table.js`。
- ⛔ **读侧必须同步改**（飞书导出是**从结果 Excel 读回再拆**）：`split_emails()`（主程序）、`同步数据库到飞书.py`、`gen_import.py`
  → 一律 `re.split(r'\s*[,/]\s*')` **兼容新旧**。只改写侧 → `EMAIL_OK` 对整串失配 → **邮箱整列静默丢光**。
- 存量：库内 73 条多邮箱当天已刷逗号（备份 `DB/backups/客户库_邮箱分隔符刷新前_*.sqlite3`；`phone` 77 条未动）。
- 改了 `ui/live-table.js` → 只重算 `_check_page.py` 的 `_BUILT_SHA`（`_TMPL_SHA` 不变）。
- 守卫：`_check_live_ui.py`（页面 DOM 逗号）、`_check_feishu_records.py` ⑤（写侧 + 旧斜杠读回）、`_smoke_ext_popup.js`（插件明细）。

## ⛔ 计数一律报两组数「有效数 / 采集总数」（M19，2026-10-10）
**有效数** = 新增（真正入库、＝结果 Excel 行数）；**采集总数** = 明细行数 = 新增 + 已在库（老客户留灰字痕）；Excel **只写新增**。扩展面板与 `/manual` 的徽章 + 状态行都报 `有效 13 / 共 17`、`有效 2 · 采集总数 3 · 已在库 1`（`liveBadgeText(st,n)` / `breakdownText(st,n)` / `roundTally(st)`）。⛔ **老写法只报一个「已采 N 条」＝总数，把重复也当成成功数 → 用户点名要改**。
- ⛔ **本轮已结束时的陷阱**：`_flush_manual_session` 成功后把 `session_rows` 清空、但**留着 `added`/`existed`** 给 `roundTally` 用 → 徽章/悬停**必须按 `session_active` 门禁取这两个数**，否则会报出「有效 5 / 共 0」这种自相矛盾的数。
- 共享组件靠 **`cfg.badgeText(st, n)`**（默认 `n + ' 条'`）区分两页：主页 `showExisted:false`（N 天然＝有效数，保持「N 条」不动），`/manual` 传 `liveBadgeText`。`reset()` 会调 `badgeText(null, 0)` → 回调**必须能在 `st` 为 null 时安全求值**。
- 主页「本次任务采集数量」本来就按**新增个数**停（`len(all_rows) >= target_count`，`all_rows` 只装新增）→ 与「有效数」天然对齐，**本次没动主页**。

## ⛔ 主页卡片顺序 & 采集数量强必填（M17）
编号**硬编码在 `<h3>`**（无计数器）→ 插卡/挪卡**必须整轮重排编号** + 同步**三处提示语**（`start()` 两条 alert、`#comboSummary` 占位、`#rawCard` 说明）；漏改不报错，只是指错步骤。
- 采集数量**强必填 = 两道兜底一起删**：前端只许 `el.valueAsNumber`（⛔ 不许 `|| '10'`），后端只许 `data.get('target_count')`（⛔ 不许第二个缺省值参数）。只删一边 = 假必填。R13 + `_check_live_ui` G 段守着。
- 输入框**仍预填 `value="10"`**；后端校验**刻意留在产品词校验之后**；三条链路共用它 → **别**隐藏/置灰；文案**逐字保留**（`expects` 里有 `'按新增个数计'`）。

## ⛔ 自定义搜索词 / 国家限定（细节见档案 M14/M15）
- **自定义搜索词**（第 7 卡 → `run_search(raw_queries=…)`）：手写查询**一字符不加**、**不做中国过滤**（`china_filters=set()`）、与标准模式**互斥**、国家不进搜索词。四点静默坑：**三处校验一起放宽**（前端 `start()` 两处 + 后端 `api_start`）；**`cond_list` 必须给占位模板** `[('自定义','{p}')]`（留空 → **静默跑 0 条**）；**预览 `renderCombos()` 同步切分支**；`is_blocked()` 平台黑名单**仍生效**。
- **国家限定**（`#countryLimit`：`none`默认/`cr`/`site`/`both`）：**默认关**；`cr=countryXX`（大写 ISO）只挂 URL、`site:.xx` 只进搜索词；`COUNTRY_LIMITS` 是**独立字典**（不动 `COUNTRIES` 4 元组）；`custom_mode` → 强制 `none`。陷阱：`open_search` 兜底轮丢 **cr**；`site:` 与领英条件**互斥**；**限定更严 ≠ 更准**（法国实测 10→7）。
- **国家限定**（`#countryLimit`：`none`默认/`cr`/`site`/`both`）：**默认关、行为与旧版一字不差**；`cr=countryXX`（大写 ISO）只挂 URL、`site:.xx` 只进搜索词；`COUNTRY_LIMITS` 是**独立字典**（不动 `COUNTRIES` 4 元组）；`custom_mode` → 强制 `none`。陷阱：`open_search` 兜底轮丢 **cr**；`site:` 与领英条件**互斥**；**限定更严 ≠ 更准**（法国实测 10→7）。

## ⛔ 产物目录默认不读（用户明确要求）
`output/` 与 `DB/backups/` 是**运行产物** → 清单/条数可以瞄，**内容一律不读、不比对、不追查「少了几份」**。只有用户点名才读。

## ⛔ 海关商品编码采集脚本（2026-10-06，**配方与全部坑见 `TRAPS.md`**）
`海关商品编码采集.py`（+ 同名 `.bat`）→ `output/海关编码/`；独立脚本，**不 import `core.*`**。
- ⛔ `stats.customs.gov.cn` 挂**瑞数防护** → 普通 HTTP 一律 **412**，**只能真浏览器**；名称取 `.th-line` 的 `title`（可见文本被截断）；就绪判据须含「`hidPageNum` == 目标页号」否则会**静默取到上一页**。

## 关键约定速查
- 库 `DB/客户库.sqlite3`（表 `customers`，WAL）；结果 Excel 落 `output/` 根，查询导出落 `output/查询导出/`。`find_latest_result()` 从**文件名解析时间**（字典序≠时间序）；`ts_result_path()`/`ts_query_export_path()` 自带 `_2/_3` 去重。
- 哨兵 `QUERY_EMPTY='__empty__'`：前端 `const EMPTY` 与后端**一字不差**；筛选选项一律由 `db_facet_counts()` 读真实库 distinct 生成、**页面零硬编码行业名**。
- 拆包遗留：入口**只许绝对导入** + `sys.path` 自举 3 行，搬走的名字要在入口**同名 re-export**；`_app_dir()` **不许**写 `dirname(abspath(__file__))`；`ENRICH_FILE` 是唯一被重新赋值的模块级变量（内部一律 `paths.ENRICH_FILE`）。
- `.workbuddy/` 与程序零耦合。**别删**：`memory/*`、`_todo.json`、`_fail_q1_p0.png`、回归脚本、两个 `_*_before.json`。`.gitignore` 是**白名单式**（`.workbuddy/_*` 全排除再 `!` 逐条放行）→ 新增回归脚本要确认被 `!` 覆盖（`??` = 已放行）。
- 词库字节约定：UTF-8 无 BOM / **纯 CRLF** / 2 空格缩进 / 末尾无换行（`json.dumps` 出的 LF 要 `replace('\n','\r\n')` 后**二进制写**）；三级下拉顺序 = `sorted(keys)`。脚本 `补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py` / `标注空行业.py`（后两个要 `--apply` 才写）。

## git / 远端
- 附注标签 V1.0–**V1.4**（`-a -m`）；V1.4 起**不写提交 hash** → `git rev-parse "V1.4^{commit}"`。**用户会自己做备份提交**：`备份1`(`f69f1af`)/`备份2`(`d332048`) 打**轻量标签** `v1.5`/`v1.5.1` → **别只认大写 `V1.x`**（`git tag -l` + `git for-each-ref refs/tags`）。**M16/M17/M18 未提交**。
- 远端 = public：`origin=https://github.com/jurryzhang66/waimao.git`；`git push origin main --tags`；凭据 `helper-selector`(GCM)。⛔⛔ 公开仓库已含 ① `DB/客户库.sqlite3` 真实客户 ② `output/` 结果表 ③ `DB/backups/` ④ **飞书 BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`** → 收口只能 `git filter-repo` + 强推 + 轮换 token。

## ⛔ 功能坑 / 回归脆弱点 / 本机环境（动手前必读）
飞书 `官网` 字段与 `HERMES_HOME`、词库 `cond_template`、`open_search`/`_back_to_search`、扩展唯一 fetch 出口与 CORS、
地图 `div[role="feed"]`/`maps_role_word`、bash 残缺 / 项目解释器 / 端口漂移 / `C:` 盘、评分方向反、数据待办 —— 细节在
**`AI_PROJECT_CONTEXT.md` §7 / §9.4 与同目录 `.workbuddy/memory/TRAPS.md`**；改对应模块前先读，别凭记忆动手。
