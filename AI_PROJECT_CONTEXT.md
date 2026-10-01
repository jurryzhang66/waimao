# AI_PROJECT_CONTEXT.md — 谷歌外贸客户开发工具

> **这份文件的用途**：让 AI 在几秒内恢复本项目上下文，然后**按需定位**到相关代码，只读必要的源文件。
> 它**不是**项目说明书，也**不替代**源代码 —— 具体实现细节、边界条件、锁顺序，一律以源码和源码注释为准。
>
> **阅读顺序建议**：本文件 → 目标模块对应的源文件 → 该文件顶部的模块 docstring（本项目注释密度极高，坑都写在注释里）。
>
> 生成时间：2026-10-01 ｜ 对应版本：V1.4（git 附注标签 `V1.4`）｜ 校验方式：逐文件实读，未猜测

---

## 1. 项目概况

### 1.1 项目用途

一个**纯本地运行**的谷歌外贸客户开发工具。用户是外贸业务方，要在目标国家批量找到潜在买家（批发商 / 进口商 / 品牌方 / 零售商），拿到他们的官网、邮箱、电话，打分筛选后导入飞书多维表格跟进。

### 1.2 主要解决什么问题

| 痛点 | 本工具的解法 |
|---|---|
| 手工在谷歌逐个搜索、翻页、抄网址 | 自动按「产品词 × 搜索条件 × 国家」批量跑搜索，自动翻页 |
| 搜到网址后还要一个个点开找邮箱电话 | **搜到即就地补全**：访问该站抓邮箱/电话/联系页 |
| 不知道哪家值得跟 | 自动评分（满分 90）+ 分级（重点客户 / 普通客户 / 观察） |
| 联系方式散落在 Excel 里，重复劳动多 | 统一进 SQLite 客户库，按域名去重，每轮产出一份结果 Excel |
| 手工往飞书里录 | 一键导出到飞书多维表格（经 `lark-cli`） |
| 在浏览网页时看到好客户，但要切回工具手动录 | Chrome 扩展：网页上一键「采集本页」 |
| 谷歌搜索搜不到「只有实体店没有官网」的本地商家 | 第二条链路：谷歌地图名录采集 |

### 1.3 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 运行时 | Python 3.13 | 解释器路径见「本机环境」 |
| Web 服务 | Flask | 本地 `127.0.0.1`，端口运行时实测挑选 |
| 浏览器自动化 | DrissionPage（ChromiumPage） | 驱动独立 Chrome 实例，不依赖用户已开的 9222 |
| 数据库 | SQLite（标准库 `sqlite3`） | WAL 模式，单文件 `DB/客户库.sqlite3` |
| Excel | openpyxl | 结果文件读写 |
| HTTP 抓取（轻量） | `requests` | 手动采集第②级；软导入，缺了也能跑 |
| 前端 | **裸 HTML + 原生 JS，无框架、无构建** | 两个页面由 Python 在 import 期读文件 + 注入 JSON |
| 浏览器扩展 | Chrome MV3（Service Worker + content script） | 无打包工具，纯手写 |
| 飞书接入 | `lark-cli.exe` 子进程调用 | 非 HTTP SDK，走命令行 |
| 版本控制 | git（本地 + GitHub 远端） | 标签全部是附注标签 |

**运行依赖**：`Flask`、`DrissionPage`、`openpyxl`（`requests` 随 DrissionPage 一起来）。

### 1.4 当前项目处于什么阶段

**已投产自用、持续迭代的成熟单机工具**（不是原型，也不是要发布的产品）。

- 三条采集链路（网页搜索 / 地图名录 / 手动采集 + 扩展）全部跑通并各有回归脚本守着。
- 已拆包成「入口 + `core/` 包 + `ui/` 模板」，三个页面（主页 / 手动采集 / 客户库查询）共用一份 CSS。
- 有 **22 项自动化回归**（`.workbuddy/_run_all_reg.py`），改代码后必须全绿。
- 真实客户库已积累 **306 条**（有邮箱 200 / 有电话 100），用户在日常使用中（数字一直在涨）。
- 代码已提交并推送到 GitHub：`https://github.com/jurryzhang66/waimao`（**public**，用户知情同意，见 §6.9 风险提示）。
- **未提交的工作区改动**：最近四轮（计数口径拆分 + 去重键不变量；客户库查询页 `/db`；扩展面板入口；主页顶栏导航）尚未 commit。

---

## 2. 项目结构

只列出**有实际意义的**目录、模块与核心文件。

```
D:\waimao\dp\
├── 客户开发工具.py          ★ 唯一入口：Flask app + 三条采集链路 + 补全/评分/落盘/飞书 + re-export
├── 启动客户开发工具.bat       双击启动（实际就是 python 客户开发工具.py）
├── 关键词库.json             ★ 行业→品类→产品→多语言词条（8 行业/14 品类/40 产品/126 词条）
│   └── 关键词库.json.bak{,2,3} 历史备份（人工留档，程序不读）
├── core/                    ★ 从入口拆出的 5 个模块（零环依赖，分层严格）
│   ├── config.py              可配置常量：搜索条件 / 角色词本地化 / 国家表 / 黑名单 / 中国过滤
│   ├── paths.py               项目根定位、output 目录、结果文件命名、最新结果查找、ENRICH_FILE
│   ├── state.py               飞书配置 + 全局运行状态 STATE/MANUAL_STATE + 锁 + log()
│   ├── db.py                  SQLite：建表 / 去重键 / upsert / 统计 / 键修复 / 删除+备份 / **分页查询+分面统计**
│   └── ui.py                  页面模板加载与占位符注入（构建 PAGE_HTML / MANUAL_HTML / QUERY_HTML）
├── ui/
│   ├── page.html            ★ 主界面模板（651 行，含顶栏导航）。**sha256 有基线（R5），故意改要同步重算**
│   ├── manual.html          ★ 手动采集页模板（426 行），复用 page.html 的 <style> 块
│   └── query.html           ★ 客户库查询页模板，同样复用 page.html 的 <style> 块
├── extension/               ★ Chrome MV3 扩展（「外贸客户采集助手」）
│   ├── manifest.json          权限仅 activeTab/scripting/contextMenus/storage
│   ├── background.js        ★ Service Worker：**全扩展唯一 fetch 出口** + 消息路由
│   ├── ports.js                端口候选表 + 身份常量（必须与入口 PREFERRED_PORTS 一致）
│   ├── content.js              内容脚本：悬浮按钮 + 右键菜单采集
│   ├── floating-css.js         悬浮按钮样式（以 JS 字符串形式提供，非 .css 文件）
│   ├── popup.html/.js/.css     工具栏弹窗：连接状态 + 采集 + 本轮明细 + 逐行删除
│   ├── options.html/.js/.css   设置页：端口探测/固定、默认选项
│   └── README.md               扩展的安装/入口/权限/技术点/FAQ（186 行，写得比代码还细）
├── DB/
│   ├── 客户库.sqlite3       ★ 唯一数据库（WAL）→ 表 customers
│   └── backups/              一致性快照（清理前/污染前/删除前/修键前，人工与程序共用此目录）
├── output/                  ★ 每轮一份结果 Excel：行业-YYYYMMDD_HHMM-主国家.xlsx（现存 20 份）
│   └── 查询导出/            ★ /db 页导出的 Excel 落这里（**子目录，gitignore**；绝不能落上一层）
├── import_records.json        导出飞书时的临时 payload（运行时生成）
├── import_records_sync.json   同步脚本用的临时 payload
│
├── 补历史欠账.py              CLI：批量补全库里「邮箱电话都为空」的历史欠账（--dry 只列不跑）
├── 回填行业.py                CLI：按规则判断行业，回填本地库 + 飞书（行业口径的**唯一权威**）
├── 重标行业.py                CLI：把历史行业旧口径改成规范名（默认 dry-run，--apply 才写）
├── 同步数据库到飞书.py         CLI：把 SQLite 全量缺失记录同步到飞书（--dry-run 预演）
├── demo.py                    诊断脚本：检查 PyCharm 环境与浏览器能否启动
├── gen_import.py              一次性脚本：从旧 Excel 生成飞书导入 JSON（历史遗留）
│
├── 客户库字段说明.md          字段契约文档（字段含义 / 去重规则 / 评分解释）
├── 谷歌外贸客户开发搜索技巧手册.md  业务手册（搜索运算符 / 分国家策略 / 邮件合规 / 30 天计划）
├── AI_PROJECT_CONTEXT.md      ★ 本文档：项目地图
│
└── .workbuddy/              ⚠️ 与程序**零耦合**（代码里引用 0 处），但是改代码的安全网
    ├── _run_all_reg.py        全量回归驱动（22 项，逐项写 _reg__<名字>.log）
    ├── _check_*.py            静态/单测类校验（页面、启动、扩展、词库、行业规则、飞书记录、真实库键、查询页真机）
    ├── _smoke_*.py / .js      运行时冒烟（搜索/地图/采集/本轮会话/客户库查询/扩展内容脚本/扩展 popup/端到端联调）
    ├── _kwlib_before.json     词库回归的 deep-diff 基准（脚本依赖，**不能删**）
    ├── _industry_pred_before.json  行业规则回归的基准（脚本依赖，**不能删**）
    ├── _reg_summary.txt       每次全量回归的验收记录（结论 + 真实库复核 + 测试域名清单）
    ├── _baseline_v13.json / _todo.json / _fail_q1_p0.png   历史基线、待办、故障取证图
    ├── memory/               ★ MEMORY.md（长期项目知识）+ YYYY-MM-DD.md（每日工作日志）
    └── 大量 _*.png / _*.log / _*.txt   运行时产物与一次性探针（不进 git）
```

**不参与运行时但**别删**的东西**：`memory/`、`_todo.json`、`_fail_q1_p0.png`、所有 `_check_*`/`_smoke_*`/`_kwlib_*`/`_verify_*` 脚本、两个 `_*_before.json` 基准。

---

## 3. 功能模块

按**功能**划分（不是按文件夹）。每个模块给出：作用 / 位置 / 核心文件 / 实现方法 / 与其他模块的关系 / 依赖 / 可复用性 / 状态 / 注意。

---

### M1. 谷歌网页搜索采集

- **功能作用**：按「产品词 × 搜索条件 × 国家」批量跑谷歌搜索，翻页取结果，逐条过滤后交给补全模块。
- **所在位置**：`客户开发工具.py` 第 134–517 行（搜索核心）+ 第 1177–1391 行（`run_search` 后台任务）
- **核心文件**：`客户开发工具.py`；依赖 `core/config.py`（条件模板、国家表、黑名单）
- **实现方法**：
  1. 组装查询词：`cond_template(key, lang)` 给出公式骨架 → 用 `pq_list` 替换 `{p}` → 拼上排除词与中国过滤词。
  2. `open_search()` 打开搜索页，**内置多轮重开**专治谷歌返回「壳页面」（前 2 轮直连 `/search?q=`，第 3 轮走搜索框兜底）。
  3. `extract_results()` 抽结果（判据 `RESULT_LINK_CSS = 'css:a:has(h3)'`），结果链接是跳转链，必须 `resolve_goto()` 还原真域名。
  4. 逐条：`enrich()` 就地抓联系方式 → `china_filter_reasons()` 中国信号过滤 → `db_upsert_customer()` 登记 → 评分 → 再 upsert 回填 → 追加 `all_rows`。
  5. 凑够 `target_count` 个**新增网站**即停；`finally` 里 `page.quit()` 后落盘（中途停止也不白跑）。
- **与其他模块的关系**：产出喂给 M6（客户库）、M3（补全评分）、M7（结果 Excel）。与 M2 并列，互不调用。
- **依赖**：DrissionPage、`core/config`、`core/db`、`core/state`、`core/paths`
- **是否可复用**：搜索核心的**单个环节**（翻页、跳转链还原、壳页面重试、结果抽取）都能独立复用；整条 `run_search` 与业务强绑定。
- **当前完成状态**：✅ 已投产
- **修改时注意**：
  - ⚠️ 这是**跑通的链路**，项目既有约定是「不动跑通的链路」。改动前先看 `_smoke_search.py` 的断言。
  - ⚠️ 结果没渲染有两种成因（壳页面 / 谷歌零结果页），**日志分不开**，别急着当 bug 修（见 §7）。
  - ⚠️ 谷歌限流时会连返壳页面 → 三次重试失败跳页 → **等 90 秒**才恢复。

---

### M2. 谷歌地图名录采集

- **功能作用**：从谷歌地图搜索结果里抓「有实体地址的真实商家」（含电话/地址/官网），拿到网页搜索搜不到的本地客户。
- **所在位置**：`客户开发工具.py` 第 687–706 行（常量）+ 第 978–1175 行（地图工具函数）+ 第 1408–1625 行（`run_maps`）
- **核心文件**：`客户开发工具.py`
- **实现方法**：
  1. 查询词 = 产品词 + **身份词**（`maps_role_word()`，否则只返回餐馆/零售店）+ 城市名（可选）。
  2. 定位靠 URL 里的 `@lat,lng,zoom` 视野（`COUNTRY_CENTERS` 25 国坐标）；结果受**出口 IP 所在地**影响。
  3. 滚 `div[role="feed"]` 本身（**不是滚 window**）加载更多卡片；单次搜索硬上限约 120 条，出现「…the end of the list」（多语言 8 种文案）就收手。
  4. 逐条：`maps_detail()` **直接导航到 place URL** 读详情面板（`data-item-id` 三件套：`phone:tel:` / `authority` / `address`）。
  5. 去重键用 `maps_place_key()` 抓 `!1s0x…:0x…` 十六进制段（无官网的商家也有稳定键）。
  6. 老客户在「点详情 + 访问官网」**之前**就 `db_has_customer()` 跳过，省掉最贵的两步。
- **与其他模块的关系**：与 M1 并列的第二条链路，共用 M3 评分、M6 客户库、M7 结果 Excel。
- **依赖**：同 M1
- **是否可复用**：地图 DOM 交互工具（`maps_*` 系列）与业务解耦，可复用。
- **当前完成状态**：✅ 已投产（产出较少，共 7 条）
- **修改时注意**：
  - ⚠️ `maps_detail` **必须直接导航**到 place URL，不能「点开卡片」——点开后列表被详情替换，其余句柄会 `NoRectError`。
  - ⚠️ 身份词必须拼进查询词，这是实测结论。
  - ⚠️ `run_maps` 在 `china_filter_reasons()` **之前**就把「地图电话并入官网电话」了，合并时机一变，中国过滤的入参就变，smoke 可能仍绿而真机行为已改。

---

### M3. 联系方式补全与评分

- **功能作用**：访问客户官网，抽取邮箱/电话/联系页；按规则打分并分级。
- **所在位置**：`客户开发工具.py` 第 518–685 行（正则、`clean_emails/clean_phones`、`enrich`、`score_item`、`rating`）+ 第 1626–1660 行（`_enrich_worklist`）+ 第 1845–1898 行（`enrich_core`）
- **核心文件**：`客户开发工具.py`
- **实现方法**：
  - `enrich(page, url)`：`page.new_tab()` 开临时标签 → `tab.html` 跑正则 → 没邮箱就试 `CONTACT_PATHS` 前两个 → 收尾关标签。**必须**用 `_back_to_search(page, tab_id)` 切回搜索主标签，否则下一步导航会落到客户站。
  - `clean_emails` 过滤噪声域（wixpress/shopify/schema.org…），每站最多留 3 个。
  - `score_item`：邮箱 +30 / 电话 +15 / 联系页 +10 / 客户身份词（`CTYPE_WORDS`）+25 / 产品词 +10 / 非博客页 +10，满分 90。
  - `rating`：≥70 重点客户，≥50 普通客户，否则观察。
  - `enrich_core`：批处理历史欠账，入口是 CLI `补历史欠账.py`。
- **与其他模块的关系**：被 M1/M2（就地补全）、M4（第③级升级）、CLI 脚本共同调用，是**共用能力**。
- **依赖**：DrissionPage、`requests`（软导入）
- **是否可复用**：✅ 高。正则、噪声域表、`enrich` 的抓取策略、评分骨架都可直接搬。
- **当前完成状态**：✅ 已投产；⚠️ 评分口径有已知缺陷（见 §7）
- **修改时注意**：
  - ⚠️ `PRODUCT_WORDS` 是**写死的猫砂垫词表**，`score_item` 已开可选入参 `product_words`（传了就按传入算，不传保持旧行为）。自动链路暂时不传，手动采集会传。
  - ⚠️ `enrich()` 用 `page.new_tab()`，而 `open_search` 用 `page.get()` —— 混用时标签页会串（本项目踩过）。
  - ⚠️ 按钮「补全联系方式+评分」**已从界面删除**，但 `enrich_core` / `_enrich_worklist` / `enrich()` / `_save_enrich_excel` **必须保留**（脚本与搜索链路在用）。

---

### M4. 手动采集（工具页 + 三级抓取 + 本轮会话）

- **功能作用**：用户在任意网页上看到好客户，一键采集入库；也可在 `/manual` 页粘贴一批网址批量跑。采集以「本轮」为单位攒着，结束时一次性落成一份结果 Excel。
- **所在位置**：
  - 模板：`ui/manual.html`
  - 业务函数：`客户开发工具.py` 第 530–977 行（清洗/抽联系方式/`collect_from_html`/常驻浏览器/本轮会话）
  - 落盘：第 1793–1842 行（`_flush_manual_session`）
  - 路由：第 2109–2330 行（`/api/collect`、`/api/manual/*`）
- **核心文件**：`ui/manual.html`、`客户开发工具.py`
- **实现方法**：
  - **三级抓取**（前一级拿不到邮箱才进下一级）：
    ① 秒级 —— 扩展送来的当前页 HTML 直接跑正则（不开浏览器）
    ② 联系页 —— `requests` 抓页面自带的 contact 链接（找不到才按 `CONTACT_PATHS` 猜）
    ③ 升级 —— 开 Chromium 跑完整 `enrich()`（3–10s，含 JS 渲染与反爬绕过）
  - 收尾统一走 `_commit_candidate()`（评分 → `db_upsert_customer` → 返回 11 键行）。
  - **采集即落库**：`_commit_candidate` 当场写 SQLite；「本轮明细」只是内存清单，决定 Excel 有哪些行。
  - **本轮会话语义**：`session_active / session_rid_seq / session_rows / added / existed / failed / upgraded`。点「开始本轮」开轮；**扩展单点若本轮未开，自动替用户开轮**（`_ensure_manual_session`）；口径（行业/国家）只在开轮那一刻记下。
  - 结束：`_flush_manual_session()` → `_save_enrich_excel()` **新建**一份结果文件并成为「最新结果文件」；**空轮不落盘**；**失败保留数据**可一键重试。
  - 批量任务（`/api/manual/batch`）是**本轮内的一个可选子过程**，单线程串行；批量还在跑时点「结束」只置挂起标志，由 worker 的 `finally` 收尾落盘。
  - **逐行删除**（✕）：`POST /api/manual/session/delete`，按 `rid` 定位，**明细 + 客户库双删**，删前自动备份。
- **与其他模块的关系**：喂给 M6（客户库）、M7（结果 Excel）、M8（飞书）；被 M5（扩展）调用。
- **依赖**：Flask、`requests`、DrissionPage（第③级）、`core/state.MANUAL_STATE`
- **是否可复用**：✅ 高 —— 「三级抓取」的降级策略、「本轮会话」的攒批+一次性落盘模式、「删除双删+删前备份」的骨架都可复用。
- **当前完成状态**：✅ 已投产（最活跃的一路，库内 69 条手动采集）
- **修改时注意**（本节是全项目坑最密的地方）：
  - ⚠️⚠️ **`log()` 内部会抢 `STATE_LOCK`（非可重入）→ 任何 `log` 必须在 `with STATE_LOCK` 块外调；DB 与文件 IO 一律锁外**。历史踩过 2 次死锁。删除路由的骨架就是这条纪律的样板（①锁内定位 ②锁外备份+删库 ③锁内改内存 ④锁外 log）。
  - ⚠️⚠️ **「已采 N 条」≠「结果 Excel 行数」**：明细行数 = 新增 + 已在库（老客户也留一行灰字痕），而 Excel **只写新增**。三处 UI 都必须把两个口径一起报出来（`已采 17 条 · 新增 13 · 已在库 4`）。这是用户明确反馈过的问题。
  - ⚠️ 删除必须**双删**：只删明细是假删除（库里那条还在 → 下次采到同站判「已在客户库」跳过 → 永远采不回来 → 飞书仍带它）。
  - ⚠️ 删除按 **`rid`** 定位，不能按 url（同一 url 在一轮里可能既有 `added` 又有 `existed`）。
  - ⚠️ `MANUAL_STATE` 是**独立状态**，绝不复用 `STATE['stop']`（会把自动搜索一起杀掉）。
  - ⚠️ `MAX_CONTENT_LENGTH = 2MB`（扩展会送整页 HTML）。

---

### M5. Chrome 扩展（MV3）

- **功能作用**：在浏览任意网页时，一键把当前页（网址 + 标题 + 整页 HTML）送进本机工具；也能从 popup 看本轮明细、逐行删除、结束本轮。
- **所在位置**：`extension/`（12 个文件）
- **核心文件**：`manifest.json`、`background.js`（唯一 fetch 出口 + 消息路由）、`ports.js`（端口表 + 身份常量）、`content.js`、`popup.*`、`options.*`、`floating-css.js`
- **实现方法**：
  - **所有 `fetch` 只能由 service worker 发**：`popup.js` 里 `fetch(` 出现次数必须为 **0**（回归脚本硬断言），一律 `chrome.runtime.sendMessage` → `background.js` 代发。
  - 端口发现：按 `DP_PREFERRED_PORTS` 逐个并行探 `/api/ping`，只有 `ok && app === 'waimao-dp'` 才认（防误连本机别的服务）。优先级：用户手填 → 上次缓存 → 候选表。
  - CORS：工具侧只对 `chrome-extension://` 回显 ACAO（**绝不 `*`**）+ 要求自定义头 `X-DP-Ext: 1`（必触发预检）。
  - 悬浮按钮：**Shadow DOM(closed) + `adoptedStyleSheets`**（构造式样式表）。因为 manifest 的 `.css` 跨不过 shadow 边界，而插进页面的 `<style>` 会被严格 CSP 拦掉。
  - 权限最小化：仅 `activeTab / scripting / contextMenus / storage`；host 只给 `127.0.0.1` + `localhost`。
  - 消息：`DP_PING / DP_STATE / DP_SETTINGS_GET|SET / DP_KEYWORDS / DP_URLS / DP_FORGET_PORT / DP_COLLECT_TAB / DP_COLLECT_PAYLOAD / DP_MANUAL_STATE / DP_SESSION_FINISH / DP_SESSION_DELETE / DP_RECOLLECT_URL`。
  - popup 底部链接区（`.foot`，`flex-wrap`）：手动采集页 / 自动搜索主页 / **客户库查询页** / 设置 / 重新探测端口。跳页面的三个都先 `send('DP_URLS')` 拿 `{base, manual, home, db}`（端口由端口发现实测，**不写死**），再 `chrome.tabs.create` —— 所以 popup 里依然零 `fetch`。
- **与其他模块的关系**：调用 M4（`/api/collect`、`/api/manual/*`）；`ports.js` 与入口 `PREFERRED_PORTS` **必须两边一致**（回归 `_check_ext.py` 有硬断言）。
- **依赖**：Chrome MV3、本机工具运行中
- **是否可复用**：✅ **很高** —— 这套模板已抽象成用户级技能 `chrome-ext-local-tool`（见 §5）。
- **当前完成状态**：✅ 已投产（用户日常在用）
- **修改时注意**：
  - ⚠️⚠️ **改 `extension/` 后必须点「重新加载」**，否则出现「popup 是新的、service worker 是旧的」分裂态：新 popup 发 `DP_MANUAL_STATE`，旧 SW 落到 `default:` 回「未知消息：…」，用户看到「0 条」以为采集失败。已固化成 `_smoke_ext_popup.js` 断言。
  - ⚠️ **改 `extension/` 或 `ui/*.html` 后要「重启工具 + 点重新加载」两件事都做**（实测：跑着的旧实例打新路由是 404）。自检口令：`curl` 一下那个新路由，404 = 后端旧代码。
  - ⚠️ 联调前必须遮蔽环境里别的实例（`DP_SHADOW_PORTS`），否则**会把测试假网址真写进真实客户库**（踩过）。
  - ⚠️ `popup.js::finishSession()` 末尾必然 `refreshSession()` → 一次性提示必须写进 `_note` 才留得住（只写 `status` 会被刷新吃掉）。

---

### M6. 客户库（SQLite）

- **功能作用**：全部客户的唯一权威存储，按域名去重，供搜索跳过、导出、统计。
- **所在位置**：`core/db.py`（293 行）+ 库文件 `DB/客户库.sqlite3`
- **核心文件**：`core/db.py`
- **实现方法**：
  - 表 `customers`（21 列，字段含义见 `客户库字段说明.md`），WAL 模式，`website_key UNIQUE`。
  - `normalize_domain(url)` 统一算去重键（去 `www.`、丢端口、地图 place 合成 `maps:0x…` 键、纯邮箱给空键）。
  - `db_upsert_customer(data)`：先按键查 → 查不到再按 `lower(email)` 兜底合并 → 都没有才 INSERT。**空值不覆盖已有有效值**。合并时带**键自愈**（见下）。
  - `db_has_customer(website)`：只查不写，供「要不要跳过老客户」判断。
  - `db_fix_website_keys(apply=False)`：扫描并修正错位键，默认只读 dry-run。
  - `backup_db_before_delete()`：用 **sqlite3 在线 `backup()`** 做一致性备份，300 秒节流，失败不阻断。
  - `db_delete_customer(website)`：按 `website_key` 删一条，**key 为空直接返回 0**，绝不做 email 兜底。
- **与其他模块的关系**：被 M1/M2/M3/M4 写入，被 M7/M8 读取，被 CLI 脚本批量处理。
- **依赖**：`core/paths`、`core/state.log`、openpyxl（仅空库时迁移旧 Excel用）
- **是否可复用**：✅ 高 —— 去重键算法、upsert 合并语义、WAL 安全备份骨架都可直接搬。
- **当前完成状态**：✅ 已投产（306 条）
- **修改时注意**：
  - ⛔ **不变量：`website_key` 恒等于 `normalize_domain(website)`**。回归项 `_check_db_keys.py` 守着它。
    **破了会怎样**：`db_has_customer()`（判断跳过）**只**查 `website_key`，而 `db_upsert_customer()`（写入）是「按键查不到、再按 email 兜底合并」—— 口径本就不一致；键一错位，该网址就**永久**被判「新客户」，每采一次往 Excel 多写一行、库里始终只有一条（实测 `megazone.mx` 在一份表里出现 3 次）。
  - ⚠️ 备份**必须**用 `sqlite3` 在线 `backup()`，**禁止 `shutil.copy2`**（WAL 会漏 `-wal` 里未 checkpoint 的写入）。
  - ⚠️ 备份目录由 `db_path()` 推导（`_backups_dir()`）→ 回归脚本只要打桩了 `core.db.db_path`，备份自动落临时目录。
  - ⚠️ `log` 必须来自 `core.state`（否则与入口循环导入）。

---

### M7. 结果 Excel 落盘

- **功能作用**：每轮采集产出一份带联系方式和评分的客户名单 Excel。
- **所在位置**：`客户开发工具.py` 第 1678–1790 行（`EXCEL_HEADER_10` / `_row10` / `_append_result_row` / `_save_enrich_excel`）；命名与查找在 `core/paths.py`
- **核心文件**：`core/paths.py`、`客户开发工具.py`
- **实现方法**：
  - 命名 `行业-YYYYMMDD_HHMM-主国家.xlsx`，落 `output/`；同分钟重名由 `ts_result_path()` 自动加 `_2/_3`。
  - `_save_enrich_excel()` **每次 `Workbook()` 新建**一份，按评分降序，并把 `paths.ENRICH_FILE` 改指过去（→ 后续飞书导出读这份）。
  - `find_latest_result()` 从**文件名解析时间**排序（不能用字典序，也不信 mtime）。
  - `_append_result_row()` 是「点一下追加一条」的旧实现，**已被本轮会话模式取代、当前无调用方**，但保留（有回归覆盖）。
- **与其他模块的关系**：M1/M2/M3/M4 的最终产物；M8 的输入。
- **依赖**：openpyxl
- **是否可复用**：✅ 高 —— 命名/去重/最新文件查找/降序落盘都可复用。
- **当前完成状态**：✅ 已投产（`output/` 20 份）
- **修改时注意**：
  - ⛔ **10 列硬契约**（顺序与列名一个都不能改）：`公司/页面标题, 网站网址, 邮箱, 电话, 联系页, 评分, 评级, 摘要, 搜索公式, 国家`。飞书导出（`build_feishu_records`）与空库迁移（`init_customer_db`）都按**下标**读。
  - ⚠️ `paths.ENRICH_FILE` 是**全项目唯一会被重新赋值的模块级变量** → 内部一律写 `paths.ENRICH_FILE`，对外靠入口的 PEP 562 `__getattr__` 转发。
  - ⚠️ Excel 被用户打开着会 `PermissionError` → 已有退避重试 + 另存新文件的降级路径，别简化掉。

---

### M8. 飞书导出

- **功能作用**：把最新结果 Excel 里评分合格的行写成飞书多维表格记录。
- **所在位置**：`客户开发工具.py` 第 1901–2026 行（`build_feishu_records` / `run_export_feishu`）+ CLI `同步数据库到飞书.py`（203 行）
- **核心文件**：`客户开发工具.py`、`同步数据库到飞书.py`、`回填行业.py`
- **实现方法**：
  - 生成 `import_records.json`（`{'create_records': [...]}`）→ `subprocess.run([lark-cli, 'base', '+record-batch-create', ...])`。
  - 调子进程前必须 `env.pop('HERMES_HOME', None)`，否则 lark-cli 异常。
  - **50 分门槛**：`[手动采集]` 开头的行**豁免**（用户自己认定是客户才点的，低分不该被静默丢）。
  - 「来源渠道」按网址回客户库查真 `source`（结果 Excel 的 10 列里没有这一列）。
- **与其他模块的关系**：消费 M7 的产物 + 查询 M6。
- **依赖**：`lark-cli.exe`（外部二进制）、飞书 BASE_TOKEN/TABLE_ID（硬编码在 `core/state.py`）、`email` 字段只接受单个邮箱。
- **是否可复用**：⚠️ 中等 —— 强绑定本项目的飞书表结构；「lark-cli 子进程调用 + 编码兜底」的写法可复用。
- **当前完成状态**：✅ 已投产
- **修改时注意**：
  - ⚠️ 「来源渠道」是飞书的**单选**字段，取值必须在表里已有选项。三个值：`谷歌搜索` / `谷歌地图` / `手动采集`。加了新 source 记得同步改 `FEISHU_SOURCES` **并在飞书表里加选项**。
  - ⚠️ 「国家/地区」也要选项名映射（`COUNTRY_STANDARD`：沙特→沙特阿拉伯）。
  - ⛔ `BASE_TOKEN` 是**可读写的活凭据**，目前硬编码且已随公开仓库泄露（见 §6.9）。

---

### M9. 关键词库与前端三级联动

- **功能作用**：给用户一套「行业 → 品类 → 产品」的三级下拉，选中后把多语言产品词一键填进产品词输入框。
- **所在位置**：`关键词库.json`（数据）+ `客户开发工具.py` 第 2400–2407 行（`/api/keywords`）+ `ui/page.html` 的 `loadKeywords/onIndustry/onCategory/onProduct`
- **核心文件**：`关键词库.json`、`ui/page.html`
- **实现方法**：
  - 结构 `{行业: {品类: {产品: [词条]}}}`，词条对象带 9 种语言键（`en,cn,de,fr,es,ar,it,nl,tr`；`fa` 仅食品有）。
  - 规模：**8 行业 / 14 品类 / 40 产品 / 126 词条**。规范行业名：宠物用品 / LED照明 / 家具 / 服装 / 机械零部件 / 户外用品 / 食品 / 塑料包装袋。
  - 前端三级下拉顺序 = `sorted(keys)`（Flask `jsonify` 默认排序），**不是文件键序**。
  - 选国家时 `applyCountryLang()` 自动勾选对应语言。
- **与其他模块的关系**：产出喂给 M1（产品词 → 搜索公式）。
- **依赖**：无（纯数据 + 前端 JS）
- **是否可复用**：✅ 数据与联动模式都可复用。
- **当前完成状态**：✅ 已投产
- **修改时注意**：
  - ⚠️ **字节约定**：UTF-8 无 BOM / **纯 CRLF** / 2 空格缩进 / 末尾无换行。`json.dumps(indent=2, ensure_ascii=False)` 出的是 LF → 必须 `replace('\n','\r\n')` 后**二进制写**。
  - ⚠️ 校验脚本 `_kwlib_check.py`（含与 `_kwlib_before.json` 的 deep-diff）；改库用一次性脚本按 `en` 原文匹配整体重写；结构变更必须同步改前端 JS。
  - ⚠️ 库内 126 词条含大量中文注释式翻译（`cn` 键常写「完整全称，搜索最准」这类说明）。

---

### M10. 搜索条件多语言化

- **功能作用**：按目标国家语言，把「批发商 / 进口商 / 采购」等身份词本地化，避免在法语页面里搜英文词。
- **所在位置**：`core/config.py` 第 12–135 行（`CONDITIONS` / `COND_TEMPLATE` / `COND_ROLES` / `cond_template()`）+ 前端预览
- **核心文件**：`core/config.py`
- **实现方法**：
  - `CONDITIONS` 是 `(key, 中文名)` 2 元组；`COND_TEMPLATE` 是含 `{p}` / `{role}` 的骨架；`COND_ROLES[key][lang]` 有 8 种语言（缺则回落 `en`）。
  - `cond_template(key, lang)` 是**唯一出口**，后端 `run_search` 与前端预览都必须走它（保证「预览即实际」）。
  - 语言优先级：`#kwLang`（用户手选）→ 该国 `hl` → `en`。
  - 国家筛选走 URL 参数 `&gl=…&hl=…`，**不写进搜索词**（`cr`/`lr` 实测不值得加，已拍板）。
- **与其他模块的关系**：被 M1 消费；被 M11（页面）注入为 `tmpl_map` 供预览。
- **依赖**：零 import（`core/config.py` 永远在依赖图最底层）
- **是否可复用**：✅ 高 —— 多语言身份词表可直接搬。
- **当前完成状态**：✅ 已投产
- **修改时注意**：
  - ⚠️ 模板里 `{p}` **别加引号**（`pq_list` 已包好），否则拼出 `""xxx""`。
  - ⚠️ 含 `OR` 的模板**必须用括号锁住同义词组**，否则退化成 `(A B) OR C`，会让 C 单独生效、把任意行业的同类角色拉进结果。
  - ⚠️ `COUNTRIES` 是 4 元组、前端按 5 元组注入 → **改元组长度会连带炸掉两处**。

---

### M11. 本地 Web UI 与状态轮询

- **功能作用**：整个工具的操作界面（主页面 + 手动采集页 + 客户库查询页）+ 实时进度与日志。
- **所在位置**：`ui/page.html`、`ui/manual.html`、`ui/query.html`、`core/ui.py`、`客户开发工具.py` 第 2028 行起（Flask app + 全部路由）
- **核心文件**：`core/ui.py`、三个 html、入口的路由段
- **实现方法**：
  - **服务端渲染在 import 期构建一次**：`_build_page()` 把条件/国家/排除项/中国过滤/地图坐标/身份词以 JSON 注入 `*_PLACEHOLDER`，结果赋值给 `PAGE_HTML` / `MANUAL_HTML`；`_build_query_page()` 另出 `QUERY_HTML`。**改 `ui/*.html` 必须重启工具**。
  - `manual.html` / `query.html` 都用 `PAGE_CSS_PLACEHOLDER` 占位，构建时（`_page_style()` + `_inject_page_style()`）把 `page.html` 的整个 `<style>` 块注入 → **三个页面共用一份 CSS**。⚠️ 反过来说：往那一份里加规则会**连带影响全部三个页面**，副页面专有的样式要写进它们自带的第二个 `<style>`。
  - 状态轮询：前端每秒拉 `/api/status`（主链路：logs/result_count/phase/rows/db_total/db_verified）与 `/api/manual/state`（手动链路：本轮明细 + 最近 50 条）。
  - CORS 三重门：`before_request` 放行 OPTIONS 预检 → `after_request` 只对 `chrome-extension://` 回显 ACAO，并**顺手当扩展心跳**（写 `MANUAL_STATE['ext_last_seen']`）。
- **与其他模块的关系**：所有模块的入口与展示层。
- **依赖**：Flask、`core/ui`、`core/config`
- **是否可复用**：⚠️ 中等 —— 「模板文件 + import 期注入占位符」的模式可复用；页面本身与本业务强绑定。
- **当前完成状态**：✅ 已投产
- **修改时注意**：
  - ⚠️ **`ui/page.html` 的 sha256 被 `_check_page.py` R5 用两条基线守着**：`_TMPL_SHA`（模板文本，当前 `f90082ea…`）+ `_BUILT_SHA`（`_build_page()` 结果）。**故意改主页必须同步重算这两条**（V1.5 加顶栏导航时重算过一次）；它的价值是「误格式化/误翻译把转义改变形时立刻抓到」。副页面专有的样式写进 `ui/manual.html` / `ui/query.html` 自带的第二个 `<style>` —— 混进 page.html 那份会连带影响三页。
  - ⚠️ 改 `ui/*.html` 后**必须重启工具**（import 期构建）。
  - ⚠️ `MANUAL_HTML` / `QUERY_HTML` / `PAGE_HTML` 是模块级常量，不在函数里构建。
  - ✅ 首页顶栏有 `.nav` 导航（V1.5 加）：`📝 手动采集页` → `/manual`、`📊 客户库查询` → `/db`。R6 有断言守着这两个 `href` —— ⚠️ href 写错或被人删掉**不会有任何运行时报错**，只会静默少一个入口。

---

### M12. 回归测试套件

- **功能作用**：改代码后的安全网。22 项，覆盖页面静态、启动、词库、行业规则、地图常量、三条采集链路、UI 真机渲染、查询页（后端冒烟 + 真机）、扩展三层验证、真实库体检。
- **所在位置**：`.workbuddy/`（与程序零耦合，但会被 gitignore 的白名单放行）
- **核心文件**：`_run_all_reg.py`（驱动）、`_reg_summary.txt`（验收记录）
- **实现方法**：
  - 驱动按固定清单跑子进程，每项写 `_reg__<名字>.log`，退出码全 0 才算过。
  - 约定俗成：**除 `_check_db_keys` 与 `补历史欠账 --dry` 外，所有项都把 `core.db.db_path` 打桩到临时目录**（防写脏真实库）。
  - 三层扩展验证：静态（`_check_ext`）→ DOM 桩测（`_smoke_ext_content.js` / `_smoke_ext_popup.js`，Node + 手写最小 DOM）→ 真后端 E2E（`_smoke_ext_live.py`，真 Flask + 真 HTTP）。
- **与其他模块的关系**：横切所有模块。
- **依赖**：Python / Node（路径硬编码在 `_run_all_reg.py`）
- **是否可复用**：✅ 高 —— 「全量驱动 + 每项独立子进程 + 兜底日志」的骨架、DOM 桩、E2E 骨架都可复用。
- **当前完成状态**：✅ 22 项全绿
- **修改时注意**：
  - ⚠️ 打桩落点：子模块间必须 `模块.函数()`（如 `m.db.db_path = …`）；smoke 必须有 `_under_tmp()` 护栏，否则**静默写真实库**。
  - ⚠️ 禁止并行 Edit 同一文件（会静默覆盖）。
  - ⚠️ 新增回归脚本要确认被 `.gitignore` 的 `!` 规则覆盖（`git status --short` 里出现 `??` = 已放行）。
  - ⚠️ **别拿固定数字当基线**（用户在持续用扩展采集）：要按 `source` 分布看一遍 + 查测试域名残留。

---

### M13. 客户库查询与导出

- **功能作用**：从已积累的客户库里按条件筛人（行业 / 国家 / 来源渠道 / 评级 / 评分区间 / 有无联系方式 / 采集时间 / 关键词），确认命中结果后再导出 Excel。解决「采了一堆，但想挑出『某国 + 某行业 + 还没拿到邮箱』这批人去联系」的问题。
- **所在位置**：`ui/query.html`（页面）、`core/db.py` 末段（「客户库查询」一节）、`core/paths.py`（`query_export_dir` / `ts_query_export_path` 等）、`core/ui.py`（`QUERY_HTML`）、`客户开发工具.py`（`/db` + 5 个 `/api/db/*` 路由 + `_save_query_excel`）
- **核心文件**：`ui/query.html`、`core/db.py`（`db_query_customers` / `db_facet_counts` / `_query_where`）
- **实现方法**：
  1. **筛选面板的数据来自真实库**：`/api/db/facets` 现查 `GROUP BY` 返回每个维度的取值 + 条数（外加各自的「未填写」条数），前端据此渲染勾选框。⚠️ 刻意**不**拿关键词库那 8 个规范行业名硬编码 —— 库里还留着历史行业名，硬编码会让那批数据选不出来。
  2. `_query_where()` 把筛选 dict 翻成参数化 SQL：多选走 `IN (...)`（勾了「未填写」则空值也算命中，哨兵 `QUERY_EMPTY='__empty__'`）；**排序字段走白名单**（`QUERY_ORDER_SQL`），非法键静默回落默认排序，绝不把外部字符串拼进 SQL。
  3. `db_query_customers()` 计数与取行**共用同一个 WHERE**，所以「命中 N 条」与翻页看到的一定自洽；`limit` 钳在 1…`QUERY_MAX_LIMIT`(500)。
  4. 导出：`/api/db/export` 分页拉完命中行 → `_save_query_excel()` 写 **14 列**（客户库全字段，**不是**结果 Excel 的 10 列契约）→ 落 `output/查询导出/`，返回文件名与下载 URL；`/api/db/download/<name>` 用 `send_file` 下载，并挡路径穿越。
  5. 页面交互：打开即自动查一次；任一筛选 chip / 排序 / 每页变化都回到第 1 页重查；翻过头（`offset >= total`）自动回退到最后一个有内容的页。
  6. **入口共四处**：① **首页顶栏 `.nav` 的「📊 客户库查询」**（V1.5 加，`href="/db"`，R6 有断言守着）；② Chrome 扩展面板底部「📊 客户库查询」（`popup.html` 的 `#lnkDb` → `background.js::urlsReply()` 返回的 `db` 字段，复用 `DP_URLS` 消息）；③ `/manual` 页顶部同一链接；④ 直接敲地址。⚠️ 四条路都依赖**后端是新代码**：跑着的旧实例（改动前启动的）打 `/db` 是 **404**，必须先重启工具。
- **与其他模块的关系**：**只读消费** M6 客户库；与 M7 结果 Excel / 飞书导出**完全隔离**（见「注意」第一条）。不参与采集，也不被采集调用。
- **依赖**：Flask、openpyxl、`core/db`、`core/paths`、`core/ui`
- **是否可复用**：✅ 高 —— 「facets 驱动的前端筛选面板 + 白名单排序的分页查询 + 导出落子目录」是一套与业务无关的骨架，换个表就能复用。
- **当前完成状态**：✅ 已完成（2026-10-01 新增，`.workbuddy/_smoke_query.py` 126 项 + `_check_query_ui.py` 真机全绿）
- **修改时注意**：
  - ⛔⛔ **导出必须落 `output/查询导出/` 子目录，绝不能落 `output/` 根下**。`find_latest_result()` 只 glob `output/` 一层、且靠「文件名里有 8 位日期」筛候选 —— 查询表的名字天然带日期，落在根下会被它选中当「**最新结果文件**」，把飞书导出的目标劫持到一份查询结果上。`_smoke_query.py` ⑧ 组有一条**反证**断言守着这个行为。
  - ⛔ **查询链路不碰 `STATE_LOCK`、不改 `paths.ENRICH_FILE` / `STATE['output']`**（那两个指针归「本轮采集」用）。它是纯读链路，只开自己的 sqlite 连接。
  - ⚠️ 前端 JS 里的 `const EMPTY = '__empty__'` 必须与后端 `core.db.QUERY_EMPTY` 完全一致（`_check_page.py` R9 有断言）。写错不报错，只会让「勾了未填写却筛不出东西」——典型静默失效。
  - ⚠️ 页面里**不许**出现行业名（`_check_page.py` R9 会红）——选项一律由 `/api/db/facets` 生成。
  - ⚠️ 入口从 `core.ui` 是**分两行 import** 的（`PAGE_HTML, _build_page` 单独一行）——`_check_page.py` R4 有一个字符串级的 glue 断言 `'from core.ui import PAGE_HTML, _build_page'`，合并成一行会让它红。
  - ⚠️ 改 `ui/query.html` 后**必须重启工具**（`QUERY_HTML` 在 import 期构建）。

---

## 4. 核心实现方式

> 只记「怎么实现」，不贴代码。

### 4.1 数据如何流转

```
                        ┌──────────────────────────────────────────┐
  用户填表单            │  run_search（谷歌网页搜索）               │
  ↓                    │   run_maps（谷歌地图名录）                │
Flask /api/start ──────┤   collect_from_html（手动采集/扩展）       │
                       └──────────────┬───────────────────────────┘
                                      ↓ 逐条
                          score_item() 评分 / rating() 分级
                                      ↓
                       db_upsert_customer()  →  DB/客户库.sqlite3（按 website_key 去重）
                                      ↓
                        内存累积本轮结果（all_rows / session_rows）
                                      ↓ 整轮结束（含中途停止）
                     _save_enrich_excel() →  output/行业-日期_时间-国家.xlsx（10 列）
                                      ↓ paths.ENRICH_FILE 指向它
                       build_feishu_records() → import_records.json → lark-cli → 飞书
```

**关键点**：
- 采集**当场**写 SQLite（`_commit_candidate`），Excel 是**整轮结束时**才落盘。
- 手动采集的「本轮明细」只是内存清单，决定 Excel 有哪些行；Excel **只写新增**。
- 飞书导出**不重新抓取**，只读「最新结果文件」。

**查询/导出链路（与上面完全解耦的单向只读支线）**：

```
用户勾条件  →  POST /api/db/query  →  db_query_customers(参数化 WHERE + 白名单 ORDER BY)
                                         ↓ 只开自己的 sqlite 连接，出函数就关
                                  前端渲染结果表（分页、序号跨页接续）
点「导出 Excel」→ POST /api/db/export →  分页拉完命中行 → _save_query_excel(14 列)
                                         ↓
                         output/查询导出/查询导出-<时间戳>-共N条.xlsx
                                         ↓ send_file（挡路径穿越）
                                    浏览器下载 + output/ 留档
```

⚠️ 这条链路**不碰 `STATE_LOCK` / `STATE` / `paths.ENRICH_FILE`**（纯读，长查询不会卡住采集）；
⚠️ 导出**必须**落 `output/查询导出/` **子目录** —— 落 `output/` 根下会被 `find_latest_result()`
选中当「最新结果文件」，把飞书导出的目标劫持到一份查询表上（详见 M13）。

### 4.2 状态如何管理

| 状态对象 | 位置 | 语义 | 前端怎么读 |
|---|---|---|---|
| `STATE` | `core/state.py` | **自动链路**（搜索 / 地图 / 导出）的运行状态：`running/phase/logs/result_count/rows/done/output/stop` | `GET /api/status?since=N`（增量拉日志） |
| `MANUAL_STATE` | `core/state.py` | **手动采集**专用：批量任务子状态（running/stop/total/done/current）+ 本轮会话语义（session_* / added/existed/failed/upgraded）+ 扩展心跳（ext_last_seen） | `GET /api/manual/state`（还附带最近 50 条手动采集记录） |
| `STATE_LOCK` | `core/state.py` | 两套状态**共用同一把** `threading.Lock`（**非可重入**） | — |

**为什么手动采集不复用 `STATE`**：`STATE['stop']` 是自动链路的开关，共用会让「停止手动采集」把正在跑的自动搜索一起杀掉。

### 4.3 锁纪律（全项目最硬的一条）

`STATE_LOCK` **不可重入**，而 `log()` 内部也要抢同一把锁。因此：

> **任何 `log()` 调用必须在 `with STATE_LOCK` 块外；DB IO 与文件 IO 一律在锁外。**

横切一切写状态的地方（`_flush_manual_session`、`_manual_batch_worker`、`api_manual_session_delete` 都踩过这个坑）。标准骨架（四段式）：

```
① 锁内：定位/快照，取出需要的信息
② 锁外：慢 IO（备份、删库、写 Excel、开浏览器）
③ 锁内：改内存状态
④ 锁外：log()
```

另有 `EXCEL_LOCK`（串行化 Excel 写盘）、`_BROWSER_LOCK`（串行化常驻浏览器创建）。

### 4.4 端口如何决定（不写死）

- `PREFERRED_PORTS = (5000, 8000, 8080, 8765, 9000, 7000, 6500, 5800, 5555)`；`pick_port()` **实测 bind**，绑不上就顺延，全不行就让系统分配。
- **为什么不能写死**：Windows 会把**成片** TCP 端口保留给 Hyper-V / WinNAT，落在保留段的端口 bind 直接抛 `WSAEACCES(10013)`，而 `netstat` 里**看不到任何占用**，极易误判成「被别的程序抢了」。且保留段**每次开机漂移**。
- 真实端口通过 `/api/ping` 报给扩展（`_RUN_PORT` 在 `__main__` 里回填）。
- ⚠️ 改 `PREFERRED_PORTS` 必须同步改 `extension/ports.js` 的 `DP_PREFERRED_PORTS`（`_check_ext.py` 有硬断言）。

### 4.5 页面/组件如何通信

- **无框架、无构建**。Python 在 import 期读 `ui/*.html`，把数据以 JSON 注入 `*_PLACEHOLDER`，结果整页返回。
- 前端与后端只通过 **HTTP 轮询**通信（无 WebSocket、无 SSE）。
- 扩展与工具只通过 **HTTP + 自定义头**通信；扩展内部只通过 `chrome.runtime.sendMessage` 通信（`fetch` 只在 service worker 里）。

### 4.6 核心算法

| 算法 | 位置 | 要点 |
|---|---|---|
| 去重键 | `normalize_domain()` | 去 `www.`、丢端口、地图 place 合成 `maps:0x…:0x…` 键、纯邮箱给空键 |
| 地图 place 键 | `maps_place_key()` | 正则抓 `!1s(0x…:0x…)`，比商家名可靠 |
| 搜索评分 | `score_item()` + `rating()` | 6 项加分，满分 90；≥70 重点 / ≥50 普通 / 其他观察 |
| 中国信号过滤 | `china_filter_reasons()` | 16 个可勾选项，分「查询词级」（不参与的进搜索公式）与「结果级」（看标题/网址/摘要/邮箱/电话/正文）两套 |
| 域名黑名单 | `is_blocked()` | 三层：`BLOCK_SUBSTR` → `SEARCH_ENGINE_PREFIX` → `BLOCK_DOMAINS` + `endswith('.cn')` 兜底 |
| 最新结果查找 | `find_latest_result()` + `_result_time_key()` | **从文件名解析日期时间**排序（字典序 ≠ 时间序；mtime 会被「另存为」带偏） |
| 身份词提取 | `maps_role_word()` | 从 `COND_ROLES` 取该国语言的第一个词，拼进地图查询词 |

### 4.7 第三方服务如何接入（飞书）

不走 SDK，走**子进程调 `lark-cli.exe`**：
`生成 JSON payload → subprocess.run([lark-cli, 'base', '+record-batch-create', '--base-token', …, '--json', '@import_records.json', '--as', 'user'])` → 解析 stdout JSON 判 `ok`。
两个坑：① 调之前必须 `env.pop('HERMES_HOME')`；② stdout 可能不是 utf-8，需 utf-8/gbk 双解码兜底。

### 4.8 浏览器自动化如何接入

- 每次任务 `create_browser_page()` 起一个**独立 Chrome 实例**（独立临时 profile + 随机空闲调试端口），不依赖用户手工开 9222。
- 自动链路「任务开头建、`finally` 里 quit」；手动采集是**惰性常驻**（点一下采一条，重建 Chrome 要 3–5s），并用 `atexit` 兜底关闭。
- 两者互不干扰（各自独立实例）。

---

## 5. 可复用功能

> 下面这些是**已经存在、以后大概率还会再用**的东西。改代码前先来这里找，别重复实现。

### 5.1 Python 侧

| 名称 | 位置 | 怎么用 |
|---|---|---|
| `cond_template(key, lang)` | `core/config.py` | 取某条件的公式骨架（已本地化角色词）。**唯一出口**，前后端都必须走它 |
| `_app_dir()` | `core/paths.py` | 拿**项目根**（不是「本文件所在目录」）。⚠️ 有详细注释解释为什么不能写 `dirname(__file__)` |
| `output_dir()` / `ts_result_path()` / `build_result_name()` | `core/paths.py` | 结果文件目录/路径/命名，自带 `_2/_3` 去重 |
| `find_latest_result()` | `core/paths.py` | 找最新结果 Excel（文件名解析时间排序） |
| `normalize_domain()` / `normalize_email()` / `maps_place_key()` | `core/db.py` | 去重键算法，直接可搬 |
| `db_connect()` | `core/db.py` | SQLite 连接（已设 WAL + Row factory） |
| `db_upsert_customer()` | `core/db.py` | 通用 upsert（按 key，email 兜底合并，空值不覆盖，键自愈） |
| `db_has_customer()` | `客户开发工具.py` | 「要不要跳过这个站」的只读判断 |
| `backup_db_before_delete()` | `core/db.py` | **WAL 安全备份**骨架（sqlite3 在线 `backup()` + 节流 + 失败不阻断）——任何「删数据前先备份」都该用它 |
| `db_fix_website_keys(apply=False)` | `core/db.py` | 「扫全库找不一致 + dry-run / apply 两模式」的骨架 |
| `clean_emails()` / `clean_phones()` | `客户开发工具.py` | 邮箱/电话抽取 + 噪声域过滤（`NOISE_EMAIL` 表可直接搬） |
| `_sanitize_page_html()` | `客户开发工具.py` | 把整页 HTML 压到能安全跑正则的规模（先粗截、再剥 script/style/svg/template） |
| `_find_contact_url()` | `客户开发工具.py` | 从页面里找自带联系页链接（比盲猜 `/contact` 准） |
| `enrich(page, url)` | `客户开发工具.py` | 完整抓取策略（含联系页兜底） |
| `score_item()` / `rating()` | `客户开发工具.py` | 评分骨架（可选 `product_words` 参数） |
| `is_blocked()` / `china_filter_reasons()` | `客户开发工具.py` | 域名黑名单 / 中国信号过滤 |
| `pick_port()` | `客户开发工具.py` | 端口实测挑选（任何本地服务都该这么做） |
| `log()` | `core/state.py` | 双通道日志（控制台 + 前端轮询队列） |
| `_flush_manual_session()` | `客户开发工具.py` | 「攒一批 → 一次性落盘 → 失败保留可重试」的骨架 |
| `db_query_customers(filters, order, limit, offset)` | `core/db.py` | **分页查询骨架**：参数化 WHERE + 白名单 ORDER BY + 计数与取行共用同一 WHERE（分页数字必然自洽） |
| `db_facet_counts()` | `core/db.py` | **「按真实数据生成筛选选项」骨架**：各维度 distinct + 条数 + 空值条数（换张表就能用） |
| `query_export_dir()` / `ts_query_export_path()` | `core/paths.py` | 导出落「专用子目录 + 时间戳去重」的骨架（配合「别让产物混进会被扫描的目录」这条经验） |
| 三级抓取降级策略 | `collect_from_html()` | 「秒级正则 → 轻量 HTTP → 重型浏览器」的降级链，通用性很强 |
| `_guess_industry()` | `客户开发工具.py` | 行业判定，**刻意复用 `回填行业.py` 的规则**（口径只能有一份） |

### 5.2 前端 / 扩展侧

| 名称 | 位置 | 怎么用 |
|---|---|---|
| 「模板文件 + import 期注入占位符」模式 | `core/ui.py` | 页面改动不用碰 Python 字符串 |
| 「样式只维护一份」注入技巧 | `core/ui.py::_build_manual_page()` | 从 A 页抽 `<style>` 塞进 B 页的占位符 → B 页零成本共享 A 页样式，且 A 页哈希不变 |
| 扩展端口发现 + 身份校验 | `extension/ports.js` + `background.js::discover()` | 并行探候选端口 + `app` 字段验身份 |
| Shadow DOM + `adoptedStyleSheets` 悬浮按钮 | `extension/floating-css.js` + `content.js` | 跨 CSP、跨 shadow 边界的注入方案 |
| 「唯一 fetch 出口」架构 | `extension/background.js` | popup/content 一律发消息，SW 代发请求 |
| 事件委托删除行 | `ui/manual.html::onSessionBodyClick` + `extension/popup.js::onSessionListClick` | 行是 innerHTML 拼的、会整表重建 → **只能**委托 |
| 「facets 驱动的筛选面板」模式 | `ui/query.html::loadFacets()` | 勾选项全部由后端 distinct 接口生成，页面里零硬编码枚举 —— 将来新增行业/来源，页面一个字都不用改 |
| 「查询条件 → 导出」一整套 | `ui/query.html` + `/api/db/*` | 换张表/换个库就能复用的筛选+分页+导出页面，是目前项目里最完整的一个 CRUD 只读视图 |
| `_note` 兜底提示 | `extension/popup.js` | 应对「末尾必然 `refreshSession()` 会覆盖一次性提示」 |
| `breakdownText()` / `roundTally()` | `ui/manual.html` | 「把两个口径一起报出来」的文案函数 |

### 5.3 工程能力

| 名称 | 位置 | 怎么用 |
|---|---|---|
| 全量回归驱动 | `.workbuddy/_run_all_reg.py` | 「固定清单 + 独立子进程 + 每项写日志 + 退出码汇总」 |
| 临时库打桩护栏 | 各 `_smoke_*.py` | `m.db.db_path = <tmp>` + `_under_tmp()` 自检，防写脏真实库 |
| Node 最小 DOM 桩 | `.workbuddy/_smoke_ext_popup.js` | 不装 jsdom 也能测扩展页面逻辑（含「未知 id 抛错」的设计） |
| 真机 UI 校验 | `.workbuddy/_check_*_ui.py` | 起真 Flask + 真浏览器 + 截图取证 |
| 一次性探针脚本 | `.workbuddy/_probe_*.py`（用完即删） | 排查渲染问题时先探针再断言 |

### 5.4 已沉淀为技能（可直接复用）

- **`chrome-ext-local-tool`**（用户级技能）：给本机 HTTP 工具做 Chrome MV3 采集扩展的完整方法论 —— 端口不写死、内容脚本样式不被 CSP 拦、请求只能由 SW 发、工具页与 popup 共享列表的**逐行删除（按行号 + 双删 + 删前备份）**、三层验证脚本模板。**本项目就是它的原型来源。**
- **`python-monolith-split`**：把上千行单文件 Flask 脚本拆成「入口 + 包」且外部行为一字不变（本项目 `core/` 拆包的方法论来源）。
- **`keyword-lib-extend`**：给 `关键词库.json` 新增/修改行业并打通「回填行业规则 + 三级联动页面 + 全量回归」。

---

## 6. 重要设计决定

### 6.1 为什么拆成「入口 + `core/` 包」

原先是 2500+ 行的单文件。拆分**只搬代码不改行为**，并且必须满足：
- 外部脚本（`补历史欠账.py` 用 `spec_from_file_location` 加载入口，**没有包上下文**）→ 入口只能**绝对导入**，不能相对导入。
- 老脚本按 `模块名.<名字>` 读 → 被搬走的名字要在入口**同名 re-export** 一遍。
- 依赖方向恒定：`config`（零 import）← `paths` ← `state` ← `db` ← `ui` ← 入口。**不允许成环。**

### 6.2 为什么 `ui/page.html` 有 sha256 基线（R5）

拆包时把页面模板拆成独立文件，为的是「改样式不用碰 Python」。为了确保**拆分没改变页面内容**，回归脚本对模板和构建结果都算了 sha256 并硬校验 —— 就是 R5 的 `_TMPL_SHA` / `_BUILT_SHA`。

**这两个基线的含义已经变了**：当初是「一次性验证重构前后等价」，现在只剩「**误格式化 / 误翻译把模板转义改变形时，立刻抓到**」。

**结论（V1.5 起）**：`page.html` **可以改**，但**故意改就必须同步重算 R5 的两条基线**（只改一条会红）。V1.5 加首页顶栏导航时就重算过一次。

⚠️ 但「给某个副页面加专有样式」仍然**不该**往 `page.html` 的 `<style>` 里塞 —— 那一份会被 `_page_style()` 注入到全部三个页面。本页专有的样式写进 `manual.html` / `query.html` 自带的第二个 `<style>`。

### 6.3 为什么搜索和补全合成了一个闭环

早期是「先搜一批网址，再统一补全」。改成「搜到一个立刻补」之后：
- 可以按「新增网站数」精确控制目标（而不是搜一堆再筛）。
- 联系方式信号能在**入库之前**参与中国过滤（顺序很重要）。
- 中途停止也不白跑。

遗留：`_enrich_worklist` / `enrich_core` / `补历史欠账.py` 这套「后补」能力仍保留，专门收拾历史欠账。

### 6.4 为什么端口绝不能写死

见 §4.4。这是踩了 `WSAEACCES 10013` + `netstat` 查不到的坑之后定下的。

### 6.5 为什么扩展的请求只能由 service worker 发

MV3 的 CSP 禁止扩展页面执行远程脚本、也对 `fetch` 来源有限制；更重要的是：把 fetch 集中到一处，才能统一做**端口发现、身份校验、超时、错误兜底**。回归脚本把「`popup.js` 里 `fetch(` 出现 0 次」写成**硬断言**。

### 6.6 为什么删除要「明细 + 客户库双删 + 删前备份」

- **双删**：采集即落库，只删明细是**假删除** —— 库里那条还在，下次再采到同一个站会被 `db_has_customer` 判「已在客户库」跳过，**永远采不回来**，飞书导出也仍会带它。
- **按 `rid` 删**：同一 url 在一轮里可能既有 `added` 又有 `existed`。
- **删前备份**：不可逆操作；用 sqlite3 在线 `backup()`（WAL 下裸拷贝会漏数据）。

### 6.7 为什么 Excel「只写新增」，不写「已在库」

避免导出飞书时重复推送同一家公司。**代价**是「已采 N 条」> 「Excel 行数」。用户拍板维持这个行为，但要求 UI **把两个口径一起报出来**（这是后续必须一直守住的约定）。

### 6.8 为什么 `website_key` 必须恒等于 `normalize_domain(website)`

`db_has_customer()`（判跳过）只查 `website_key`，`db_upsert_customer()`（写入）按键查不到会按 email 兜底合并。两者口径本就不一致，靠**「键与网址严格对齐」**这个不变量把缺口补上。破了就会出现「同一个站反复进 Excel、库里只有一条」。修复能力：`db_fix_website_keys()` + upsert 内的键自愈 + 回归项 `_check_db_keys.py`。

### 6.9 ⛔ 为什么「公开 GitHub 仓库」是个必须记住的事实

`origin = https://github.com/jurryzhang66/waimao.git`，**public**（用户在我的风险说明之后仍明确同意）。里面已包含：
- `DB/客户库.sqlite3`（真实客户 306 条 / 200 邮箱 / 100 电话）
- `output/` 结果表、`DB/backups/` 快照
- **飞书 `BASE_TOKEN`**（`core/state.py`、`同步数据库到飞书.py`、`回填行业.py`）

**推过就删不干净**。要收口只能 `git filter-repo` 重写历史 + 强制推送 + **轮换飞书 token**。
**结论：以后往仓库里加任何敏感文件前，先想清楚这一步。**

### 6.10 其他已定下的约定

- **标签全部用附注标签**（`git tag -a -m`），新版本照做。查标签先 `git tag -l`。
- **V1.4 起不再往记忆文件里写提交 hash**（该提交里就含记忆文件，写 hash 得再 amend、amend 又换 hash，永远差一位）→ 一律 `git rev-parse "V1.4^{commit}"`。
- **10 列硬契约**不可改（见 §7 相关注意事项）。
- **自动搜索的两条链路一次性把结果落到「最新结果文件」**，手动采集则一轮一份 —— 两套语义刻意不同。
- `cr` / `lr` 搜索参数**不值得加**（已实测拍板），国家筛选只用 `gl` / `hl`。

---

## 7. 已知问题

> 都是**目前存在、暂未解决**的问题。改相关代码前先看这一节。

### 7.1 搜索链路

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 1 | **「结果没渲染」两种成因日志分不开**：① 谷歌返回壳页面（重开能好）② 谷歌**零结果页**（`did not match any documents`，重试同 URL 无效）。触发场景 = 冷会话的第一个谷歌请求 + 重公式（33 词） | `open_search()` / `wait_results()` | 排查时容易误判为 bug。**修法未拍板**。取证图 `.workbuddy/_fail_q1_p0.png` |
| 2 | **冷会话首请求被降级** | 同上 | 同上，是 #1 的成因之一 |
| 3 | 谷歌限流：连返壳页面 → 重试失败跳页 | `run_search` | **等 90 秒**恢复。别当 bug。 |

### 7.2 评分与行业

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 4 | ⛔ **评分在非英语场景方向是反的**（20 条法国结果实锤）：`CTYPE_WORDS` 全是英文（`wholesale/distributor/…`），法语 `grossiste/distributeur/fournisseur` 一个不认；且 `score_item()` **只有加分无减分** | `客户开发工具.py` 第 526/653 行 | 法语/德语等市场会把真正买家判成低分。**未修**。根治三件事：① `CTYPE_WORDS` 多语言化 ② `PRODUCT_WORDS` 按本轮产品词动态传入 + 加词边界 ③ 加否决/减分项（`.gov` / 点评站 / 餐馆 / 菜谱 / B2B 名录 / 新闻） |
| 5 | `PRODUCT_WORDS` 写死猫砂垫词表且**子串匹配无词边界** | `客户开发工具.py` 第 527 行 | 换行业必须同步改（已开可选入参缓解，但自动链路未传） |
| 6 | 行业取值历史上有两套口径（`家具家居` / `汽配`） | `重标行业.py` | 已提供重标脚本，**待改 23 条**（dry-run 已备） |

### 7.3 数据质量

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 7 | 库里混着平台/垃圾域名（joybuy / dreamstime / chegg / thomasnet / trendyol / u-buy / petz.ae / suppliergo / archive.org / tiktok，以及 `drive.google.com`、`linkfly.to`）约 25–38 条 | `DB/客户库.sqlite3` | 导飞书会带垃圾。**现在可以直接在「本轮明细」里点 ✕ 删** |
| 8 | 用户自采记录里 `127.0.0.1`（误点工具自己的页面）与 `erp.91miaoshou.com`（SaaS 平台）是明显误采 | 同上 | 是否清理**未拍板** |
| 9 | 客户库 `id=154` 是淘宝记录 | 同上 | 待清 |
| 10 | 飞书里有 **16 条垃圾记录**待删 | 飞书「客户信息」表 + `.workbuddy/_todo.json` | 待处理 |
| 11 | **worklist 判据是「邮箱电话都为空」而非「补过没补过」** | `_enrich_worklist()` | 欠账脚本会**反复**访问抓不到联系方式的站（实测 26 条）。彻底修需加 `enriched_at` 列（**未拍板**） |

### 7.4 工程/流程

| # | 问题 | 影响 |
|---|---|---|
| 12 | **改 `extension/` 后不点「重新加载」→ 分裂态**（popup 新 / SW 旧，用户看到「0 条」以为失败） | 已固化成断言，但仍需人工记得点 |
| 13 | **改 `ui/*.html` 后不重启工具 → 页面不更新**（import 期构建） | 同上 |
| 14 | **跑着的旧实例打新路由是 404** | 交付新功能时必须告诉用户「重启工具」 |
| 15 | `re` 里的 `_MANUAL_PAGE` 常驻浏览器若被用户手动关掉，需重建（已有兜底） | — |
| 16 | 回归脚本自身有 6 处已知脆弱点（`_check_startup` 的换端口原因会漂移、`_check_manual_ui` 的 sleep 竞态、真机截图属「尽力而为」、`_smoke_ext_live` 两遍共用模块对象需清模块级时间戳、`<select>` 程序化赋值不存在的 value 会被忽略、`send_file` 响应持句柄要先 `close()` 才能删文件） | 避免白追假红 |
| 17 | 本机 `core.autocrlf=true` 与页面 sha256 的关系：**已实测确认无影响**（校验脚本用文本模式读，Python 通用换行会归一化 CRLF → LF）。**别再当隐患返工。** |

### 7.5 未拍板的待办

- 「半自动组合 / 纯手工输入」单选未实现。
- 冷会话首请求降级的修法未定。
- 阶段 B 拆包：`google_search` / `google_maps` / `tasks` / `feishu` 尚未从入口拆出。
- 飞书「客户信息」表的「来源渠道」**需要人工**加 `手动采集` 选项（否则导出时该值会被降级成「谷歌搜索」）。
- `chrome://extensions` 加载扩展、装/改扩展后刷新已开页面（人工步骤）。

---

## 8. 当前开发状态

### 8.1 已完成（✅ 投产可用）

| 模块 | 状态 |
|---|---|
| 谷歌网页搜索采集闭环（搜 + 就地补全 + 评分 + 落盘） | ✅ |
| 谷歌地图名录采集 | ✅ |
| 联系方式补全与评分 | ✅（口径有已知缺陷，见 §7.2） |
| 手动采集页 + 三级抓取 + 本轮会话 | ✅ |
| Chrome MV3 扩展（采集 / 明细 / 逐行删除 / 结束本轮 / 设置页） | ✅ |
| SQLite 客户库（去重 / upsert / 键不变量 / 删除+备份 / 存量修复） | ✅ |
| 结果 Excel（10 列契约 / 命名 / 最新文件） | ✅ |
| 飞书导出（含手动采集豁免） | ✅ |
| 关键词库三级联动 + 条件词多语言化 | ✅ |
| 计数口径拆分显示（已采 N = 新增 X + 已在库 Y） | ✅ |
| 客户库查询页 `/db`（多维筛选 + 分页 + 导出 Excel） | ✅ |
| 首页顶栏导航（→ `/manual`、`/db`，V1.5 加） | ✅ |
| 项目拆包（`core/` + `ui/`） | ✅ |
| 22 项全量回归 | ✅ |
| git V1.4 提交 + 推 GitHub | ✅ |

### 8.2 正在开发 / 刚完成未提交

- **最近一轮**（主页顶栏导航：`ui/page.html` 加 `.nav` + R5 基线重算 + R6 与 `_check_live_ui` C 段新断言）：**代码已改完、22 项回归全绿，尚未 git commit**。
- 再往前三轮（① 计数口径拆分 + 去重键不变量；② 客户库查询页 `/db` + 2 个新回归项；③ 扩展面板「客户库查询」入口）也都在等待一并提交 —— 是否打 **V1.5** 待用户拍板。

### 8.3 未完成

- §7 全部已知问题。
- §7.5 全部待办。
- 阶段 B 拆包（`google_search` / `google_maps` / `tasks` / `feishu`）。

### 8.4 数据现状（2026-10-01 实测）

| 项 | 值 |
|---|---|
| 客户库总条数 | **306**（还在涨 —— 用户随时在用扩展采，别拿固定数字当基线） |
| 按来源 | 谷歌搜索 214 / 手动采集 85 / 谷歌地图 7 |
| 有邮箱 | 200 |
| 有电话 | 100 |
| 结果 Excel | `output/` 21 份 |
| 查询导出 | `output/查询导出/`（用完可删，已 gitignore） |
| 库备份 | `DB/backups/` 5 份（清理前 / 污染前 / 删除前 ×2 / 修键前） |
| git | `main` 最新提交 `37de110`（**最近四轮的改动都还没提交**）；标签 V1.0～V1.4（均为附注标签） |

---

## 9. AI 开发注意事项

> 这一节是给「下一次接手这个项目的 AI」的。

### 9.1 动手之前

1. **先看 §3 找到对应功能模块**，再去看那一节指向的具体源文件 —— 不要一上来就全库 grep。
2. **本项目注释密度极高，坑都写在注释里**。改任何函数前，先读它上面的 docstring 和 `⚠️` 注释。很多「看起来多余」的写法都是有实测原因的。
3. **修改前先寻找现有实现**：§5「可复用功能」列了全部可复用件。本项目最常见的浪费就是重复实现已有能力（比如又写一个「抓邮箱」或又写一个「备份数据库」）。
4. **不要在不了解现有实现的情况下重构**。特别是：
   - ⚠️ `ui/page.html`（有 sha256 基线：故意改要**同步**重算 R5 的 `_TMPL_SHA` / `_BUILT_SHA`）
   - ⛔ `run_search` / `run_maps`（跑通的链路，回归守着）
   - ⛔ Excel 的 10 列契约
   - ⛔ `website_key` 不变量
5. **不要随意改变已经确定的架构**（拆包的分层、状态管理与锁纪律、扩展的「唯一 fetch 出口」、端口不写死）。

### 9.2 最容易犯的错（按踩坑频率排序）

| # | 错误 | 正确做法 |
|---|---|---|
| 1 | 在 `with STATE_LOCK` 里调 `log()` → **死锁** | `log()` 与 DB/文件 IO 一律在锁外（四段式骨架见 §4.3） |
| 2 | 用 `shutil.copy2` 备份 SQLite | 必须用 `sqlite3` 在线 `backup()`（WAL） |
| 3 | 改 `extension/` 或 `ui/*.html` 后以为立刻生效 | 重启工具 + `chrome://extensions` 点「重新加载」 |
| 4 | 改了 `ui/page.html` 却忘了重算 R5 基线 | 改它没问题，但必须**同时**更新 `_TMPL_SHA` 与 `_BUILT_SHA`（漏一条就红）。给副页面加**专有**样式仍要写进 `ui/manual.html` / `ui/query.html` 的第二个 `<style>` —— page.html 那份是三个页面共用的 |
| 5 | 按 url 删明细行 | 必须按 `rid` |
| 6 | 只删明细不删客户库 | **双删**，否则那是假删除 |
| 7 | 让 `popup.js` 直接 `fetch` | 必须经 `chrome.sendMessage` → background 代发（0 次 `fetch(` 是硬断言） |
| 8 | 让明细行数 = Excel 行数 | Excel **只写新增**；UI 必须把「已采 / 新增 / 已在库」一起报出来 |
| 9 | 用 `from core.paths import ENRICH_FILE` | 它是唯一会被重新赋值的模块级变量 → 一律 `paths.ENRICH_FILE` |
| 10 | 在 `core/` 里用相对导入 / 在入口用相对导入 | 入口只能**绝对导入**（外部脚本无包上下文） |
| 11 | 并行 Edit 同一个文件 | 会静默覆盖，串行改 |
| 12 | 回归脚本打桩后忘了护栏 → 写进真实库 | `m.db.db_path = <tmp>` + `_under_tmp()` 自检 |
| 13 | 拿固定条数当回归基线 | 用户在用扩展持续采集，**按 source 分布 + 测试域名残留**复核 |
| 14 | 改 `PREFERRED_PORTS` 忘了同步 `ports.js` | 两边一起改（`_check_ext.py` 有硬断言） |
| 15 | 改国家/条件时动了元组长度 | `COUNTRIES` 是 4 元组、前端按 5 元组注入，改长度会连带炸两处 |

### 9.3 改完必须做的

1. **跑受影响的单项回归**，再跑 `.workbuddy/_run_all_reg.py`（**22 项**）—— **全部 EXIT=0** 才算过。
2. **复核真实客户库**：条数与 source 分布、测试域名残留 = 0、`DB/backups/` 没有测试垃圾。
3. **检查 `.gitignore`**：新增的回归脚本要被 `!` 白名单放行（`git status --short` 里出现 `??`）。
4. **更新记忆**：`.workbuddy/memory/YYYY-MM-DD.md` 追加当日工作日志；长期结论写 `.workbuddy/memory/MEMORY.md`。
5. **交付时明确告知人工步骤**：是否需要重启工具、是否需要点扩展「重新加载」、飞书表是否需要加选项。

### 9.4 环境信息

| 项 | 值 |
|---|---|
| 工作目录 | `D:\waimao\dp` |
| Python（项目常用） | `D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe` |
| Node | `C:\Users\admin\.workbuddy\binaries\node\versions\22.22.2-3\node.exe` |
| Chrome（浏览器自动化） | 优先 Playwright 自带 Chromium，回退系统 Chrome / Edge（见 `create_browser_page()`） |
| lark-cli | `C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe` |
| 启动方式 | 双击 `启动客户开发工具.bat`，或 `python 客户开发工具.py` |
| 访问地址 | 启动日志会打印真实端口（`pick_port()` 实测决定，**别假设是 5000**） |

---

## 附录：一句话索引

| 我想… | 去看 |
|---|---|
| 改搜索逻辑 | `客户开发工具.py` `run_search` + `core/config.py` |
| 改地图采集 | `客户开发工具.py` `run_maps` / `maps_*` |
| 改抓邮箱/电话 | `客户开发工具.py` `clean_emails` / `clean_phones` / `enrich` / `_find_contact_url` |
| 改评分 | `客户开发工具.py` `score_item` / `rating` |
| 改首页顶栏导航 | `ui/page.html` 的 `.nav` / `.nav-a`（⚠️ 动它就连带要重算 `_check_page.py` R5 的 `_TMPL_SHA` / `_BUILT_SHA`） |
| 改页面 | `ui/page.html` / `ui/manual.html` / `ui/query.html`（⚠️ 改了 `page.html` 必须重算 R5 两条基线） |
| 改客户库查询页 | `ui/query.html` + `core/db.py` 末段「客户库查询」+ 入口 `/api/db/*`（⚠️ 导出必须落 `output/查询导出/` 子目录） |
| 加/改筛选维度 | `core/db.py` `_query_where()` + `db_facet_counts()`（前端零改动，选项自动出现） |
| 改扩展 | `extension/`（改完必须点「重新加载」） |
| 改数据库结构 | `core/db.py` + `.workbuddy/_check_db_keys.py` |
| 改结果 Excel 列 | ⛔ 不要改（10 列硬契约） |
| 改飞书导出 | `客户开发工具.py` `build_feishu_records` / `run_export_feishu` |
| 改关键词库 | `关键词库.json` + `.workbuddy/_kwlib_check.py`（注意 CRLF 字节约定） |
| 加行业 | 技能 `keyword-lib-extend` |
| 加新回归项 | `.workbuddy/_run_all_reg.py` 的 `ITEMS` + `.gitignore` 白名单 |
| 查历史决策 | `.workbuddy/memory/MEMORY.md` + `memory/2026-09-27~30.md` |
| 查最近一次回归结论 | `.workbuddy/_reg_summary.txt` |
