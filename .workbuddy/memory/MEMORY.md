# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

定位：搜索潜在客户 → 就地补全邮箱电话 → 评分 → 存 SQLite → 导出 Excel / 飞书。

> 📍 **结构 / 功能模块 / 核心实现 / 可复用件 / 设计决定 / 已知问题 / 开发状态 → 一律看项目根 `AI_PROJECT_CONTEXT.md`**（2026-10-01 建立；§4.3 锁纪律、§6 设计决定、§7 已知问题、§9.2「最容易犯的 15 个错」）。
> 本文件**只留「不看会静默出错」的硬约束**，与档案刻意不重复；过程细节看 `memory/YYYY-MM-DD.md` 与 `.workbuddy/_reg_summary.txt`。

## ⛔ 四条硬不变量

1. **`website_key` 恒等于 `normalize_domain(website)`**（`_check_db_keys.py` 只读守着，真实库实测错位 0）。
   候选口径不一致：`db_has_customer()`（判跳过）**只**查 `website_key`，而 upsert（写入）是「按键查不到、再按 email 兜底合并」。键一错位，该网址**永久**被判「新客户」：每采一次 Excel 多一行、库里始终只有一条（实测 id=267 键 `megafood.mx`/网址 `megazone.mx`，后者一份表里出现 **3 次**）。修法：upsert 合并时键自愈（新键被占用则只记日志）+ 存量用 `db_fix_website_keys(apply=)`。
2. **结果 Excel 10 列硬契约**（列名列序一个都不能改）：`公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家`。飞书 `build_feishu_records` 与 `init_customer_db` 都按**下标**读。
3. **`ui/page.html` 有 sha256 基线**（`_check_page.py` R5 的 `_TMPL_SHA` + `_BUILT_SHA`，两条都要对）。**它现在可以改**（V1.5 加首页顶栏导航时改过一次），但**故意改就必须同步重算这两条** —— 漏一条 R5 就红；基线的剩余价值 = 误格式化/误翻译改变形时立刻抓到。副页面（`/manual`、`/db`）的 `<style>` 由 `PAGE_CSS_PLACEHOLDER` 从它这里注入 → **往那份里加规则会连带影响三个页面**，本页专有样式写副页面自带的第二个 `<style>`。
4. **查询导出必须落 `output/查询导出/` 子目录**。`find_latest_result()` 只 glob `output/` **一层**、按文件名 8 位日期筛候选 → 查询导出表名天然带日期，落根下会被当成「最新结果文件」，**劫持飞书导出目标**。`_smoke_query.py` 有反证断言（占位结果表刻意写 2000 年、比导出**旧**，否则反证失效）。

## ⚠️ 锁纪律（历史踩过 2 次死锁）

`STATE_LOCK` 是**非可重入** `Lock`，`log()` 内部也要抢它 → **任何 `log()` 必须在 `with STATE_LOCK` 块外调；DB IO 与文件 IO 一律锁外。**
四段式骨架（样板 `api_manual_session_delete`）：①锁内定位 ②锁外备份+IO ③锁内改内存 ④锁外 log。
**查询 / 导出链路刻意完全不碰 `STATE_LOCK` / `STATE` / `paths.ENRICH_FILE`**（长查询占锁会卡死采集与轮询）；导出另用独立 `EXCEL_LOCK`。

## ⚠️ 改完必须「重启 / 重新加载」（最常忘）

- 改 `ui/*.html` → **必须重启工具**（`PAGE_HTML` / `MANUAL_HTML` / `QUERY_HTML` 都在 import 期构建一次）。
- 改 `extension/` → **必须点 `chrome://extensions` 的「重新加载」**，否则「popup 新 / SW 旧」分裂态：新 popup 发 `DP_MANUAL_STATE`，旧 SW 落到 `default:` 回「未知消息：…」，用户看到「0 条」以为采集失败（`_smoke_ext_popup.js` ⑤ 段已固化成断言）。
- 交付新功能**两件事都要告诉用户**：实测用户跑着的旧实例（5000）打新路由是 **404**。自检口令：`curl` 那个新路由，404 = 后端旧。

## ⚠️ 打桩 / 回归纪律

- 全量 `_run_all_reg.py` 现为 **22 项**（新增 `_smoke_query` 126 项、`_check_query_ui` 真机）。
- 子模块间必须 `模块.函数()`（如 `m.db.db_path = …`）；smoke 必须有 `m.db.db_path = m.db_path` + `_under_tmp()` 护栏，**否则静默写真实库**。打桩临时库**必须同时打桩 `paths.ENRICH_FILE`**（`init_customer_db()` 在「库为空」时会从它导数据 → 否则测试跑在真实数据上，看起来还是绿的）。
- **禁止并行 Edit 同一文件**（会静默覆盖）。
- **只有两项刻意扫真实库**：`_check_db_keys.py`（只读）与 `补历史欠账.py --dry`；其余全打进临时目录 → 红了多半是**真实数据**要人工修，别把断言改松。
- ⚠️ **别拿固定数字当基线**（用户在持续用扩展自己采：227 → 247 → 253 → 277 → 290 → 292）。有效复核 = **按 source 分布看一遍 + 查测试域名残留**（清单见 `_reg_summary.txt`）。
- ⚠️ **6 个「回归脚本自身脆弱点」**（不是产品 bug，但会让回归假红）：① `_check_startup` 别把换端口原因写死 `'10013'`（进程真占着时是 10048）；② `_check_manual_ui` 心跳/渲染别只 sleep（async fetch 有竞态）→ 1s 轮询等目标态；③ 真机整页截图**只是证据不是断言** → `try/except` 尽力；④ `_smoke_ext_live` 两遍共用 `core.db` **模块对象** → 模块级时间戳（`_last_delete_backup_at`）跨遍残留，`load_tool()` 里必须清零；⑤ `<select>` 程序化赋值**不存在的 value 会被忽略** → 测试里动态 `createElement('option')`；⑥ `send_file` 响应**持有文件句柄** → 删临时文件前先 `dl.close()`，否则 `WinError 32`。
- ⚠️ `_check_ext.py` C 组硬断言：主工具 `PREFERRED_PORTS` 必须逐字等于 `extension/ports.js` 的 `DP_PREFERRED_PORTS`。**改扩展必跑 `_check_ext.py` / `_smoke_ext_bg.js`**（现场读 `extension/`）。
- ⚠️ `_smoke_ext_live.py` 走真 Chrome + 真 Flask，**会真写库** → 靠 `DP_SHADOW_PORTS` 遮蔽用户开着的实例；跑全量前最好先关掉工具。
- ⚠️ `_check_page.py` R4 是**字符串级 glue 断言**：`'from core.ui import PAGE_HTML, _build_page'` 必须保持单独一行（故 import 区刻意分两行，不合并 `QUERY_HTML`）。夹具自洽：`_check_manual_ui` 的 `MANUAL_STATE` 里 `added`/`existed` 要与 `session_rows` 一致；`_check_query_ui` 样本要**留一条无行业/无评分**的，「未填写」哨兵项才会出现。
- ⚠️ `_smoke_ext_popup.js` 的 DOM 桩很薄：`El` 只有 `id/className/textContent/title/hidden/disabled/checked/value/style/scrollTop·Height/_html/_listeners` + `innerHTML` + `addEventListener/emit`，**没有** `dataset/classList/createElement/closest/matches`；`document` 只有 `getElementById`；`emit(type)` **不带 `target`**（测点行要显式传假 target）；`confirm` 由 `CONFIRM_RETURN` 桩控制。

## ⚠️ 采集即落库 → 删除必须双删

`_commit_candidate` 采集那一刻就写 SQLite，「本轮明细」只是内存清单。**只删明细是假删除**：库里那条还在 → 下次采到同站被判「已在客户库」跳过 → 永远采不回来 → 飞书仍带它。
- 按 **`rid`** 定位（`session_rid_seq` 发号器），不按 url —— 同一 url 在一轮里可能既有 `added` 又有 `existed`。
- `backup_db_before_delete()`：**必须 sqlite3 在线 `backup()`；禁止 `shutil.copy2`**（WAL 会漏 `-wal`）；300 秒节流；失败不阻断。备份目录由 `db_path()` 推导 → 打桩了 `m.db.db_path` 的脚本自动落临时目录、护栏零改动。
- `db_delete_customer()`：key 为空直接返回 0，**绝不退化成清库**；刻意不做 email 兜底。

## ⛔ 「已采 N 条」≠「结果 Excel 行数」（用户报过）

明细行数 = **新增 + 已在库**（老客户也留一行灰字痕）；Excel **只写新增**（用户拍板，否则导飞书会重复推送同一家）。实测 `added=13, existed=4` → 13+4=17 是用户看到的数，Excel 13 行（+表头 14）。
三处都要拆开报：`ui/manual.html` 状态行 + `sessionFile` 行、`extension/popup.js` 状态行 + 结果行；徽章保持「N 条」（popup 太窄）但挂 `title` 写算式。函数 `breakdownText(st,n)` / `roundTally(st)`，**`roundTally` 只在 `!session_active` 时返回**。

## 关键约定速查

- 库 `DB/客户库.sqlite3`（表 `customers`，WAL）；备份 `DB/backups/`。结果 Excel 落 `output/` 根，查询导出落 `output/查询导出/`。`find_latest_result()` **从文件名解析时间**（字典序≠时间序）；`ts_result_path()` / `ts_query_export_path()` 自带 `_2/_3` 去重。
- 查询空值哨兵 `QUERY_EMPTY='__empty__'`：前端 `const EMPTY` 与后端必须**一字不差**（`_check_page.py` R9 断言），否则「勾了未填写却筛不出东西」= 静默失效。筛选选项一律由 `db_facet_counts()` 读**真实库** distinct 生成、**页面零硬编码行业名**（库里有历史行业名 `家具家居` 18 条 / `汽配` 5 条，硬编码规范 8 值会让它们怎么选都筛不出来）。
- ⚠️ 拆包遗留：入口**只许绝对导入**（`补历史欠账.py` 用 `spec_from_file_location` 加载，无包上下文）+ 顶部 `sys.path` 自举 3 行，搬走的名字要在入口**同名 re-export**；`_app_dir()` **不许**写 `dirname(abspath(__file__))`（搬进 `core/` 后会静默指向 `core/output`、`core/DB` = 换了一份**空库**且不报错）；`ENRICH_FILE` 是唯一被重新赋值的模块级变量（内部一律 `paths.ENRICH_FILE`）。
- ⚠️ `.workbuddy/` 与程序**零耦合**。**别删**：`memory/*`、`_todo.json`、`_fail_q1_p0.png`、所有回归脚本、两个 `_*_before.json` 基准。
- ⚠️ `.gitignore` 是**白名单式**（V1.4 起）：先 `.workbuddy/_*` 全排除，再 `!` 逐条放行测试套件 → **新增回归脚本要确认被 `!` 覆盖**（`git status --short` 出现 `??` = 已放行）。`*.log`、`output/查询导出/` 也排除。
- 词库字节约定：UTF-8 无 BOM / **纯 CRLF** / 2 空格缩进 / 末尾无换行；`json.dumps(indent=2, ensure_ascii=False)` 出 LF → 必须 `replace('\n','\r\n')` 后**二进制写**。页面三级下拉顺序 = `sorted(keys)`（Flask `json.sort_keys` 默认 True），不是文件键序。脚本：`补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py`(默认 dry-run，`--apply` 才写)。

## git / 远端

- `main` 版本：V1.0 / V1.1 / V1.2 / V1.3 / **V1.4**（全是 `-a -m` 附注标签，`git tag -l` 查）。
  ⚠️ **V1.4 起不再往本文件写提交 hash**（该提交含本文件，写 hash 得再 amend、amend 又换 hash，永远差一位）→ 一律 `git rev-parse "V1.4^{commit}"`。
- **远端 = public，用户知情同意**：`origin` = `https://github.com/jurryzhang66/waimao.git`；身份 `jurryzhang66 <jurryzhang66@users.noreply.github.com>`。`git push origin main --tags`；凭据走 `helper-selector`(GCM)。
- ⛔⛔ **公开仓库既成事实**：`main` 与全部标签含 ① `DB/客户库.sqlite3` 真实客户 ② `output/` 结果表 ③ `DB/backups/` 快照 ④ **飞书 BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`**。**推过就删不干净** → 收口只能 `git filter-repo` 重写 + 强推 + **轮换飞书 token**。以后加敏感文件前先想清楚。

## 飞书 / 词库 / 搜索 / 地图 / 扩展（只记最致命的）

- **飞书**：BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`、表 `客户信息` `tblY38YnVIQ5AYYA`、CLI `C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`。坑：调用前 `pop('HERMES_HOME')`；`--limit` 上限 200、翻页 `--offset`；**官网字段名就叫 `官网`**（按「网站/网址」查会静默 0 命中）；`邮箱` 只收单个合规邮箱；select 用数组；本地「沙特」→ 飞书「沙特阿拉伯」；`+field-update` 是**全量 PUT**。`来源渠道` 三值 `谷歌搜索/谷歌地图/手动采集`，结果 Excel **无来源列**（契约不能改）→ `build_feishu_records()` 按 domain 回库查真实来源；**50 分门槛对 `[手动采集]` 豁免**。
- **词库**：8 行业 / 14 品类 / 40 产品 / 126 词条、9 语言；`cond_template(key, lang)` 是**唯一出口**，语言优先级 `#kwLang` → 该国 `hl` → `en`。⚠️ 模板里 `{p}` **别加引号**；含 OR 的模板**必须用括号锁住同义词组**，否则退化成 `(A B) OR C`。⚠️ `COUNTRIES` 是 **4 元组**、前端按 **5 元组**注入，改长度会连带炸两处；国家筛选走 URL `&gl=&hl=`，**不写进搜索词**。改库后跑 `_kwlib_check.py`。
- **搜索**：判渲染 `RESULT_LINK_CSS='css:a:has(h3)'`，开页必须走 `open_search()`。结果链接是跳转链 → 必须 `resolve_goto()`；判跳转必须用 `_is_search_engine_url()`（旧硬编码 `google.com/goto` 在 `google.com.hk` 上失配会一页 10 条全丢）。⛔「补全联系方式+评分」按钮已删，**但 `enrich_core`/`_enrich_worklist`/`enrich()`/`_save_enrich_excel` 必须保留**。⚠️ `enrich()` 用 `page.new_tab()`、`open_search` 用 `page.get()` → 补全后必须 `_back_to_search()`；`ChromiumTab` **没有 `new_tab()`**。谷歌限流连返壳页面 → 等 **90 秒**恢复，别当 bug。
- **地图 / 扩展**（细节见 `AI_PROJECT_CONTEXT.md` M2 / M5）：地图滚 `div[role="feed"]` **本身不是 window**、`maps_detail` **直接导航 place URL**（点卡片会让其余句柄 `NoRectError`）、**身份词必须拼进查询词**（`maps_role_word`）否则只返回餐馆、`run_maps` 在 `china_filter_reasons()` **之前**就并入了地图电话；扩展 `background.js` 是**唯一 fetch 出口**（`popup.js` 里 `fetch(` 必须为 **0**）、悬浮按钮用 Shadow DOM(closed) + `adoptedStyleSheets`、CORS 只回显 `chrome-extension://` 的 ACAO（**绝不 `*`**）、`finishSession()` 末尾必然 `refreshSession()`（一次性提示要写进 `_note`）。

## 本机环境

- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c` 或 PowerShell；**别从 Bash 里 invoke PowerShell**（被安全策略拦）。`wmic` 被屏蔽 → `Get-CimInstance Win32_Process`。
- ⚠️ TCP 保留段（Hyper-V/WinNAT）**每次开机漂移** → 端口必须自动避让，**别把「某端口被保留」写进断言**；5000/8000 常被圈走（裸 bind 报 `WSAEACCES 10013`，netstat 看不到占用）→ **以日志打印的真实地址为准**。
- 删文件进回收站：`ctypes` 调 `SHFileOperationW`；**返回非 0 也可能已成功，必须 `os.path.exists()` 复查**。

## 数据质量待办（全清单见 `AI_PROJECT_CONTEXT.md` §7）

- ⛔ **评分在非英语场景方向是反的（20 条法国结果实锤，未修）**：`CTYPE_WORDS` 全英文、`score_item()` **只有加分无减分**；`PRODUCT_WORDS` 写死猫砂垫且**子串匹配无词边界**。
- 平台垃圾域名约 25~38 条未清（可在「本轮明细」点 ✕，也可用 `/db` 筛出来核对）；`重标行业.py` dry-run 待改 **23 条**（家具家居 18 / 汽配 5），**尚未 `--apply`**。
- 其余未拍板：半自动/纯手工单选、冷会话首请求降级修法、飞书 16 条垃圾待删、id=154 淘宝记录、两条误采（`127.0.0.1` / `erp.91miaoshou.com`）、阶段 B 拆包、**最近两轮改动（含查询页）尚未 git commit（是否打 V1.5 待拍板）**。
