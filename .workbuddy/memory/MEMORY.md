# 项目长期记忆：D:\waimao\dp（谷歌外贸客户开发工具）

定位：搜索潜在客户 → 就地补全邮箱电话 → 评分 → 存 SQLite → 导出 Excel / 飞书。

> 📍 结构 / 功能模块 / 核心实现 / 设计决定 / 已知问题 / 开发状态 → 看项目根 `AI_PROJECT_CONTEXT.md`（§4.3 锁纪律、§6 设计决定、§7 已知问题、§9.1 动手之前、§9.2 最容易犯的错）。
> 本文件**只留「不看会静默出错」的硬约束**；过程细节看 `memory/YYYY-MM-DD.md` 与 `.workbuddy/_reg_summary.txt`。

## ⛔ 硬不变量

1. **`website_key` ≡ `normalize_domain(website)`**（`_check_db_keys.py` 只读守）。判跳过 `db_has_customer()` 只查 `website_key`；upsert 是「按键查不到→按 email 兜底合并」。键错位 → 该网址永久被判「新客户」：每采一次多一行、库里始终一条。修：upsert 合并时键自愈 + `db_fix_website_keys(apply=)` 修存量。
2. **结果 Excel 10 列硬契约**（列名列序不可改）：`公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家`。飞书 `build_feishu_records` 与 `init_customer_db` 按**下标**读。
3. **`ui/page.html` 有 sha256 基线**（`_check_page.py` 的 `_TMPL_SHA` + `_BUILT_SHA`，两条都要对）；故意改必须**一起**重算。副页面 `/manual` `/db` 的 `<style>` 由 `PAGE_CSS_PLACEHOLDER` 从它注入 → 加规则连带影响三个页面；本页专有样式写副页面自带第二个 `<style>`。
4. **查询导出必须落 `output/查询导出/`**。`find_latest_result()` 只 glob `output/` 一层、按文件名 8 位日期筛 → 查询导出表名带日期，落根下会劫持飞书导出目标。

## ⚠️ 锁纪律（踩过 2 次死锁）

`STATE_LOCK` 非可重入，`log()` 内部也要抢 → **任何 `log()` 必须在 `with STATE_LOCK` 外调；DB / 文件 IO 一律锁外。** 四段式（样板 `api_manual_session_delete`）：①锁内定位 ②锁外备份+IO ③锁内改内存 ④锁外 log。
查询 / 导出 / 删除链路**完全不碰** `STATE_LOCK` / `STATE` / `paths.ENRICH_FILE`；导出另用 `EXCEL_LOCK`。⚠️ `/api/db/delete` 不能持锁（`backup_db_before_delete()` 内部调 `log()` → 必死锁）；R9 用 **AST 断言**钉住。

## ⚠️ 改完必须「重启 / 重新加载」

- 改 `ui/*.html` → **重启工具**（`PAGE_HTML`/`MANUAL_HTML`/`QUERY_HTML` 在 import 期构建一次）。
- 改 `extension/` → **点「重新加载」**，否则「popup 新 / SW 旧」分裂态（旧 SW 回「未知消息」→ 用户见「0 条」误判失败）。
- 交付新功能要说：旧实例打新路由是 **404**（`curl` 自检）。

## ⚠️ 页面交互（改 `ui/*.html` 三个坑）

- **禁原生 `confirm()`/`alert()`**（贴窗口顶部、样式不可改）→ 用页面自己的居中模态框（`/db` 是 `#delModal`：fixed + flex 居中，Esc/点遮罩=取消，Enter=确定）。R9 断言整页无 `confirm(`（**别把「原生 confirm」写进注释带括号**，会撞红）。⚠️ **例外：`/manual` 那处原生 `confirm`（约 408 行）用户 2026-10-02 拍板不改**。
- ⛔ **JS 要取的 DOM 节点必须放在 `<script>` 之前**（`/db` 是立即执行 IIFE）——否则取到 `null` → 抛错 → `init()` 中断、筛选面板全空白（易误判成后端挂了）。
- **行是 `innerHTML` 整表重画 → 行内按钮必须事件委托**（`#resBody` 上挂 `click`/`change`）。

## ⚠️ 打桩 / 回归纪律

- 全量 `_run_all_reg.py` **23 项**。
- 子模块间必须 `模块.函数()`；smoke 必须有 `m.db.db_path = m.db_path` + `_under_tmp()` 护栏。打桩临时库**必须同时打桩 `paths.ENRICH_FILE`**。
- **禁止并行 Edit 同一文件**。
- **只有两项刻意扫真实库**：`_check_db_keys.py`（只读）与 `补历史欠账.py --dry`；其余打临时目录 → 红了多半是真实数据要人工修。
- ⚠️ **别拿固定数字当基线**（用户在持续采）。有效复核 = 按 source 分布 + 查测试域名残留。
- ⚠️ **回归脚本脆弱点**（假红非产品 bug）：① 别把换端口原因写死 `'10013'`；② 别只 sleep 等 async → 轮询；③ 真机截图只是证据 → `try/except`；④ `_smoke_ext_live` 两遍共用 `core.db` → 时间戳清零；⑤ `<select>` 赋不存在的 value 被忽略 → `createElement('option')`；⑥ `send_file` 持句柄 → 删前 `dl.close()`；⑦ 别拿上一段页面状态当起点；⑧ 断言里行名/数量动态取；⑨ **临时库默认落系统盘 `C:`** → `C:` 满时 SQLite 报 `disk I/O error`/`disk full`/`readonly`，**一批 DB 项集体假红**（2026-10-02 六项齐红）。已把 `TMPDIR/TEMP/TMP` 钉到 `.workbuddy/_reg_tmp`（项目盘）。**红了先看错误类型：disk/readonly/I-O → 先查磁盘空间。**
- ⚠️ 静态断言看**代码**不看源码文本：用 `ast` 走 `ast.Name`/`ast.Attribute`。
- ⚠️ `_check_ext.py` C 组：`PREFERRED_PORTS` 必须逐字等于 `extension/ports.js` 的 `DP_PREFERRED_PORTS`。
- ⚠️ `_smoke_ext_live.py` 走真 Chrome + 真 Flask、**会真写库** → 靠 `DP_SHADOW_PORTS` 遮蔽；跑全量前先关工具。
- ⚠️ `_check_page.py` R4 是字符串 glue 断言：`'from core.ui import PAGE_HTML, _build_page'` 必须单独一行。`_check_query_ui` 样本要留一条无行业/无评分（「未填写」哨兵才出现）。
- ⚠️ `_smoke_ext_popup.js` DOM 桩很薄：`El` 无 `dataset/classList/createElement/closest/matches`，`document` 只有 `getElementById`，`emit(type)` 不带 `target`，`confirm` 由 `CONFIRM_RETURN` 控。

## ⚠️ 采集即落库 → 删除必须双删

`_commit_candidate` 采集那刻就写 SQLite；「本轮明细」只是内存清单。**只删明细是假删除**（库里还在 → 下次判「已在客户库」跳过 → 永远采不回来 → 飞书仍带它）。
- 按 **`rid`** 定位（`session_rid_seq`），不按 url。
- `/db` 按**主键 `id`** 删 → `db_delete_customers_by_ids(ids)` 返回 `(删除数, 没找到的 id)`。单行 ✕ 与批量走**同一条**接口。
- `backup_db_before_delete()`：**必须 sqlite3 在线 `backup()`；禁 `shutil.copy2`**（WAL 漏 `-wal`）；300 秒节流；失败不阻断。目录由 `db_path()` 推导。
- 两条删除路都必须挡空输入（`''`/`[]`/`None`/非法 → **返回 0**，绝不退化成 `DELETE FROM customers`）；都**不做 email 兜底**。
- ⚠️ `/db` 删除**不动 `MANUAL_STATE` 内存明细**（要一并拿掉回 `/manual` 点 ✕）。

## ⛔ 「已采 N 条」≠「结果 Excel 行数」

明细行数 = **新增 + 已在库**（老客户留灰字痕）；Excel **只写新增**。三处拆开报：`ui/manual.html` 状态行 + `sessionFile`、`extension/popup.js` 状态行 + 结果行；徽章保持「N 条」但挂 `title` 写算式。函数 `breakdownText(st,n)` / `roundTally(st)`（`roundTally` 只在 `!session_active` 时返回）。

## ⛔ 自定义搜索词 = 完全原样（主页第 6 卡 / `run_search(raw_queries=…)`）

用户手写完整谷歌查询，**一个字符都不加**，且**不做中国商家过滤**（`custom_mode` → `china_filters = set()`）；与标准模式**互斥**。国家不进搜索词。不看会静默出错的四点：
- **三处校验一起放宽**：前端 `start()` 的 `!products.trim()` 与 `!conditions.length`、后端 `api_start` 的 `if not products`。
- **`cond_list` 必须给占位模板** `[('自定义', '{p}')]`（留空 → 内层永不进入 → 静默跑 0 条）。
- **预览 `renderCombos()` 必须同步切分支**。
- ⚠️ 「不过滤」只关那 17 项中国过滤 —— `is_blocked()` 平台黑名单**仍生效**。只服务网页搜索：切地图时置灰 + `api_start` 忽略。

## ⛔ 国家限定（`country_limit` 四选一，本轮新增）

- 主页第 4 步卡 `#countryLimit`：`none`(默认)/`cr`/`site`/`both`。**默认关，行为与旧版一字不差**。
- `cr=countryXX`（**大写 ISO**）只挂 URL；`site:.xx` 只进搜索词；都与 `&gl=&hl=` 并联。
- 数据层 `core/config.py`：`COUNTRY_LIMITS{code:(cr,site)}` + `_MODES` + `_DEFAULT='none'`，**独立字典**（不动 `COUNTRIES` 4 元组）；前端经 `COUNTRY_LIMITS_PLACEHOLDER` 注入。
- 特殊值：美国 site 留空（`.com` 为主）；伊朗 cr 留空（不在谷歌 cr 列表）；`ca_fr`→`countryCA`；英国 `countryGB` **待实测**。
- **互斥**：`custom_mode` → 强制 `none`；地图模式整块收起 + `api_start` 忽略。
- 2026-09-28 实测：法国加 `cr` 后 10→7 条、真客户被挤掉 → 默认关。**限定更严 ≠ 更准。**
- `site:.uk` **能**匹配 `.co.uk`。已知限制：`open_search` 兜底轮 `type_search` 不带 `country_params` → **cr 会丢**（site 不丢）；`site:` 与领英条件**互斥**。

## ⛔ 产物目录默认不读（用户明确要求）

`output/`（结果表 / 查询导出）与 `DB/backups/`（库快照）是**运行产物**，内容随时在变、用户自己也在清。→ **清单/条数可以瞄，内容一律不读、不比对、不追查「少了几份」**。只有用户点名才读。

## 关键约定速查

- 库 `DB/客户库.sqlite3`（表 `customers`，WAL）；备份 `DB/backups/`。结果 Excel 落 `output/` 根，查询导出落 `output/查询导出/`。`find_latest_result()` 从**文件名解析时间**；`ts_result_path()`/`ts_query_export_path()` 自带 `_2/_3` 去重。
- 查询空值哨兵 `QUERY_EMPTY='__empty__'`：前端 `const EMPTY` 与后端必须**一字不差**。筛选选项一律由 `db_facet_counts()` 读真实库 distinct 生成、**页面零硬编码行业名**。
- ⚠️ 拆包遗留：入口**只许绝对导入** + `sys.path` 自举 3 行，搬走的名字要在入口**同名 re-export**；`_app_dir()` **不许**写 `dirname(abspath(__file__))`（否则静默换空库）；`ENRICH_FILE` 是唯一被重新赋值的模块级变量（内部一律 `paths.ENRICH_FILE`）。
- ⚠️ `.workbuddy/` 与程序零耦合。**别删**：`memory/*`、`_todo.json`、`_fail_q1_p0.png`、回归脚本、两个 `_*_before.json`。
- ⚠️ `.gitignore` 是**白名单式**：`.workbuddy/_*` 全排除再 `!` 逐条放行 → 新增回归脚本要确认被 `!` 覆盖（`??` = 已放行）。`*.log`、`output/查询导出/` 也排除。
- 词库字节约定：UTF-8 无 BOM / **纯 CRLF** / 2 空格缩进 / 末尾无换行；`json.dumps(indent=2, ensure_ascii=False)` 出 LF → 必须 `replace('\n','\r\n')` 后**二进制写**。三级下拉顺序 = `sorted(keys)`。脚本：`补历史欠账.py`(--dry) / `同步数据库到飞书.py`(--dry-run) / `回填行业.py` / `重标行业.py` / `标注空行业.py`（后两个默认只报告，`--apply` 才写）。

## git / 远端

- `main` 版本 V1.0–**V1.4**（`-a -m` 附注标签）。⚠️ V1.4 起**不往本文件写提交 hash** → 一律 `git rev-parse "V1.4^{commit}"`。
- 远端 = public（用户知情）：`origin=https://github.com/jurryzhang66/waimao.git`；身份 `jurryzhang66 <jurryzhang66@users.noreply.github.com>`。`git push origin main --tags`；凭据 `helper-selector`(GCM)。
- ⛔⛔ 公开仓库既成事实：含 ① `DB/客户库.sqlite3` 真实客户 ② `output/` 结果表 ③ `DB/backups/` ④ **飞书 BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`**。收口只能 `git filter-repo` + 强推 + 轮换 token。

## 飞书 / 词库 / 搜索 / 地图 / 扩展（只记最致命的）

- **飞书**：BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`、表 `客户信息` `tblY38YnVIQ5AYYA`（CLI 路径见档案 §9.4）。坑：调用前 `pop('HERMES_HOME')`；`--limit` 上限 200、翻页 `--offset`；**字段名就叫 `官网`**；`邮箱` 只收单个合规邮箱；select 用数组；本地「沙特」→飞书「沙特阿拉伯」；`+field-update` 是**全量 PUT**。`来源渠道` 三值，结果 Excel **无来源列** → `build_feishu_records()` 按 domain 回库查来源；**50 分门槛对 `[手动采集]` 豁免**。
- **词库**：8 行业 / 14 品类 / 40 产品 / 126 词条、9 语言；`cond_template(key, lang)` 是**唯一出口**，优先级 `#kwLang` → 该国 `hl` → `en`。⚠️ 模板 `{p}` **别加引号**；含 OR 的模板**必须用括号锁同义词组**。⚠️ `COUNTRIES` 是 **4 元组**、前端按 **5 元组**注入，改长度炸两处；国家筛选走 URL `&gl=&hl=`，**不写进搜索词**。改库后跑 `_kwlib_check.py`。
- **搜索**：判渲染 `RESULT_LINK_CSS='css:a:has(h3)'`，开页必须走 `open_search()`。结果链接是跳转链 → `resolve_goto()`；判跳转必须用 `_is_search_engine_url()`（硬编码 `google.com/goto` 在 `.com.hk` 上会一页 10 条全丢）。⛔「补全联系方式+评分」按钮已删，但 `enrich_core`/`_enrich_worklist`/`enrich()`/`_save_enrich_excel` 必须保留。⚠️ `enrich()` 用 `page.new_tab()`、`open_search` 用 `page.get()` → 补全后必须 `_back_to_search()`；`ChromiumTab` **没有 `new_tab()`**。限流连返壳 → 等 **90 秒**。
- **地图 / 扩展**（细节见档案 M2/M5）：地图滚 `div[role="feed"]` **本身不是 window**、`maps_detail` **直接导航 place URL**、**身份词必须拼进查询词**（`maps_role_word`）否则只返回餐馆、`run_maps` 在 `china_filter_reasons()` **之前**并入地图电话；扩展 `background.js` 是**唯一 fetch 出口**（`popup.js` 里 `fetch(` 必须为 **0**）、悬浮按钮用 Shadow DOM(closed)、CORS 只回显 `chrome-extension://`（**绝不 `*`**）、`finishSession()` 末尾必然 `refreshSession()`。

## 本机环境

- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c`；**别从 Bash 里 invoke PowerShell**。`wmic` 被屏蔽 → `Get-CimInstance Win32_Process`。
- ⚠️ TCP 保留段（Hyper-V/WinNAT）**每次开机漂移** → 端口自动避让，**别把「某端口被保留」写进断言**；5000/8000 常被圈走 → 以日志打印的真实地址为准。
- 删文件进回收站：`ctypes` 调 `SHFileOperationW`；**返回非 0 也可能已成功，必须 `os.path.exists()` 复查**。
- ⚠️ 系统盘 `C:` 空间紧张（2026-10-02 只剩 2.34G）→ 回归临时目录已钉到 D:（见上）。

## 数据质量待办（全清单见档案 §7）

- ⛔ **评分在非英语场景方向是反的**（法国结果实锤，未修）：`CTYPE_WORDS` 全英文、`score_item()` **只有加分无减分**；`PRODUCT_WORDS` 写死猫砂垫且**子串匹配无词边界**。
- 平台垃圾域名约 25~38 条未清（可 `/db` 筛出勾删）；`重标行业.py` dry-run 待改 **23 条**（家具家居 18 / 汽配 5），**尚未 `--apply`**。
- ✅ **行业为空已清零**（2026-10-02）：先删 7 条平台页/误采 → 310→303；再把剩余 17 条标「食品」。⚠️ 顺序不能反（脚本按「行业为空」取数）。
- 其余未拍板：半自动/纯手工单选、冷会话首请求降级修法、飞书 16 条垃圾待删、id=154 淘宝记录、阶段 B 拆包、**最近八轮改动尚未 git commit（V1.5 待拍板）**。
- ✅ 已拍板（别再当待办）：`/manual` 原生 `confirm` 保留不改；`DB/backups/` 少掉的几份 + `关键词库.json.bak*` 是用户自己删的，不恢复、不排查。
