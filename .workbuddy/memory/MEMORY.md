# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

定位：搜索潜在客户 → 就地补全邮箱电话 → 评分 → 存 SQLite → 导出飞书。
原始细节看 `memory/YYYY-MM-DD.md` 日志（09-27 ~ 09-30）。本文件只留「不看会踩坑」的东西。

## 结构与硬约束
- 入口 `客户开发工具.py`（路由 + 全部链路 + re-export + `pick_port`）。`core/`：`config`(条件/角色词/国家/黑名单 + `cond_template`，**零 import**) / `paths`(输出目录/命名/`find_latest_result`/`ENRICH_FILE`) / `state`(飞书配置/`STATE`/`STATE_LOCK`/`log`) / `db`(SQLite + `normalize_*` + `maps_place_key`) / `ui`(`_build_page → PAGE_HTML`，**import 期构建一次**)。`ui/page.html`(主页面，sha256 锁死) / `ui/manual.html`(手动采集页) / `extension/`(MV3) / `启动客户开发工具.bat`。
- ⚠️ **改 `ui/*.html` 必须重启工具**（服务端渲染在 import 期）。
- ⚠️ 入口只许**绝对导入**（`补历史欠账.py` 用 `spec_from_file_location` 加载，无包上下文）；顶部有 `sys.path` 自举 3 行。
- ⚠️ `_app_dir()` 不许写 `dirname(abspath(__file__))`（搬进 core/ 后会静默指向 `core/output`、`core/DB`）→ 取上一级 + 向上探测入口文件。
- ⚠️ `ENRICH_FILE` 是唯一被重新赋值的模块级变量：内部一律 `paths.ENRICH_FILE`，对外靠 PEP 562 `__getattr__` 转发（只覆盖属性访问，覆盖不到函数内裸名查表）。
- ⚠️ 打桩落点：子模块间必须 `模块.函数()`；smoke 必须 `m.db.db_path = m.db_path` + `_under_tmp()` 护栏，否则**静默写真实库**。
- ⚠️ 禁止并行 Edit 同一文件（会静默覆盖）。
- 端口不写死：`PREFERRED_PORTS=(5000,8000,8080,8765,9000,7000,6500,5800,5555)` + `pick_port()` 实测；本机 5000/8000 常被系统保留段圈走（裸 bind 报 `WSAEACCES 10013`，netstat 看不到占用）→ **以日志打印的真实地址为准**。

## 数据契约
- 库 `DB/客户库.sqlite3`，表 `customers`，按 `website_key` 去重，WAL；备份 `DB/backups/`。
- 结果 Excel 每轮一份 `行业-YYYYMMDD_HHMM-主国家.xlsx` 落 `output/`；`find_latest_result()` 按时间解析（**字典序≠时间序**）；`ts_result_path()` 自带 `_2/_3` 去重；`STATE['output']` 存 `output/<文件名>`。
- ⛔ **10 列硬契约**（`_save_enrich_excel` 写；飞书 `build_feishu_records` 与 `init_customer_db` 按下标读）：`公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家`。列名列序**一个都不能改**。
- 脚本：`补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py`(默认 dry-run，`--apply` 才写) / `demo.py` / `gen_import.py`。
- ⚠️ `.workbuddy/` 与程序**零耦合**（引用 0 处）。**别删**：`memory/MEMORY.md`、`_todo.json`、`_fail_q1_p0.png`、所有回归脚本。
- ⚠️ `.gitignore` 是**白名单式**（V1.4 起）：先 `.workbuddy/_*` 全排除，再用 `!` 逐条放行测试套件（`_run_all_reg.py`/`_check_*.py`/`_kwlib_check.py`/`_verify_maps_base.py`/`_smoke_*.py`/`_smoke_*.js`）。**新增回归脚本记得同步加一条 `!`**，否则备份里没有它。`*.log` 全局排除；`DB/backups/客户库_污染前_*` 排除（测试临时快照）。
- git `main`：V1.0 `07f146a` / V1.1 `7690296` / V1.2 `556d857` / V1.3 `65c0f2f` / **V1.4 = 附注标签 `V1.4`**（提交 `84f9584`）。⚠️ **V1.4 起不再往本文件写提交 hash** —— 该提交里就含本文件，写 hash 得再 amend、amend 又换 hash，永远差一位；取 hash 一律 `git rev-parse "V1.4^{commit}"`。查标签先 `git tag -l`。**标签全是附注标签**（`-a -m`），新版本照做。
- **远端（2026-09-30 接入）**：`origin` = `https://github.com/jurryzhang66/waimao.git`，**仓库是 public**（用户在我列出全部风险后仍明确同意公开）。仓库级身份 `jurryzhang66 <jurryzhang66@users.noreply.github.com>`（⚠️ 旧提交 V1.0~V1.4 的作者**仍是占位值** `github用户名 <github注册邮箱>`，当时选择了不重写历史）。推送 `git push origin main --tags`；凭据走 `helper-selector`(GCM)，本机无缓存，实测直接推成功。
- ⛔⛔ **公开仓库既成事实（用户知情同意）**：`main` 与全部标签含 ① `DB/客户库.sqlite3` **253 条真实客户**（156 邮箱 / 90 电话）② `output/` 16 份结果表 ③ `DB/backups/` 3 份库快照 ④ **飞书 BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`**（`core/state.py` / `同步数据库到飞书.py` / `回填行业.py` / `.workbuddy/_backfill_rules_snapshot.py`）。**推上去就删不干净**（历史 + 已被抓取）→ 要收口只能 `git filter-repo` 重写 + 强推 + **轮换飞书 token**。以后往仓库加敏感文件前先想清楚这一步。
- `.venv/` 必须保持 gitignore。回滚 `git checkout V1.4 -- <file>` 或复制 `DB/backups/`。
- ⚠️ 本机 `core.autocrlf=true`。**不影响 `ui/page.html` 的 sha256 锁**：`core/ui.py` 与 `_check_page.py` R5 都用 `open(..., encoding='utf-8')` **文本模式**读，Python 通用换行会把 CRLF 归一化成 LF（实测：CRLF 版二进制 35697B ≠ 35058B，但文本模式读出来仍是 `85207b10…`）。已验证过一次，**别再当隐患返工**。

## 关键词库 `关键词库.json`
`{行业:{品类:{产品:[词条]}}}` = **8 行业 / 14 品类 / 40 产品 / 126 词条**。规范行业名：**宠物用品 / LED照明 / 家具 / 服装 / 机械零部件 / 户外用品 / 食品 / 塑料包装袋**。词条 9 语言 `en,cn,de,fr,es,ar,it,nl,tr`（`fa` 仅食品 33 条，插在 `ar` 后）。
- ⚠️ 字节约定：UTF-8 无 BOM / **纯 CRLF** / 2 空格缩进 / 末尾无换行。`json.dumps(indent=2, ensure_ascii=False)` 出的是 LF → 必须 `replace('\n','\r\n')` 后**二进制写**。
- ⚠️ 页面三级下拉顺序 = `sorted(keys)`（Flask `app.json.sort_keys` 默认 True，jsonify 每层 dict 都排序），不是文件键序。
- 校验 `_kwlib_check.py`（含与 `_kwlib_before.json` deep-diff）。改库用一次性脚本按 `en` 原文匹配整体重写；结构变更必须同步改前端 JS。

## 国家→语言 / 搜索条件多语言化
- `_build_page()` 注入 `counts_js`；前端 `COUNTRY_LANG`/`COUNTRY_GL` + `applyCountryLang()` 自动勾语言。已知副作用（用户接受）：非食品行业选伊朗/阿富汗 → 标签显示波斯语但词条回落英文。
- `CONDITIONS` 是 `(key, 中文名)` 2 元组；骨架 `COND_TEMPLATE`（含 `{p}`/`{role}`）；`COND_ROLES[key][lang]` 有 8 语言（缺则回落 en）；`cond_template(key, lang)` 是唯一出口 —— **后端 `run_search` 与前端预览都必须走它**。语言优先级：`#kwLang` → 该国 `hl` → `en`。
- ⚠️ 模板里 `{p}` **别加引号**（`pq_list` 已包好），否则拼出 `""xxx""`；含 OR 的模板**必须用括号锁住同义词组**。
- 国家筛选走 URL 参数 `&gl=<偏好国>&hl=<界面语言>`，**不写进搜索词**。`cr`/`lr` 实测不值得加（已拍板）。

## 搜索链路（最易碎）
- 判渲染 `RESULT_LINK_CSS='css:a:has(h3)'`；开页必须走 `open_search(page, formula, country_params, start, min_items, attempts)`（前 2 轮直连 `/search?q=`，第 3 轮搜索框兜底）。壳页面 `refresh()` 救不回，重新导航即可。
- ⚠️⚠️ **「结果没渲染」两种成因日志分不开（未修）**：① 壳页面（重开能好）② **谷歌零结果页**（`did not match any documents`，重试同 URL 无效；证据 `_fail_q1_p0.png`）。触发 = 新会话第一个谷歌请求 + 重公式（33 词）→ 是**冷会话首请求被降级**，不是 gl/hl 或公式问题。修法未拍板。
- `is_blocked()` 三层：`BLOCK_SUBSTR` → `SEARCH_ENGINE_PREFIX` → `BLOCK_DOMAINS` + `endswith('.cn')` 兜底。`EXCLUDE_OPTIONS` 是**查询词级**排除，与域名黑名单两套，加平台站两边都加。
- ⚠️ 结果链接是跳转链：必须 `resolve_goto()`；判跳转必须用 `_is_search_engine_url()`（去 `www.` 比前缀）—— 旧硬编码 `google.com/goto` 在 `google.com.hk` 上失配会一页 10 条全丢。
- ⚠️ 谷歌限流：连返壳页面 → 三次重试失败跳页 → **等 90 秒**恢复。别误判 bug。

## 任务流水线（搜索+补全一体化）
- `run_search` 自身即闭环：新网站 → `db_upsert_customer` → **立刻** `enrich()` → 评分 → 再 upsert（空值不覆盖）→ 追加 `all_rows`。凑够 `target_count` 个**新增网站**即停；`finally` 里 `page.quit()` 后落盘（中途停止不白跑）。
- ⛔ 「补全联系方式+评分」按钮已删除，**但 `enrich_core`/`_enrich_worklist`/`enrich()`/`_save_enrich_excel` 必须保留**（脚本与搜索链路在用）。
- ⚠️ 标签页陷阱：`enrich()` 用 `page.new_tab()`，`open_search` 用 `page.get()` → 补全后必须 `_back_to_search(page, search_tab_id)`。⚠️ `ChromiumTab` **没有 `new_tab()`**。
- 前端 `#liveBody` 实时入库明细；`/api/status` 返回 logs/result_count/phase/**rows**/db_total/db_verified。
- ⚠️ worklist 判据是「邮箱电话都为空」而非「补过没补过」→ 欠账脚本会反复访问抓不到联系方式的站（实测 26 条）。彻底修需加 `enriched_at` 列（未拍板）。

## 谷歌地图采集
- `/api/start` 按 `source` 分流 `run_maps`。选择器：`div[role="feed"]`（**滚 feed 本身，不滚 window**）、`a[href*="/maps/place/"]`、详情靠 `data-item-id` 三件套（`phone:tel:` / `authority` / `address`）。
- ⚠️ `maps_detail` 必须**直接导航到 place URL**，不能点卡片（点开列表被详情替换 → 其余句柄 `NoRectError`）。
- ⚠️ **身份词必须拼进地图查询词**（`maps_role_word(cond_keys, lang)`），否则只返回餐馆。
- 去重键 `maps_place_key()`（抓 `!1s0x…:0x…`）；`COUNTRY_CENTERS` 25 国 + 城市框；单次硬上限 ~120 条，达目标即停，落盘复用 10 列 Excel。

## 手动采集 + Chrome 扩展（MV3）
- 语义（2026-09-30 改为「本轮会话」）：`/manual` 点「开始本轮」开轮；**扩展单点若本轮未开会自动替用户开轮**（`_ensure_manual_session`，口径只在开轮那一刻记下）；`added/existed/failed/upgraded` 是**本轮**语义（开轮清零，批量开始不再清零）。`MANUAL_STATE` 是独立状态，绝不复用 `STATE['stop']`。
- 落盘 `_flush_manual_session()` → `_save_enrich_excel(rows, industry, country)` **新建**一份结果文件并成为「最新结果文件」；**空轮不落盘**；**失败保留 `session_rows` 且 `session_active` 仍 True** 可一键重试。
- 路由：`/manual`、`/api/ping`、`/api/collect`、`/api/manual/{batch,stop,state,close_browser,session/start,session/finish,session/delete}`。`MAX_CONTENT_LENGTH=2MB`。
- 唯一入口 `collect_from_html(url,title,html,industry,country,source='手动采集',allow_upgrade,product_words)`：三级抓取（① 扩展送的 HTML 秒级正则 ② `requests` 抓页面自带 contact 链接 ③ `enrich()` 升级），收尾走 `_commit_candidate`（评分 + 写库 + 11 键行）。⚠️ **采集即落库** —— `_commit_candidate` 当场 `db_upsert_customer`，「本轮明细」只是内存清单（决定 Excel 有哪些行）。
- ⚠️⚠️ **`log()` 内部会抢 `STATE_LOCK`（非可重入 `Lock`）→ 任何 `log` 必须在 `with STATE_LOCK` 块外调；DB IO 一律锁外**。历史踩过 2 次死锁。删除路由的骨架就是这条纪律的样板：①锁内定位 ②锁外备份+删库 ③锁内改内存 ④锁外 log。
- **删除单条明细（2026-09-30）**：`POST /api/manual/session/delete` 按 **`rid`** 定位（`session_rid_seq` 发号器）—— 同一 url 在同一轮里可能既有 `added` 又有 `existed`，按 url 删会一次删两条。必须**明细 + 客户库双删**（只删明细是假删除：库里那条还在 → 下次采到同站被判「已在客户库」跳过、永远采不回来、飞书仍会带它）。`core/db.py`：`backup_db_before_delete()`（**必须 sqlite3 在线 `backup()`；禁止 `shutil.copy2`**，WAL 会漏 -wal；300 秒节流；失败不阻断）+ `db_delete_customer()`（key 为空直接返回 0，绝不退化成清库）。备份目录由 `db_path()` 推导 → 打桩了 `m.db.db_path` 的脚本自动落临时目录。UI：`ui/manual.html` 每行 ✕（**事件委托挂 `#sessionBody`**，行是 innerHTML 拼的、换轮会清表，逐行绑必丢）+ popup `.li-del`（委托 `#sessList`）；**`popup.js` 里 `fetch(` 必须为 0** → 走 `DP_SESSION_DELETE` 由 background 代发。
- CORS 三重门：只回显 `chrome-extension://` 来源的 ACAO（**绝不 `*`**）+ 自定义头 `X-DP-Ext: 1`（必触发预检）+ `get_json()`；`after_request` 校验并顺带当扩展心跳（`ext_last_seen`）。
- 扩展：权限仅 `activeTab/scripting/contextMenus/storage`，host 只给 `127.0.0.1`+`localhost`。`background.js` 是**唯一 fetch 出口**（`popup.js` 里 `fetch(` 必须为 0，`_check_ext.py` 硬断言）。悬浮按钮用 **Shadow DOM(closed) + `adoptedStyleSheets`**（manifest 的 `.css` 跨不过 shadow 边界）。
- ⚠️ `popup.js::finishSession()` 末尾必然 `refreshSession()` → 一次性提示必须写进 `_note` 才留得住（只写 `status` 会被刷新吃掉）。
- ⚠️⚠️ **改 `extension/` 后不点「重新加载」会出现「popup 新 / service worker 旧」分裂态**：新 popup 发 `DP_MANUAL_STATE`，旧 SW 落到 `default:` 回 `未知消息：…`，用户看到「0 条」以为采集失败。`_smoke_ext_popup.js` ⑤ 段已固化成断言。
- ⚠️⚠️ **联调必须遮蔽环境里别的实例（`DP_SHADOW_PORTS`）**：扩展按 `PREFERRED_PORTS` 扫 `/api/ping`，会连上用户自己开在 8000 的实例 → **把测试假网址真写进真实客户库**（踩过，已备份后清理）。跑全量前最好先关掉工具。
- 人工步骤未做：① `chrome://extensions` 加载 `extension/`；② 飞书「客户信息」表 `来源渠道` 加 `手动采集` 选项；③ 装/改扩展后已开页面要刷新。④ ⚠️ **改了 `extension/` 或 `ui/*.html` 后必须「重启工具 + 点重新加载」两件事都做**：2026-09-30 实测用户跑着的实例（5000）打新路由 `/api/manual/session/delete` 是 **404**（旧代码）。自检口令：`curl` 一下该路由 —— 404 = 后端旧，得重启。

## 回归脚本（`.workbuddy/`，绝对路径加载主工具）
- 全量 **19 项**：`python .workbuddy/_run_all_reg.py`，每项写 `_reg__<名>.log`，退出码全 0 才算过；跑完查真实库条数没变。⚠️ **别再拿固定数字当基线**（用户在持续用扩展自己采）：2026-09-30 15:30 是 **253** = 谷歌搜索 214 / 手动采集 32 / 谷歌地图 7。**按 source 分布看一遍 + 查测试域名残留**才是有效复核（测试域名清单见 `_reg_summary.txt`）。验收记录 `_reg_summary.txt`。
- ⚠️⚠️ **4 个「回归脚本自身脆弱点」**（改脚本前先看，否则会白追假红）：① `_check_startup` 别把换端口原因写死成 `'10013'` —— 5000 绑不上的成因会漂移（保留段 → 10013；**有别的进程真占着它 → 10048**）；② `_check_manual_ui` 的心跳/渲染断言别只 sleep 固定时长（页面 1s 轮询 + async fetch 有竞态）→ 一律轮询等目标态；③ 真机脚本的**整页截图只是证据不是断言** → `try/except` 尽力而为（3838px 截图偶发 CDP 超时）；④ `_smoke_ext_live` 两遍共用 `core.db` **模块对象** → 模块级时间戳（如 `_last_delete_backup_at`）会跨遍残留，`load_tool()` 里必须清零。
- 清单：`_check_page`(页面文案 + 拆包 R1–R6 sha256/单例) / `_check_startup`(pick_port + 真起进程) / `_kwlib_check` / `_check_industry_rules` / `_verify_maps_base` / `_smoke_search` / `_smoke_maps` / `_smoke_collect` / `_smoke_manual_session` / `_check_feishu_records` / `_check_maps_ui` / `_check_kwlib_ui` / `_check_live_ui` / `_check_manual_ui` / `_check_ext` / `_smoke_ext_content` / `_smoke_ext_popup` / `_smoke_ext_live` + `补历史欠账.py --dry`。
- ⚠️ `_check_ext.py` C 组跨文件硬断言：主工具 `PREFERRED_PORTS` 必须逐字等于 `extension/ports.js` 的 `DP_PREFERRED_PORTS`。`_check_ext.py` / `_smoke_ext_bg.js` 都从 `extension/` 现场读文件 → **改扩展必跑**。
- ⚠️ `_smoke_ext_live.py` 走真 Chrome + 真 Flask，**会真写库** → 靠 `DP_SHADOW_PORTS` 遮蔽别的实例。`_check_startup.py` 的「候选全不可用兜底」必须现场占临时端口，别写死。
- ⚠️ `.workbuddy/_smoke_ext_popup.js` 的 DOM 桩能力边界：`El` 只有 `id/className/textContent/hidden/disabled/checked/value/style/scrollTop/scrollHeight/_html/_writes/_ih/_listeners` + `innerHTML` setter/getter + `addEventListener/emit(type, extra)/insertAdjacentHTML`；**没有** `dataset/classList/createElement/closest/matches`；`document` 只有 `getElementById`。⚠️ `emit(type)` 回调默认只传 `{preventDefault(){}}`（**无 `target`**）→ 测「点某一行」要显式传假 target：`emit('click', {target: {closest: s => s === '[data-rid]' ? {dataset:{rid:'1'}} : null}})`。`window.confirm` 由脚本顶部的 `CONFIRM_RETURN` 桩控制。

## 飞书多维表格
- BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`；表 `客户信息` TABLE_ID `tblY38YnVIQ5AYYA`；CLI `C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`。
- 坑：调用前 `pop('HERMES_HOME')`；`--limit` 上限 200，翻页 `--offset`；**官网字段名就叫 `官网`**（按「网站/网址」查会静默 0 命中）；`邮箱` 只收单个合规邮箱（多余写入 `备注`）；select 字段值用数组；本地「沙特」→ 飞书「沙特阿拉伯」；`+field-update` 是**全量 PUT**。
- `来源渠道` 三值 `谷歌搜索/谷歌地图/手动采集`（`FEISHU_SOURCES`）：结果 Excel **无来源列**（契约不能改），故 `build_feishu_records()` 一次性 `SELECT website_key, source` 按 domain 查真实来源。**50 分门槛对 `[手动采集]` 行豁免**。
- 遗留：飞书「行业」字段选项仍是旧四值（需人工改成 8 规范值）；16 条垃圾记录待删（`_todo.json`）。

## 本机环境
- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c` 或 PowerShell；PowerShell 输出不回显时写临时文件再 Read。`wmic` 被屏蔽 → `Get-CimInstance Win32_Process`。
- ⚠️ TCP 保留段（Hyper-V/WinNAT）**每次开机漂移**（`netsh interface ipv4 show excludedportrange protocol=tcp`）→ 本地服务端口必须自动避让，**别把「某端口被保留」写进断言**。
- 删文件进回收站：Python `ctypes` 调 `SHFileOperationW`（`Add-Type`/COM 被拦）；**返回非 0 也可能已成功，必须 `os.path.exists()` 复查**。
- Python：`D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`。

## 数据质量待办
- 库里混平台垃圾域名（joybuy/dreamstime/chegg/thomasnet/trendyol/u-buy/petz.ae/suppliergo/archive.org/tiktok 等）约 25~36 条未清。
- ⛔ **评分在非英语场景方向是反的（20 条法国结果实锤，未修）**：`CTYPE_WORDS`(`wholesale/distributor/...`) 全英文，法语 `grossiste/distributeur/fournisseur` 一个不认；`score_item()` **只有加分无减分**。根治三件事：① `CTYPE_WORDS` 多语言化 ② `PRODUCT_WORDS` 按本轮产品词动态传入 + 词边界 ③ 加否决/减分项（`.gov`/点评站/餐馆/菜谱/B2B 名录/新闻）。
- `PRODUCT_WORDS=['litter','liner','cat','pet']` 写死猫砂垫且**子串匹配无词边界** → 换行业必须同步改。
- 行业取值已统一：`回填行业.py` 的 `INDUSTRY_RULES` 对齐 8 规范值（`^` 前缀 = 整词）。`重标行业.py` 2026-09-29 dry-run 待改 **23 条**（家具家居 18 → 家具、汽配 5 → 机械零部件）。
- 未拍板：① 「半自动组合/纯手工输入」单选未实现；② 冷会话首请求降级修法未定；③ 飞书 16 条垃圾待删；④ 客户库 id=154 淘宝记录待清；⑤ 3 条用户自采记录里 `127.0.0.1` 与 `erp.91miaoshou.com` 属明显误采，是否清理未定。
