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
- 有 **23 项自动化回归**（`.workbuddy/_run_all_reg.py`），改代码后必须全绿。
- 真实客户库已积累 **303 条**（有邮箱 200 / 有电话 99），用户在日常使用中（数字一直在涨）。
- 代码已提交并推送到 GitHub：`https://github.com/jurryzhang66/waimao`（**public**，用户知情同意，见 §6.9 风险提示）。
- **未提交的工作区改动**：**M16（主页实时明细逐行删除）+ M17（采集数量强必填）+ M18（「本轮明细」共享组件）三轮都还没 commit**。此前八轮已由**用户自己**以「备份1」`f69f1af`（轻量标签 `v1.5`）与「备份2」`d332048`（`v1.5.1`）提交；`v1.5.1` 已含 M14 + M15 + 首页顶栏导航。
  ⚠️ 用户打的是**轻量标签**（`v1.5` / `v1.5.1`），不是 `V1.x` 那种 `-a -m` 附注标签 → 查「某轮落在哪个提交」用 `git tag -l` + `git for-each-ref refs/tags`，**别只认大写 `V1.x`**。
  ⚠️ `git status` 里若看到若干 `D`（`DB/backups/` 的旧备份 + `关键词库.json.bak*` + `客户库.sqlite3.bak_*`）：**是用户自己清理的，不是 bug、不用恢复**（用户 2026-10-02 确认）。提交时用 `git add -A` 让这些删除自然一并进去即可，**不必单独为它做任何事**。

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
│   ├── page.html            ★ 主界面模板（819 行，含顶栏导航）。**sha256 有基线（R5），故意改要同步重算**
│   ├── manual.html          ★ 手动采集页模板（395 行），复用 page.html 的 <style> 块
│   ├── query.html           ★ 客户库查询页模板（571 行），同样复用 page.html 的 <style> 块
│   └── live-table.js        ★ 「本轮明细」共享组件（254 行，见 M18）：主页与 /manual 的同一张表 + 同一个居中确认框
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
├── 标注空行业.py              ★ CLI：把「行业没标注」的客户批量写成指定行业（默认 dry-run，--apply 才写）
├── 同步数据库到飞书.py         CLI：把 SQLite 全量缺失记录同步到飞书（--dry-run 预演）
├── demo.py                    诊断脚本：检查 PyCharm 环境与浏览器能否启动
├── gen_import.py              一次性脚本：从旧 Excel 生成飞书导入 JSON（历史遗留）
│
├── 客户库字段说明.md          字段契约文档（字段含义 / 去重规则 / 评分解释）
├── 谷歌外贸客户开发搜索技巧手册.md  业务手册（搜索运算符 / 分国家策略 / 邮件合规 / 30 天计划）
├── AI_PROJECT_CONTEXT.md      ★ 本文档：项目地图
│
└── .workbuddy/              ⚠️ 与程序**零耦合**（代码里引用 0 处），但是改代码的安全网
    ├── _run_all_reg.py        全量回归驱动（23 项，逐项写 _reg__<名字>.log）
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
     ⚠️ 传了 `raw_queries`（见 **M14**）时**整步跳过**：每条自定义词就是完整公式，原样发出。
     ⚠️ 若 `country_limit` 含 `site`（见 **M15**），在核心公式后**追加 `site:.xx`**（进搜索词）；含 `cr` 则给 URL 追加 `&cr=countryXX`（不进搜索词）。默认 `none` 时这两步都不发生。
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
  - `clean_emails` 过滤三类误报：① 文件扩展名被当成 TLD（srcset 里的 `xxx_1512x@2x.png`）② 埋点/第三方宿主（`sentry.io`、`jsdelivr.net`…）③ 32 位 hex 的 local part。判据集中在 `_is_noise_email()`，每站最多留 3 个。
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
  - 收尾统一走 `_manual_row()`（评分 → 返回 11 键行，**不写库**）。
  - ⛔ **入库时机 = 点「🏁 结束并生成 Excel」那一刻（2026-10-11 改）**：采集时**一行都不写** SQLite，
    采到的行只活在内存 `MANUAL_STATE['session_rows']` 里；`_flush_manual_session()` 里**先 `db_upsert_customer`
    逐条入库、成功后才写结果 Excel**（保证「表里有的库里都有」）。动机：把国家/行业填错的那一轮可以直接
    丢掉，不会提前污染客户库。代价（用户拍板接受）：没点「结束」就关掉工具，这一轮明细就没了。
    ⚠️ `run_search` / `run_maps`（自动那两条链路）**没改**，仍是「边采边落库」。
  - **本轮会话语义**：`session_active / session_rid_seq / session_rows / added / existed / failed / upgraded`。点「开始本轮」开轮；**扩展单点若本轮未开，自动替用户开轮**（`_ensure_manual_session`）；口径（行业/国家）只在开轮那一刻记下。
  - 结束：`_flush_manual_session()` → **先入库、再** `_save_enrich_excel()` **新建**一份结果文件并成为「最新结果文件」；**空轮不落库不落盘**；**失败保留数据**可一键重试（入库用 upsert，重试幂等）。
  - 批量任务（`/api/manual/batch`）是**本轮内的一个可选子过程**，单线程串行；批量还在跑时点「结束」只置挂起标志，由 worker 的 `finally` 收尾落盘。
  - **逐行删除**（✕）：`POST /api/manual/session/delete`，按 `rid` 定位。**默认只删内存明细、不碰库**（本轮的行还没入库；灰字行更是别人的老客户）。唯一例外：`kind='added'` **且** `db_has_customer(url)` 为真（来源＝「已入库但结果 Excel 没写成功」那种保留行）→ 这时才走 `_delete_customer_and_backup()` 连库一起删。
  - **本轮内去重**：`_session_has_url(url)` 按 `normalize_domain` 比 `session_rows` 里 kind='added' 的行 —— 因为本轮采的还没入库，`db_has_customer()` 看不见它们（踩过：同一个站在一份表里出现 3 次）。
- **与其他模块的关系**：喂给 M6（客户库）、M7（结果 Excel）、M8（飞书）；被 M5（扩展）调用。
- **依赖**：Flask、`requests`、DrissionPage（第③级）、`core/state.MANUAL_STATE`
- **是否可复用**：✅ 高 —— 「三级抓取」的降级策略、「本轮会话」的攒批+一次性落盘模式、「按需删库+删前备份」的骨架都可复用。
- **当前完成状态**：✅ 已投产（最活跃的一路，库内 69 条手动采集）
- **修改时注意**（本节是全项目坑最密的地方）：
  - ⚠️⚠️ **`log()` 内部会抢 `STATE_LOCK`（非可重入）→ 任何 `log` 必须在 `with STATE_LOCK` 块外调；DB 与文件 IO 一律锁外**。历史踩过 2 次死锁。删除路由的骨架就是这条纪律的样板（①锁内定位 ②锁外备份+删库 ③锁内改内存 ④锁外 log）。
  - ⚠️⚠️ **UI 必须报两组数：「有效数」/「采集总数」**。有效数 = 新增（＝真正入库、＝结果 Excel 行数）；采集总数 = 明细行数 = 新增 + 已在库（老客户也留一行灰字痕）；**Excel 只写新增**。扩展面板与 `/manual` 的徽章/状态行按 `有效 13 / 采集总数 17 · 已在库 4` 报（`liveBadgeText()` / `breakdownText()`，见 **M19**）。2026-10-10 用户点名：老写法只报一个「已采 N 条」＝总数，会把重复条目也当成成功数。
  - ⚠️ 删除**不再是无条件双删**（2026-10-11 改）：手动链路本轮的行还没入库，删它只动内存明细；
    只有「已入库但 Excel 没写成功」的保留行才连库一起删（判据 `kind='added' and db_has_customer(url)`）。
    灰字 `kind='existed'` 行**永远不碰库**。⚠️ 但「Excel 里有的，库里必须都有」这条不变量仍要守住 ——
    所以入库排在写表之前，且被删的行既不入库也不进 Excel。
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
- **当前完成状态**：✅ 已投产（303 条）
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
  - ⛔ **多值分隔符**：「邮箱」列用**逗号**（`EMAIL_SEP = ', '`），「电话」列仍用 `' / '`（用户明确保留，两者刻意不同）。
    这个分隔符在**写**（`_row10` / `_save_enrich_excel` / 写库 email 字段 / 实时明细 JSON）与**读**（`split_emails()` / `同步数据库到飞书.py` / `gen_import.py`）两侧**必须一起改** ——
    飞书导出是**从结果 Excel 读回再拆**的，只改写侧会让 `EMAIL_OK` 对整串失配 → **邮箱整列静默丢光**。
    `split_emails()` 用 `re.split(r'\s*[,/]\s*')` 兼容新旧两种分隔符，所以 2026-10-11 之前的存量数据仍读得出来
    （库内 73 条多邮箱记录已于当天刷成逗号）。守卫：`_check_live_ui.py`（页面 DOM）、`_check_feishu_records.py` ⑤（写侧 + 旧斜杠读回）、`_smoke_ext_popup.js`（插件明细）。
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
  - 国家筛选默认走 URL 参数 `&gl=…&hl=…`，**不写进搜索词**。在此之外还提供一层更硬的国家限定（`cr` 挂 URL、`site:` 进搜索词）—— 见 **M15**，**默认关、仅标准网页模式**。`lr` 仍不采用。
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
  - ⚠️ **`ui/page.html` 的 sha256 被 `_check_page.py` R5 用两条基线守着**：`_TMPL_SHA`（模板文本）+ `_BUILT_SHA`（`_build_page()` 结果）。**故意改主页必须同步重算这两条**（已重算过多次：顶栏导航 / M14 / M15 / M16 / M17 各一次）—— ⛔ **别在本文件里写死 hash**，一律以 `_check_page.py` 顶部的常量为准。它的价值是「误格式化 / 误翻译把转义改变形时立刻抓到」。副页面专有的样式写进 `ui/manual.html` / `ui/query.html` 自带的第二个 `<style>` —— 混进 page.html 那份会连带影响三页。
  - 📌 **主页卡片顺序（`ui/page.html`，编号硬编码在 `<h3>` 文字里，没有 CSS 计数器 / `<ol>`）**：
    `1. 本次任务采集数量`(M17) → `2. 目标国家` → `📋 产品关键词库`（**刻意无编号**）→ `.grid` 内 `3. 产品关键词` / `4. 搜索条件` / `5. 参数` / `6. 关键词组合预览` → `7. 自定义搜索词`(`#rawCard`) → `.btn-row` → `📥 本轮已入库明细`。
    ⛔ **插卡/挪卡必须整轮重排编号**，并同步改这些**用户可见**的提示语：`start()` 的两条 alert（「或在第 7 步填一条自定义搜索词」）、组合预览里的占位（「请先填写「3. 产品关键词」，并至少勾选一个「4. 搜索条件」」）、`#rawCard` 的说明（「上面第 4 步勾选的条件」/「目标国家（第 2 步）」）。漏改**不报任何错**，只是提示语指到错的步骤 —— `_check_page.py` R13 与 `_check_live_ui.py` G 段一起守着。
  - ⚠️ 改 `ui/*.html` 后**必须重启工具**（import 期构建）。
  - ⚠️ `MANUAL_HTML` / `QUERY_HTML` / `PAGE_HTML` 是模块级常量，不在函数里构建。
  - ✅ 首页顶栏有 `.nav` 导航（V1.5 加）：`📝 手动采集页` → `/manual`、`📊 客户库查询` → `/db`。R6 有断言守着这两个 `href` —— ⚠️ href 写错或被人删掉**不会有任何运行时报错**，只会静默少一个入口。

---

### M12. 回归测试套件

- **功能作用**：改代码后的安全网。23 项，覆盖页面静态、启动、词库、行业规则、地图常量、三条采集链路、UI 真机渲染、查询页（后端冒烟 + 真机）、数据修复脚本（标注空行业）、扩展三层验证、真实库体检。
- **所在位置**：`.workbuddy/`（与程序零耦合，但会被 gitignore 的白名单放行）
- **核心文件**：`_run_all_reg.py`（驱动）、`_reg_summary.txt`（验收记录）
- **实现方法**：
  - 驱动按固定清单跑子进程，每项写 `_reg__<名字>.log`，退出码全 0 才算过。
  - 约定俗成：**除 `_check_db_keys` 与 `补历史欠账 --dry` 外，所有项都把 `core.db.db_path` 打桩到临时目录**（防写脏真实库）。
  - 三层扩展验证：静态（`_check_ext`）→ DOM 桩测（`_smoke_ext_content.js` / `_smoke_ext_popup.js`，Node + 手写最小 DOM）→ 真后端 E2E（`_smoke_ext_live.py`，真 Flask + 真 HTTP）。
- **与其他模块的关系**：横切所有模块。
- **依赖**：Python / Node（路径硬编码在 `_run_all_reg.py`）
- **是否可复用**：✅ 高 —— 「全量驱动 + 每项独立子进程 + 兜底日志」的骨架、DOM 桩、E2E 骨架都可复用。
- **当前完成状态**：✅ 23 项全绿
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
  6. **删除客户**（2026-10-02 加）：结果表每行最左有勾选框、最右有 ✕，另有「🗑️ 删除选中 (N)」按钮与表头全选框（支持半选态）。两个入口打**同一条**接口 `POST /api/db/delete`，body 固定 `{'ids': [主键…]}`（单行就是长度为 1 的数组）。后端 `db_delete_customers_by_ids()` **按主键**删（不用 website_key，主键无歧义），删前调 `backup_db_before_delete()` 落一份 WAL 安全备份到 `DB/backups/`（300 秒节流，失败不阻断）。删完前端原地重查当前页。
  7. **入口共四处**：① **首页顶栏 `.nav` 的「📊 客户库查询」**（V1.5 加，`href="/db"`，R6 有断言守着）；② Chrome 扩展面板底部「📊 客户库查询」（`popup.html` 的 `#lnkDb` → `background.js::urlsReply()` 返回的 `db` 字段，复用 `DP_URLS` 消息）；③ `/manual` 页顶部同一链接；④ 直接敲地址。⚠️ 四条路都依赖**后端是新代码**：跑着的旧实例（改动前启动的）打 `/db` 是 **404**，必须先重启工具。
- **与其他模块的关系**：**只读消费** M6 客户库；与 M7 结果 Excel / 飞书导出**完全隔离**（见「注意」第一条）。不参与采集，也不被采集调用。
- **依赖**：Flask、openpyxl、`core/db`、`core/paths`、`core/ui`
- **是否可复用**：✅ 高 —— 「facets 驱动的前端筛选面板 + 白名单排序的分页查询 + 导出落子目录」是一套与业务无关的骨架，换个表就能复用。
- **当前完成状态**：✅ 已完成（2026-10-01 新增查询/导出；2026-10-02 新增删除、并把删除确认改成**页面自己的居中模态框**。`.workbuddy/_smoke_query.py` **168 项** + `_check_query_ui.py` 真机 A–H 全绿 + 全量 **23 项**）
- **修改时注意**：
  - ⛔⛔ **导出必须落 `output/查询导出/` 子目录，绝不能落 `output/` 根下**。`find_latest_result()` 只 glob `output/` 一层、且靠「文件名里有 8 位日期」筛候选 —— 查询表的名字天然带日期，落在根下会被它选中当「**最新结果文件**」，把飞书导出的目标劫持到一份查询结果上。`_smoke_query.py` ⑧ 组有一条**反证**断言守着这个行为。
  - ⛔ **查询链路不碰 `STATE_LOCK`、不改 `paths.ENRICH_FILE` / `STATE['output']`**（那两个指针归「本轮采集」用）。**删除接口同样全程不持 `STATE_LOCK`** —— `backup_db_before_delete()` 内部会调 `log()`，而 `log()` 自己要抢那把**非可重入**锁，持锁调用必死锁（`_check_page.py` R9 用 AST 断言钉住了「删除接口里不出现 `STATE_LOCK`」）。
  - ⛔ **删除必须按主键 id**（`db_delete_customers_by_ids`），并且**空/非法 id 一律返回 0** —— 少了这道门，前端传个 `[]`/`None`/字符串就等于 `DELETE FROM customers`（清库）。`_smoke_query.py` ⑪ 组有 4 条断言守着。
  - ⚠️ 删除**只动客户库，不动 `MANUAL_STATE`**：若「本轮采集」正在进行，被删的那条仍留在它的内存明细里（那明细不是从库里读的），本轮结果 Excel 还会带上它 —— 要一并拿掉得去 `/manual` 点那行的 ✕。
  - ⚠️ 前端 JS 里的 `const EMPTY = '__empty__'` 必须与后端 `core.db.QUERY_EMPTY` 完全一致（`_check_page.py` R9 有断言）。写错不报错，只会让「勾了未填写却筛不出东西」——典型静默失效。
  - ⚠️ 页面里**不许**出现行业名（`_check_page.py` R9 会红）——选项一律由 `/api/db/facets` 生成。
  - ⚠️ 结果表每行的勾选框 / ✕ 是 `innerHTML` 整表重画的，删除的事件**必须委托到 `#resBody`**（与 `/manual` 的 `.row-del` 同一个道理：逐行绑监听会随行一起丢）。
  - ⚠️ 入口从 `core.ui` 是**分两行 import** 的（`PAGE_HTML, _build_page` 单独一行）——`_check_page.py` R4 有一个字符串级的 glue 断言 `'from core.ui import PAGE_HTML, _build_page'`，合并成一行会让它红。
  - ⛔ **二次确认一律用页面自己的模态框（`#delModal`），绝不用原生 `confirm()`**：原生对话框贴在浏览器窗口**顶部**、位置与样式都由浏览器决定（用户明确嫌「放顶部不方便」，2026-10-02 要求移到屏幕中间）。模态框 = `position:fixed` 全屏遮罩 + `flex` 居中卡片，Esc / 点遮罩 = 取消，Enter = 确定。`_check_query_ui.py` H 段断言「卡片中心落在视口正中 ±2px」（量之前先等 `m-pop` 入场动画落定），`_check_page.py` R9 断言整页里**不再出现 `confirm(`**。⚠️ **例外：`ui/manual.html`（约第 408 行）保留原生 confirm** —— 用户 2026-10-02 拍板**暂不改**（别主动去动，改它要同步 `_check_manual_ui.py` + R7）。
  - ⛔ **模态框等「JS 要取的 DOM 节点」必须放在 `<script>` 之前**：本页脚本是**立即执行的 IIFE**，解析到那一刻就 `getElementById` 取节点 —— 放到 `</script>` 之后会拿到 `null`、绑事件抛 TypeError，导致 `init()` 整体中断、**筛选面板全空白**（现象是「0 个筛选框」而不是弹窗报错，极易误判成后端挂了；实测踩过）。
  - ⚠️ 改 `ui/query.html` 后**必须重启工具**（`QUERY_HTML` 在 import 期构建）。

---

### M14. 自定义搜索词（完全原样搜索）

- **功能作用**：主页第 7 卡。用户自己写完整谷歌查询（一行一条），**原样**发出去 —— 不套条件模板、不自动加英文双引号、不自动拼产品词、不拼排除词、不做中国商家过滤。用于标准模式覆盖不到的长尾查询（例如手写 `-site:.cn`、`OR`、`(...)`、指定城市名）。
- **所在位置**：`ui/page.html` 的 `#rawCard` / `#rawQueries`（卡片 + `rawQueries()` + `renderCombos()` 分支 + `start()` 校验 + `onSource()` 置灰）；后端 `客户开发工具.py` 的 `api_start`（读 `custom_queries`、`RAW_QUERY_MAX = 20`）与 `run_search(..., raw_queries=None)`。
- **核心文件**：`ui/page.html`、`客户开发工具.py`
- **实现方法**：
  1. 前端 `rawQueries()` 按行取、丢弃空行、去首尾空格；**非空即进入自定义模式**（与标准模式**互斥**）。
  2. `start()` 把列表放进请求体的 `custom_queries` 字段；同时放宽两处校验：`products` 可空、搜索条件可不勾（都改成「或填一条自定义搜索词」）。
  3. 后端 `api_start` 清洗（非字符串丢弃 / `strip` / 去重保序）→ 超过 `RAW_QUERY_MAX` 拒绝 → `source == 'maps'` 时整批忽略并记日志。
  4. `run_search` 里 `custom_mode = bool(raw_queries)`：`pq_list = raw_queries`、`cond_count = 1`、`cond_list = [('自定义', '{p}')]`（**占位模板，让原有双层循环原样跑，不必另写一套循环**）、`formula = pq`（原样）。
  5. 国家**不进搜索词**：仍走 `country_params = &gl=&hl=` 挂 URL，结果行照旧 `item['country'] = cname` → Excel 第 10 列。**国家那段代码一行都没改。**
- **与其他模块的关系**：与 M1 共用同一条链路（`open_search` / `extract_results` / `enrich` / 评分 / `db_upsert_customer` / M7 落盘 / M8 飞书），只是**查询词的来源**不同。与 M2 并列。
- **依赖**：与 M1 相同。
- **是否可复用**：`raw_queries` 这个「绕过模板直给公式」的开关本身可复用（任何「用户手写完整查询」的场景都能走它）。
- **当前完成状态**：✅ 已投产（2026-10-02 新增）
- **修改时注意**：
  - ⛔ **「搜索词一个字符都不加」是这条链路的全部价值**（用户原话：「既然是自定义关键词我就不希望加任何进去，要干净」）。`exclude` / `china_filter_terms` / 双引号一律不许拼。
  - ⛔ **`china_filters` 必须置空**：用户拍板自定义模式下**完全不做中国商家过滤**。实现方式是 `custom_mode` 时 `china_filters = set()` —— 这样 `extract_results()` 与 `china_filter_reasons()` 两处调用**一个字都不用改**就自动变成 no-op（`china_filter_reasons` 见到空集合直接 `return []`）。
  - ⚠️ **「完全不过滤」有边界**：`is_blocked()` 的平台黑名单（`BLOCK_DOMAINS`：amazon / ebay / etsy / walmart / wikipedia / linkedin / youtube / indiamart / trade.gov…、`BLOCK_SUBSTR`、搜索引擎域名族）**仍然生效**，与 `china_filters` 无关。要放开它属另一个开关，本次未做。
  - ⛔ **两处前端校验必须一起放宽**：`start()` 里 `if (!products.trim())` 与 `if (source !== 'maps' && !conditions.length)` —— 只改后者的话，自定义模式下会被「请填写产品关键词」挡住。
  - ⛔ **后端第一道门也要放宽**：`api_start` 里 `if not products: return ...'请填写至少一个产品关键词'`，只改前端会在 HTTP 层被拒。
  - ⚠️ `cond_list` 必须给**占位模板**：留空会让 `for cname2, tmpl in cond_list` 永不进入 → **静默跑 0 条查询**（日志「本轮新增 0 个网站」），与「勾了条件却 0 条」是同一个坑。
  - ⚠️ 预览（`renderCombos()`）必须**同步**切成自定义分支，否则用户照预览抄下来的词与实际发出去的不符（预览/实搜两条链路一致的既有约定）。
  - ⚠️ 自定义框只服务**谷歌网页搜索**：切到地图模式时置灰 + 提示（`#rawMapsHint`），`api_start` 里也整批忽略。
  - ⚠️ 改 `ui/page.html` 后**必须重启工具**，且**必须重算 R5 两条 sha256**。

---

### M15. 国家限定（可选，默认关）

- **功能作用**：主页第 5 步「参数」卡里的**四选一**（`none` / `cr` / `site` / `both`），在现有 `&gl=&hl=`（软偏好，不排除任何页面）之外，再叠一层更强的国家限定。**默认 `none`，行为与旧版一字不差**；只对「谷歌网页搜索」的**标准模式**生效。
- **所在位置**：`core/config.py`（`COUNTRY_LIMITS` / `COUNTRY_LIMIT_MODES` / `COUNTRY_LIMIT_DEFAULT`）、`core/ui.py`（注 `COUNTRY_LIMITS_PLACEHOLDER`）、`ui/page.html`（`#countryLimit` 四选一 + `countryLimit()` / `effectiveLimit()` / `siteTerm()` / `countryParams()` / `renderCombos()`）、`客户开发工具.py`（`run_search(country_limit=)` 与 `api_start` 透传）。
- **核心文件**：`core/config.py`、`ui/page.html`、`客户开发工具.py`
- **实现方法**：
  1. 数据层 `COUNTRY_LIMITS = {code: (cr, site)}` —— `cr` 是 `countryXX`（**大写 ISO**，如 `countryFR`），`site` 是 `site:.xx` 域名字面量。**独立字典**，与 `COUNTRY_CENTERS` 同理，**不动 `COUNTRIES` 4 元组**。
  2. `cr` **只挂 URL**（`countryParams()` 末尾 `s += '&cr=' + cr`），`site:` **只进搜索词**（`renderCombos()` 标准分支 `core = core + ' ' + st`）；两者都与既有 `&gl=&hl=` 并联。
  3. 特殊值：**美国** `('countryUS', '')` —— site 留空（美国 B2B 以 `.com` 为主，`.us` 极少）；**伊朗** `('', 'site:.ir')` —— cr 留空（不在谷歌 cr 支持列表）；`ca_fr` 内部码 → 映射 `countryCA`。英国 `cr='countryGB'`（**待实测**；`COUNTRIES` 里 `gl='uk'` 保持不变）。
  4. **互斥纪律**：`custom_mode` 时强制 `country_limit='none'`（与 `china_filters = set()` 同一纪律）；地图模式整块 `display:none` + `api_start` 忽略。
- **与其他模块的关系**：M1 的搜索链路消费；`site:` 与「找采购决策人（领英）」条件**互斥**（领英模板本身是 `site:linkedin.com/in …`，叠加 `site:.fr` 必 0 结果）。数据层被 M11 注入为前端常量。
- **依赖**：`core/config.py`（零 import）；前端零新依赖。
- **是否可复用**：`COUNTRY_LIMITS` 这张「代码 → (cr, ccTLD)」映射表可整张搬走。
- **当前完成状态**：✅ 已投产（2026-10-02 新增，代码已改完 + 23 项回归全绿，尚未 git commit）
- **修改时注意**：
  - ⛔ **默认关是刻意设计**：2026-09-28 真机实测（法国同查询 `"nouilles chinoises" grossiste`）—— `&gl=fr&hl=fr`（现状）**10 条 / `.fr` 占 50%** 最好；加 `cr=countryFR` 后**掉到 7 条 / 占 29%**、真客户反而被挤掉（法国 B2B 大量用 `.com`）。**限定更严 ≠ 更准**。
  - ⚠️ **`site:` 不是「限国家」而是「限域名」**：能当国家筛选是因为 ccTLD 与国家强绑定，**但美国是例外**（`.us` 注册量只有 `.com` 百分之一量级）→ 美国 site 留空。
  - ⚠️ **`site:.uk` 能匹配 `.co.uk`**：`site:` 支持 TLD，`"example.co.uk".endswith(".uk")` 成立 → 英国写 `site:.uk` 即可覆盖 `.co.uk`。
  - ⚠️ **已知限制**：`open_search()` 最后一轮兜底（`type_search`）走的 `country_params` **不含 `cr`** → 壳页面兜底轮会丢 `cr`（`gl`/`hl` 本来也丢）；`site:` 在 formula 里，不会丢。本轮**接受 + 记账**（见 §7.1 3b）。
  - ⚠️ 新增国家时 `COUNTRY_LIMITS` 的键要和 `COUNTRIES` 的 `code` 对齐（`_check_page.py` R11 有 `set(COUNTRY_LIMITS) == {c[0] for c in COUNTRIES}` 断言）。
  - ⚠️ 改 `ui/page.html` 后**必须重启工具**，且**必须重算 R5 两条 sha256**。

---

### M16. 首页「本轮已入库明细（实时）」逐行删除

- **功能作用**：主页 `/` 的「📥 本轮已入库明细（实时）」表**每一行加一个 ✕**（与 `/manual` 的「③ 本轮采集明细」体验一致），把不需要的那一条就地删掉 —— 同时从**客户库**和**本轮结果**里拿掉。**只在采集中（`running and phase=='search'`）可点**；采集结束 / 导出期 ✕ 自动置灰并提示去 `/db` 清理。确认走页面自己的**居中模态框**（不用原生 `confirm`）。
- **所在位置**：`ui/page.html`（`.live-wrap` 表格的 9 列表头 + 一行 `<script>LIVE_TABLE_JS_PLACEHOLDER</script>` + 薄封装 `renderRows` / `syncLiveEditable` / `onLiveBodyClick` / `deleteLiveRow`）；**表格与居中模态框本体已搬进共享组件 `ui/live-table.js`（见 M18）**；后端 `客户开发工具.py` 的 `POST /api/live/delete`（`api_live_delete`）+ 共用 `_delete_customer_and_backup()`；`core/state.py` 的 `STATE['rows_deleted']`；两个 worker（`run_search` / `run_maps`）的 `finally` 落盘前过滤。
- **核心文件**：`ui/page.html`、`客户开发工具.py`、`core/state.py`
- **实现方法**：
  1. **墓碑而非直接改 `rows`**：结果 Excel 是在 worker 的 `finally` 里用**它自己的局部 `all_rows`**写出的（与 `STATE['rows']` 不是同一个列表，但两者下标对齐）→ 只删 `STATE['rows']` 是**假删除**（那条仍进 Excel / 飞书）。所以删除时往 `STATE['rows_deleted']` 记一笔（该行的 `n`），worker 落盘前 `results = [r for i, r in enumerate(all_rows, 1) if i not in dead]`。**没人删过时这个过滤是恒等的**（对既有测试零影响）。
  2. **`n` 是稳定键**：行号 `n = len(all_rows)`（1 起、本轮内单调递增、不复用），前端 ✕ 带 `data-n`，后端按 `n` 定位。
  3. **四段式锁纪律**（见 §4.3）：①锁内校验 `running and phase=='search'` + 定位 `url` ②锁外 `backup_db_before_delete()` + `db_delete_customer(url)`（**两句已抽成共用 `_delete_customer_and_backup()`**，与 `/api/manual/session/delete` 同源）③锁内 `pop` 该行 + 记墓碑 + 重算 `result_count` ④锁外 `log()`。
  4. **墓碑清零点**：`api_start` + 两个 worker 的开头都要 `STATE['rows_deleted'] = []`（防直调 worker 时跨轮串味 —— 上一轮的墓碑会误杀这一轮同号的行）。
- **与其他模块的关系**：复用 M6 的 `backup_db_before_delete()` / `db_delete_customer()`（与 `/db` 删除同源），复用 M11 的轮询（`poll()` 里算 `liveEditable`）；产出影响 M7（结果 Excel 行数）与 M8（飞书）。
- **依赖**：M6 的删除 + 备份件。
- **是否可复用**：**「墓碑 + 落盘前过滤」**这个模式可复用（任何「运行中允许从 UI 摘掉一条、但真正的落盘发生在另一个局部列表里」的场景）。
- **当前完成状态**：✅ 已投产（2026-10-02 新增，代码已改完 + 单测全绿，尚未 git commit）
- **修改时注意**：
  - ⛔ **必须有 `phase` 门禁**：导出飞书时 `STATE['running']` 仍是 `True` 但 `phase=='export'`，而 `STATE['rows']` 还留着**上一轮**的行 → 此时允许删会删掉「Excel 早已写好」的库行。只有 `running and phase=='search'` 才放行。
  - ⛔ **`n` 必须防 bool**：`isinstance(True, int)` 为真 → `int(True)==1` 会**误删第一行** → 先 `if isinstance(raw, bool): raw = None`。
  - ⛔ **共享样式命名**：`ui/page.html` 的第一段 `<style>` 会被注入 `/manual` `/db`（见 §6.2）→ 新选择器一律加 **`livedel-` 前缀**（`delModal` / `modal` / `btn-danger` / `row-del` / `live-del` 已被别处占用）。R12 有**负向断言**盯着这几个名字不许出现。
  - ⚠️ **增量重画的失效判据**（**M18 起这段在 `ui/live-table.js::render()` 里**）：原先只在 `rows.length < renderedRows` 时清表重画 → 「删 1 条 + 加 1 条」净长度不变会**漏重画**（✕ 停在错行）→ 补一条 `rows[last][key] !== renderedTail`。`reset()` 里 `renderedTail` 必须与 `renderedRows` **一起**清零，否则新开始的一轮可能一直空白。
  - ⚠️ **只删库 + 记墓碑，不动 `MANUAL_STATE` 的内存明细**：若同一轮里该站也在手动采集明细中，要另外去 `/manual` 点 ✕。
  - ⚠️ **竞态窗口**：删库与「worker 落盘」之间有窗口；且**被删的不回填** → 最终 Excel 行数可能 < 目标条数，属预期。刷新页面（`/api/status` 轮询）期间也有短暂不一致。
  - ⚠️ 改 `ui/page.html` 后**必须重启工具**，且**必须重算 R5 两条 sha256**。

---

### M17. 主页「1. 本次任务采集数量」（提为第 1 张卡 + 强必填）

- **功能作用**：本轮最多新增多少个客户（10~100），三条采集链路（标准网页搜索 / 自定义搜索词 / 谷歌地图）共用。**强必填**：清空后点「开始搜索」被前端拦下、零请求。
- **所在位置**：`ui/page.html`（`#targetCount` 卡 + `start()` 读值）；`客户开发工具.py::api_start`。
- **修改时注意**：
  - ⛔ 编号**硬编码在 `<h3>` 里**，插卡/挪卡要**整轮重排**，并同步三处用户可见提示语（`start()` 两条 alert、`#comboSummary` 占位、`#rawCard` 说明）。
  - ⛔ 强必填 = **两道兜底一起删**：前端只许 `el.valueAsNumber`（不许 `|| '10'`）、后端只许 `data.get('target_count')`（不许第二个缺省值参数）。只删一边 = 假必填。R13（AST + 负向）与 `_check_live_ui.py` G 段真机守着。
  - ⚠️ 输入框**仍预填 `value="10"`**（「清空就拦」才是必填的体现）；后端校验**刻意留在产品词校验之后**。
- **当前完成状态**：✅ 已投产（2026-10-02，与 M16 同一批未 commit）。

---

### M18. 「本轮明细」共享组件（主页 + `/manual` 同一张表）

- **功能作用**：主页「📥 本轮已入库明细（实时）」与 `/manual`「③ 本轮采集明细」的**表格渲染 + 逐行 ✕ 删除 + 居中确认框**合并成**一份实现**。两页表头**逐字一致**（9 列，含「行业 / 国家」），✕ 都弹同一个居中模态框（Esc/点遮罩=取消，Enter=确定）。
- **所在位置**：`ui/live-table.js`（工厂 `makeLiveTable(cfg)`，全局只暴露这一个名字）；`core/ui.py` 的 `LIVE_TABLE_JS_PLACEHOLDER` + `_read_live_table_js()` + `_inject_live_table_js()`；两页模板各一行 `<script>LIVE_TABLE_JS_PLACEHOLDER</script>`。
- **为什么要抽**：这两块原是两份近逐字重复的代码，**重复的真实代价已经发生过** —— 主页上一轮修的两处（末行判据、居中确认框）在 `/manual` 上一直没生效，而 `/manual` 的「行业 / 国家」两列主页也没有。
- **两页的差异全部走 `cfg`**：`keyField`（主页 `n` / 手动 `rid`）、`endpoint`、`showExisted`（只有 `/manual` 渲染「已在客户库」痕迹行）、`badgeTitle`（→ `breakdownText`）、`canDelete()`、`editHint`/`readHint`、`afterRemove()`（`/manual` 删完重拉 `loadManualState()`，主页 `poll()`）。
- **⛔ 五条硬约束**（文件头注释里也有）：
  1. **闭包 + 只暴露 `makeLiveTable`**：跨 `<script>` 的顶层 `let/const` 与另一段 `<script>` 里的 `function` **重名 = `SyntaxError: Identifier 'X' has already been declared` → 整段脚本一个字符都不执行 → 症状是「页面控件全空白」**（极易误判成后端挂了）。两页要用的东西走薄封装。
  2. `livedel-*` 类名与 `#liveDelModal` 是**共享**的（写在 `ui/page.html` 第一个 `<style>` 里，由 `PAGE_CSS_PLACEHOLDER` 注入三页）→ 一律硬编码在组件里；**注释里也别写** `/db` 或 `delModal`/`row-del`/`live-del` 那批字面量（R12 的负向断言按**子串**判，写上就假红，这个坑踩过两次）。
  3. 模态框 DOM 由组件在**初始化时**建好（两页不再手写标记）→ 所以**组件必须先于各页自己的脚本执行**（模板里就是这么排的）。也顺带避开「JS 要取的节点必须在脚本之前」那个老坑。
  4. **两张表的外部契约一个字都不能改**：轮询接口、删除接口路径、请求体的键、返回体字段名（`ok/deleted/rows/backup/msg`）都被回归脚本按名断言。
  5. 改 `ui/live-table.js` 后**必须重启工具**（`PAGE_HTML`/`MANUAL_HTML`/`QUERY_HTML` 在 import 期构建一次）；旧实例打新路由是 404。
- **回归怎么守**：`_check_page.py` R12 现在**同时**断言「同一份组件文本在 `PAGE_HTML` 与 `MANUAL_HTML` 里都出现」+「两页 `<thead>` 逐字相等」→ **只改一页立刻红**；`_check_live_ui.py` 按真实 DOM 断言 9 列与「行业/国家」两列的**数据**（只加表头不加单元格 = 空列，看不出来）；`_check_manual_ui.py` E 段改为「点 ✕ → 等居中模态框 → 点确定删除」。
- **当前完成状态**：✅ 已投产（2026-10-03）；全量回归 23 项 EXIT=0；尚未 git commit。
- **已知未做（拍板推迟到下一轮）**：主页**暂不**显示「已在客户库」痕迹行（`showExisted:false`）。要补的话不是前端改个开关就行：需要 ① `run_search`/`run_maps` 的跳过分支记 `{kind:'existed', …}` ② **另开一个 key 空间**（不能混进 `STATE['rows']`，否则 `n == len(all_rows)` 的对齐与墓碑全乱）③ `/api/live/delete` 的 `{n}` 契约放宽 ④ 重新定义 `result_count` 口径。

---

### M19. 「本轮明细」计数改报两组数（有效数 / 采集总数）

- **功能作用**：扩展面板与 `/manual` 的「本轮采集明细」徽章、状态行**不再只报一个「已采 N 条」**（那＝总数，会把「已在客户库」的重复也当成成功数），改成同时报**两组数**：
  - **有效数** ＝ 真正写进客户库、也写进结果 Excel 的新客户 ＝ `st.added`。
  - **采集总数** ＝ 本轮明细行数 ＝ `session_rows.length` ＝ 新增 + 已在库。
- **所在位置**：`ui/live-table.js`（新增可选 `cfg.badgeText(st, n)`，默认 `n + ' 条'` → 主页行为一字不变）；`ui/manual.html`（`liveBadgeText()` + `renderSessionStatus()` + `breakdownText()` + 徽章初始文案）；`extension/popup.js`（`renderSession` 的徽章 / 悬停 / 状态行）+ `popup.html` 徽章初始文案。**后端一行没动** —— `added`/`existed`/`session_rows` 本来就自洽，删除路由已按 `kind` 回退计数。
- **⚠️ 为什么 `badgeText` 走 `cfg` 而不是硬编码**：共享组件同时服务主页（`showExisted:false`，只有新增 → 报「N 条」就够）与 `/manual`（`showExisted:true` → 要两组数）。硬编码会连主页一起改，而用户这次明确「只改扩展面板 + `/manual`」。`reset()` 也会调 `badgeText(null, 0)` → 回调**必须能在 `st` 为 `null` 时安全求值**。
- **回归怎么守**：`_check_page.py` R7 逐字清单换成本次新文案 + `badgeText:` 那一行；`_check_manual_ui.py` E 段断言徽章 == `有效 2 / 共 3`、状态行含 `有效 2 · 采集总数 3 · 已在库 1`，并新增 `liveBadgeText(null, 0)` 纯函数断言；`_smoke_ext_popup.js` 四处徽章文案断言同步。
- **⚠️ `_BUILT_SHA` 要重算、`_TMPL_SHA` 不用**：组件正文被注入构建结果 → 只有 `_BUILT_SHA` 变（`ui/page.html` 模板本身没动）。
- **当前完成状态**：✅ 已投产（2026-10-10）；全量回归 23 项 EXIT=0；尚未 git commit（与 M16/M17/M18 同批）。
- **已知未做**：主页「📥 本轮已入库明细（实时）」的徽章仍只报「N 条」—— 用户这次明确只要改扩展面板与 `/manual`；且主页那张表 `showExisted:false`，N 本来就是有效数，口径已经对齐。

---

## 4. 核心实现方式

> 只记「怎么实现」，不贴代码。

### 4.1 数据如何流转

```
                        ┌──────────────────────────────────────────┐
  用户填表单            │  run_search（谷歌网页搜索） ★当场入库     │
  ↓                    │   run_maps（谷歌地图名录）  ★当场入库     │
Flask /api/start ──────┤   collect_from_html（手动采集/扩展）☆入库延后│
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

> ★ 自动两条链路：`db_upsert_customer()` 就在「逐条」这一步。
> ☆ 手动采集（2026-10-11 起）：这一步**不写库**，入库被推迟到「整轮结束」——
>    `_flush_manual_session()` 先逐条 `db_upsert_customer()`，成功后才 `_save_enrich_excel()`。

**关键点**：
- **手动采集（`collect_from_html`）**：`_manual_row()` **不写库**，只在内存攒 `session_rows`；
  入库发生在用户点「🏁 结束并生成 Excel」时的 `_flush_manual_session()`（先 `db_upsert_customer` 再落 Excel）。
  2026-10-11 改 —— 动机是「把国家/行业填错的那一轮可以直接丢掉，不污染客户库」。
- **自动两条链路（`run_search` / `run_maps`）**：仍是**采集当场**写 SQLite；Excel 是**整轮结束时**才落盘。
- 手动采集的「本轮明细」决定 Excel 有哪些行；Excel **只写新增**。
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
| `STATE` | `core/state.py` | **自动链路**（搜索 / 地图 / 导出）的运行状态：`running/phase/logs/result_count/rows/rows_deleted/done/output/stop`（`rows_deleted` = 本轮在首页被逐行删掉的 `n`，落盘前过滤用，见 **M16**） | `GET /api/status?since=N`（增量拉日志） |
| `MANUAL_STATE` | `core/state.py` | **手动采集**专用：批量任务子状态（running/stop/total/done/current）+ 本轮会话语义（session_* / added/existed/failed/upgraded）+ 扩展心跳（ext_last_seen） | `GET /api/manual/state`（还附带最近 50 条手动采集记录） |
| `STATE_LOCK` | `core/state.py` | 两套状态**共用同一把** `threading.Lock`（**非可重入**） | — |

**为什么手动采集不复用 `STATE`**：`STATE['stop']` 是自动链路的开关，共用会让「停止手动采集」把正在跑的自动搜索一起杀掉。

### 4.3 锁纪律（全项目最硬的一条）

`STATE_LOCK` **不可重入**，而 `log()` 内部也要抢同一把锁。因此：

> **任何 `log()` 调用必须在 `with STATE_LOCK` 块外；DB IO 与文件 IO 一律在锁外。**

横切一切写状态的地方（`_flush_manual_session`、`_manual_batch_worker`、`api_manual_session_delete`、`api_live_delete` 都踩过这个坑）。标准骨架（四段式）：

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

- **无框架、无构建**。Python 在 import 期读 `ui/*.html`，把数据以 JSON 注入 `*_PLACEHOLDER`，结果整页返回。**注入的既可以是数据，也可以是「共享代码文本」**：`<style>` 走 `PAGE_CSS_PLACEHOLDER`（从 `ui/page.html` 抽给 `/manual` `/db`），`ui/live-table.js` 走 `LIVE_TABLE_JS_PLACEHOLDER`（从独立文件注入主页与 `/manual`）。两种都发生在 **import 期** → 改完**必须重启工具**。
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
| `clean_emails()` / `clean_phones()` | `客户开发工具.py` | 邮箱/电话抽取 + 误报过滤（`_is_noise_email()` 走 `NOISE_EMAIL_TLDS` / `NOISE_EMAIL_HOSTS` / `NOISE_EMAIL_DIM_RE` / `NOISE_EMAIL_HEX_RE` 四组常量；宿主用**后缀**匹配，不是子串） |
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
| `db_delete_customers_by_ids(ids)` | `core/db.py` | **按主键批量删的干净实现**：非正整数丢弃 + 去重 + 空列表直接返回 0（内建「不清库」门）；配合 `backup_db_before_delete()` 就是一套完整的「安全删除」 |
| `run_search(..., raw_queries=[...])` | `客户开发工具.py` | **「用户手写完整查询、绕开模板」的开关**：`custom_mode` 一开，查询词原样发出（不拼任何东西），并把 `china_filters` 置空。任何「让用户直接控制查询串」的场景都能复用这个形态 |
| `query_export_dir()` / `ts_query_export_path()` | `core/paths.py` | 导出落「专用子目录 + 时间戳去重」的骨架（配合「别让产物混进会被扫描的目录」这条经验） |
| `标注空行业.py` | 项目根 | **「把某列为空的记录批量补一个值」的脚本骨架**：默认 dry-run 打印将改的 id 清单 → `--apply` 才写库（写前 sqlite 在线 backup）；`--exclude-id` 可挑掉几条。`重标行业.py` 是它的「改名」孪生兄弟 |
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
| 事件委托删除行 | **`ui/live-table.js::onClick`** + `extension/popup.js::onSessionListClick` | 行是 innerHTML 拼的、会整表重建 → **只能**委托 |
| 「一个共享组件服务多个页面」的注入式共享 | `core/ui.py::_inject_live_table_js()` + `ui/live-table.js` | 独立 `.js` 文件 + `LIVE_TABLE_JS_PLACEHOLDER`（与 `<style>` 注入**同构**）：两页差异全走 `cfg`，页面各留薄封装 → 根治「两份近逐字重复的代码，改一边传不到另一边」。⛔ 全局只许暴露工厂名（跨 `<script>` 重名 = 整页空白），详见 M18 |
| 「facets 驱动的筛选面板」模式 | `ui/query.html::loadFacets()` | 勾选项全部由后端 distinct 接口生成，页面里零硬编码枚举 —— 将来新增行业/来源，页面一个字都不用改 |
| 「查询条件 → 导出」一整套 | `ui/query.html` + `/api/db/*` | 换张表/换个库就能复用的筛选+分页+导出页面，是目前项目里最完整的一个 CRUD 只读视图 |
| 「勾选 + 单行 ✕ 双入口同一接口」删除模式 | `ui/query.html::deleteRows()` / `selectedIds()` / `syncSel()` | 单行就是长度为 1 的数组 → 只有一个后端路径，不会出现「批量删才备份」这类分支漏洞；`ckAll.indeterminate` 处理半选态 |
| 「删除前二次确认 + 说清后果」文案 | `ui/query.html::deleteRows()` | `confirm()` 里写明：不可撤销 / 已自动备份 / 对本轮明细的影响 —— 删数据的确认框必须把代价讲明白 |
| 「按行取多行文本 → 与后端同规则」的小函数 | `ui/page.html::rawQueries()` / `productQueries()` | `split('\n') → trim → filter(Boolean)`；**预览与实搜必须走同一个函数**，否则用户照预览抄下来的词与实际发出去的不符 |
| 「预览按模式选分支」结构 | `ui/page.html::renderCombos()` | 地图分支 → 自定义分支 → 标准分支，各自 `return` 掉；新加一种查询来源时就在这儿插一段，比在渲染里塞 if 清晰 |
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

### 6.6 为什么删除要「删明细时按需删库 + 删前备份」

- **按 `rid` 删**（`/manual`）：同一 url 在一轮里可能既有 `added` 又有 `existed`。
- **手动链路默认不删库**（2026-10-11 改）：手动采集的行**本轮还没入库**（入库在「结束」那一刻）
  → 删它只是把它从「待入库清单」里拿掉，客户库本来就没有、也不该平白备份一份。
  灰字 `kind='existed'` 行是**别人早采过的老客户**，同样绝不连带删库。
- **唯一的例外（必须双删）**：`kind='added'` **且** `db_has_customer(url)` 为真 —— 来源是
  「本轮已入库成功、但结果 Excel 被占用没写成功」那种按「失败不清数据」保留在明细里的行。
  这时库里确实有它 → 只删内存仍会退化回**假删除**（下次采到同站被判「已在客户库」跳过、
  **永远采不回来**，飞书导出也仍会带它）。判据刻意写成「`kind='added'` and 库里真有它」。
- **顺带守住的不变量**：入库排在写表**之前**，所以「结果 Excel 里出现过的行，客户库里一定有」——
  这正是「下次再采到同站不会被当成新客户重复进表」的前提。
- **按主键 `id` 删**（`/db` 查询页）：查询结果每行都带着主键，主键无歧义，不存在「键错位删错人」；两条路都**不做 email 兜底**（email 兜底是 upsert 的合并口径，用它来删会删到「被合并进来的另一家」）。
- **删前备份**：不可逆操作；用 sqlite3 在线 `backup()`（WAL 下裸拷贝会漏数据）。两条路共用 `backup_db_before_delete()`（300 秒节流）。
- **「不清库」的门**：两条路的入口都必须能挡住空 key / 空 id —— `db_delete_customer('')` 与 `db_delete_customers_by_ids([])` 都**直接返回 0**。少了这道门，一次空输入就等于 `DELETE FROM customers`。
- ⚠️ `/db` 的删除**不清理 `MANUAL_STATE` 的内存明细**：若本轮采集正在进行，被删那条仍会进本轮结果 Excel，要一并拿掉得回 `/manual` 点那行的 ✕（刻意不跨模块改内存态，否则查询链路就得持 `STATE_LOCK`）。

### 6.7 为什么 Excel「只写新增」，不写「已在库」

避免导出飞书时重复推送同一家公司。**代价**是「采集总数」>「有效数（＝Excel 行数）」。用户拍板维持这个行为，但要求 UI **把两组数一起报出来**（`有效 X / 采集总数 Y`）—— 这是后续必须一直守住的约定。

### 6.8 为什么 `website_key` 必须恒等于 `normalize_domain(website)`

`db_has_customer()`（判跳过）只查 `website_key`，`db_upsert_customer()`（写入）按键查不到会按 email 兜底合并。两者口径本就不一致，靠**「键与网址严格对齐」**这个不变量把缺口补上。破了就会出现「同一个站反复进 Excel、库里只有一条」。修复能力：`db_fix_website_keys()` + upsert 内的键自愈 + 回归项 `_check_db_keys.py`。

### 6.9 ⛔ 为什么「公开 GitHub 仓库」是个必须记住的事实

`origin = https://github.com/jurryzhang66/waimao.git`，**public**（用户在我的风险说明之后仍明确同意）。里面已包含：
- `DB/客户库.sqlite3`（真实客户 303 条 / 200 邮箱 / 99 电话）
- `output/` 结果表、`DB/backups/` 快照
- **飞书 `BASE_TOKEN`**（`core/state.py`、`同步数据库到飞书.py`、`回填行业.py`）

**推过就删不干净**。要收口只能 `git filter-repo` 重写历史 + 强制推送 + **轮换飞书 token**。
**结论：以后往仓库里加任何敏感文件前，先想清楚这一步。**

### 6.10 其他已定下的约定

- **标签全部用附注标签**（`git tag -a -m`），新版本照做。查标签先 `git tag -l`。
- **V1.4 起不再往记忆文件里写提交 hash**（该提交里就含记忆文件，写 hash 得再 amend、amend 又换 hash，永远差一位）→ 一律 `git rev-parse "V1.4^{commit}"`。
- **10 列硬契约**不可改（见 §7 相关注意事项）。
- **自动搜索的两条链路一次性把结果落到「最新结果文件」**，手动采集则一轮一份 —— 两套语义刻意不同。
- 国家筛选**默认**只用 `gl` / `hl`；`cr` 与 `site:` 做成**默认关**的可选开关（**M15**）。`lr` 仍不加。2026-09-28 实测：法国加 `cr` 后条数 10→7、`.fr` 占比反降、真客户被挤掉（法国 B2B 多用 `.com`）→ 故**默认关**。

### 6.11 为什么把两页的「本轮明细」抽成一个共享组件（M18）

主页「📥 本轮已入库明细（实时）」与 `/manual`「③ 本轮采集明细」在**数据来源上确实不同**（一个是自动链路的 `STATE['rows']`，一个是手动会话的 `session_rows`、还多一类「已在客户库」痕迹行），所以最初是各写一份。**但两份代码是近逐字重复的**，而重复的代价已经真实发生过：主页上一轮修的两处（末行判据 `renderedTail`、删除确认改居中模态框）**一直没传到 `/manual`**，而 `/manual` 的「行业 / 国家」两列主页也没有 —— 于是「同一件事在两个页面表现不一样」成了常态。

抽法上做过三个取舍：

1. **不是「把页面的能力合并到一起」，而是「一份实现 + 每页一份配置」**。差异全部收敛进 `cfg`：主键字段（主页 `n`、手动 `rid`）、删除接口、是否渲染「已在客户库」痕迹行、徽章悬停文案、可删条件、提示语、删完的回调。**共性（9 列表头、✕ 弹居中模态框、增量重画判据、事件委托）一行都不用抄两遍。**
2. **共享的是 `ui/live-table.js` 这个独立文件，不是「写进某一页再抠出来」**：`ui/page.html` 自己的注释就警告过「抠 `<script>` 的正则很脆」；而 `<script src>` 又会撞掉所有按 `m.PAGE_HTML` 做逐字子串的断言（项目也没有 `static/` 目录）。最终复用**已有**的注入机制形态：新增 `LIVE_TABLE_JS_PLACEHOLDER`，由 `core/ui.py` 在 import 期把文件内容替换进去 —— 与 `<style>` 的 `PAGE_CSS_PLACEHOLDER` 完全同构，三条断言（组件文本两页都在、两页表头逐字相等）自然就有了落脚点。
3. **后端那半边也一起抽**：两个删除接口的「先备份 + 再删库」是同构的 `backup_db_before_delete()` + `db_delete_customer(url)`，抽成 `_delete_customer_and_backup()`，并顺手用 AST 把「它必须在 `STATE_LOCK` 之外被调、体内不许有 `with`」钉死（原先只有口头纪律）。

**代价（必须知道）**：组件改一处、两页同时变 —— 所以「只改一页」这种曾经正常的操作，现在会被 R12 的两页表头比对直接拦下；而组件里的**任何**顶层重名都会让**两页一起**白屏（见 §9.2 #38）。

---

## 7. 已知问题

> 都是**目前存在、暂未解决**的问题。改相关代码前先看这一节。

### 7.1 搜索链路

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 1 | **「结果没渲染」两种成因日志分不开**：① 谷歌返回壳页面（重开能好）② 谷歌**零结果页**（`did not match any documents`，重试同 URL 无效）。触发场景 = 冷会话的第一个谷歌请求 + 重公式（33 词） | `open_search()` / `wait_results()` | 排查时容易误判为 bug。**修法未拍板**。取证图 `.workbuddy/_fail_q1_p0.png` |
| 2 | **冷会话首请求被降级** | 同上 | 同上，是 #1 的成因之一 |
| 3 | 谷歌限流：连返壳页面 → 重试失败跳页 | `run_search` | **等 90 秒**恢复。别当 bug。 |
| 3b | **`country_limit` 的 `cr` 在 `open_search` 兜底轮会丢**：最后一轮 `type_search` 走的 `country_params` 不含 `cr` | `open_search()` | 仅壳页面兜底轮丢 `cr`（`gl`/`hl` 本该也不含）。`site:` 在 formula 里，**不会丢**。已知、**暂接受** |

### 7.2 评分与行业

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 4 | ⛔ **评分在非英语场景方向是反的**（20 条法国结果实锤）：`CTYPE_WORDS` 全是英文（`wholesale/distributor/…`），法语 `grossiste/distributeur/fournisseur` 一个不认；且 `score_item()` **只有加分无减分** | `客户开发工具.py` 第 526/653 行 | 法语/德语等市场会把真正买家判成低分。**未修**。根治三件事：① `CTYPE_WORDS` 多语言化 ② `PRODUCT_WORDS` 按本轮产品词动态传入 + 加词边界 ③ 加否决/减分项（`.gov` / 点评站 / 餐馆 / 菜谱 / B2B 名录 / 新闻） |
| 5 | `PRODUCT_WORDS` 写死猫砂垫词表且**子串匹配无词边界** | `客户开发工具.py` 第 527 行 | 换行业必须同步改（已开可选入参缓解，但自动链路未传） |
| 6 | 行业取值历史上有两套口径（`家具家居` / `汽配`） | `重标行业.py` | 已提供重标脚本，**待改 23 条**（dry-run 已备） |
| 6b | ~~**行业为空 24 条**（`未标注`）~~ **✅ 2026-10-02 已处理完**：`/db` 勾选删掉 7 条平台页/误采（`127.0.0.1`、`erp.91miaoshou.com`、mercadolibre ×2、`bodegaaurrera`、`tripadvisor`、`amazon.com.mx`），310→303；再用 `标注空行业.py --apply` 把剩余 17 条标成「食品」，行业为空 24→**0** | `标注空行业.py`(+`_smoke_annotate.py` 33 项) + `/db` 删除 | 已执行；备份 `DB/backups/客户库_删除前_20261002_083924.sqlite3` 与 `DB/客户库.sqlite3.bak_标注空行业_20261002_083932` |

### 7.3 数据质量

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 7 | 库里混着平台/垃圾域名（joybuy / dreamstime / chegg / thomasnet / trendyol / u-buy / petz.ae / suppliergo / archive.org / tiktok，以及 `drive.google.com`、`linkfly.to`）约 25–38 条 | `DB/客户库.sqlite3` | 导飞书会带垃圾。**现在有三种删法**：① 本轮明细点 ✕；② `/db` 筛出来勾选删；③ 按 id 直接删。删除前都会自动备份 |
| 8 | 用户自采记录里 `127.0.0.1`（误点工具自己的页面）与 `erp.91miaoshou.com`（SaaS 平台）是明显误采 | 同上 | ✅ 2026-10-02 已随 §7.2 6b 一并删除 |
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
- 飞书「客户信息」表的「来源渠道」**需要人工**加 `手动采集` 选项（否则导出时该值会被降级成「谷歌搜索」）；「行业」选项也还是旧四值（缺 `食品` 之外的新规范名）。
- `chrome://extensions` 加载扩展、装/改扩展后刷新已开页面（人工步骤）。
- **M16 / M17 / M18（第九～十一轮）尚未 git commit**；此前八轮用户已自己提交（「备份1」`f69f1af` = `v1.5`、「备份2」`d332048` = `v1.5.1`，都是**轻量标签**）。这三轮是否一并提交 / 推远端待拍板。

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
| 计数报两组数（有效 X = 新增 / 采集总数 Y = 新增 + 已在库）（**M19**） | ✅ |
| 客户库查询页 `/db`（多维筛选 + 分页 + 导出 Excel + **勾选/✕ 删除客户** + 居中模态框二次确认） | ✅ |
| 主页「7. 自定义搜索词」（**M14**：原样搜、不套条件模板、不做中国过滤、国家只做标记） | ✅ |
| 主页「国家限定」四选一（**M15**：`none`/`cr`/`site`/`both`，默认关、仅标准网页模式） | ✅ |
| 主页「本轮已入库明细（实时）」逐行删除（**M16**：仅采集中可点、居中模态框确认、墓碑保证「不进本轮 Excel」） | ✅ |
| 主页「1. 本次任务采集数量」提为第 1 张卡 + **强必填**（**M17**：原 1~6 号整体顺延、三条链路统一、清空即拦且零请求） | ✅ |
| 主页 + `/manual` 的「本轮明细」合并成**一个共享组件**（**M18**：`ui/live-table.js`，两页表头逐字一致含「行业/国家」、✕ 共用一个居中模态框；`/manual` 的原生确认框就此消失） | ✅ |
| 首页顶栏导航（→ `/manual`、`/db`，V1.5 加） | ✅ |
| 数据修复脚本（`重标行业.py` / **`标注空行业.py`**） | ✅ |
| 项目拆包（`core/` + `ui/`） | ✅ |
| 23 项全量回归 | ✅ |
| git V1.4 提交 + 推 GitHub | ✅ |

### 8.2 正在开发 / 刚完成未提交

- **最近一轮（第十一轮）**（把主页与 `/manual` 的「本轮明细」抽成共享组件 = **M18**：新增 `ui/live-table.js`（工厂 `makeLiveTable(cfg)`，两页差异全走 cfg）+ `core/ui.py` 加 `LIVE_TABLE_JS_PLACEHOLDER` 注入（与 `<style>` 注入同构）+ 主页表补齐「行业 / 国家」两列、两页各留薄封装，主页那 46 行 `renderRows` 与整套模态框代码、`/manual` 的 `renderSession` 与原生 `confirm` 一并删除；后端把两个删除接口的「先备份 + 再删库」抽成共用 `_delete_customer_and_backup()`；`_check_page.py` **R12** 改为「两页表头逐字相等 + 组件文本两页都在」并把 AST 断言重定向到新 helper、`_check_live_ui.py` **F 段**加「9 列 + 行业/国家数据」真实 DOM 断言、`_check_manual_ui.py` **E 段**改成「点 ✕ → 等居中模态框 → 确定删除」、`_smoke_search.py` 修掉一处「备份名同秒重名」的**假红**）：**代码已改完、23 项回归全绿、真机截图存档，尚未 git commit**。
- 再往前一轮 = **M17**（把「本次任务采集数量」提成「1.」独立卡并改成**强必填** = `ui/page.html` 插入新卡 + 整轮重排编号（原 1~6 → 2~7）+ `start()` 去掉兜底默认值改 `valueAsNumber` 且校验提到最前、`客户开发工具.py` 的 `api_start` 对缺键/空串**显式拒绝**；`_check_page.py` R5 基线重算 + 新增 **R13**、`_smoke_search.py` 6 处 payload 补字段 + 必填负向断言、`_check_live_ui.py` 新增 **G 段**真机）：**尚未 git commit**。
- 再往前一轮 = **M16**（主页「本轮已入库明细（实时）」逐行删除 = 墓碑 `STATE['rows_deleted']` + `POST /api/live/delete` + 居中模态框；`_check_page.py` **R12**、`_smoke_search.py` 两段、`_check_live_ui.py` **F 段**）—— 同样**尚未 commit**。
- 更早的八轮（① 计数口径拆分 + 去重键不变量；② 客户库查询页 `/db` + 2 个新回归项；③ 扩展面板「客户库查询」入口；④ 主页顶栏导航；⑤ `/db` 结果删除 + `标注空行业.py`；⑥ `/db` 删除确认改居中模态框；⑦ 主页「7. 自定义搜索词」= **M14**；⑧ 主页「国家限定」四选一 = **M15**）**已由用户自己提交**（见 §8.4：提交「备份1」`f69f1af` = 轻量标签 `v1.5`、「备份2」`d332048` = 轻量标签 `v1.5.1`；`v1.5.1` 已含 M14 + M15 + 顶栏导航）。
- ⚠️ **用户会自己动手做备份提交**，信息固定为「备份N」、打的是**轻量标签**（`v1.5` / `v1.5.1`，**不是** `V1.x` 那种 `-a -m` 附注标签）→ 查「某轮落在哪个提交」要 `git tag -l` + `git for-each-ref refs/tags` 对照，**别只认大写 `V1.x`**。M16 / M17 / M18 是否要一并提交 / 推远端，等用户拍板。

### 8.3 未完成

- §7 全部已知问题。
- §7.5 全部待办。
- 阶段 B 拆包（`google_search` / `google_maps` / `tasks` / `feishu`）。

### 8.4 数据现状（2026-10-02 实测）

| 项 | 值 |
|---|---|
| 客户库总条数 | **303**（还在涨 —— 用户随时在用扩展采，别拿固定数字当基线） |
| 按来源 | 谷歌搜索 214 / 手动采集 82 / 谷歌地图 7 |
| 有邮箱 | 200 |
| 有电话 | 99 |
| 有联系页 | 36 |
| 行业为空 | **0** —— 2026-10-02 已处理完：先删 7 条平台页/误采（310→303），再把剩余 17 条批量标成「食品」 |
| 行业分布 | 食品 197 / 宠物用品 67 / 家具家居 18 / 户外用品 10 / 汽配 5 / LED照明 5 / 机械零部件 1（合计 303） |
| 评分/评级为空 | 8 条（两者同一批） |
| 结果 Excel | `output/` 22 份 |
| 查询导出 | `output/查询导出/`（用完可删，已 gitignore） |
| 库备份 | `DB/backups/` 7 份（清理前 / 污染前 / 删除前 ×N / 修键前）；另有 `DB/客户库.sqlite3.bak_标注空行业_20261002_083932` 1 份 |
| git | `main` 最新提交 `d332048`「备份2」（**M16 / M17 / M18 尚未提交**）；**用户自建**轻量标签 `v1.5`=`f69f1af`「备份1」、`v1.5.1`=`d332048`「备份2」；附注标签 V1.0～V1.4 |

---

## 9. AI 开发注意事项

> 这一节是给「下一次接手这个项目的 AI」的。

### 9.1 动手之前

1. **先看 §3 找到对应功能模块**，再去看那一节指向的具体源文件 —— 不要一上来就全库 grep。
2. **本项目注释密度极高，坑都写在注释里**。改任何函数前，先读它上面的 docstring 和 `⚠️` 注释。很多「看起来多余」的写法都是有实测原因的。
3. **修改前先寻找现有实现**：§5「可复用功能」列了全部可复用件。本项目最常见的浪费就是重复实现已有能力（比如又写一个「抓邮箱」或又写一个「备份数据库」）。
4. **不要在不了解现有实现的情况下重构**。特别是：
   - ⚠️ `ui/page.html`（有 sha256 基线：故意改要**同步**重算 R5 的 `_TMPL_SHA` / `_BUILT_SHA`）
   - ⛔ `ui/live-table.js`（**两页共用的「本轮明细」组件**：改一处同时影响主页与 `/manual`；全局只许暴露 `makeLiveTable`，见 M18 / §9.2 #37~#40）
   - ⛔ `run_search` / `run_maps`（跑通的链路，回归守着）
   - ⛔ Excel 的 10 列契约
   - ⛔ `website_key` 不变量
5. **不要随意改变已经确定的架构**（拆包的分层、状态管理与锁纪律、扩展的「唯一 fetch 出口」、端口不写死）。
6. **⛔ 不要主动去读 `output/` 与 `DB/backups/` 里的内容**（用户 2026-10-02 明确要求）：这两个是**运行产物目录**，与代码改造几乎无关，内容随时在变（用户自己也在清理）。列举文件名/条数当「环境体检」尚可，**逐个读文件内容、比对哪份不见了 = 纯浪费上下文，还会引发假警报**（本轮收尾就因为发现 `DB/backups/` 少了 6 份、`git status` 冒出 7 个 `D`，花了好几轮排查，最后结论是「用户自己清的、与程序无关」）。**只有用户明确要求看某一份，或要复现数据库问题时，才去读它们。**

### 9.2 最容易犯的错（按踩坑频率排序）

| # | 错误 | 正确做法 |
|---|---|---|
| 1 | 在 `with STATE_LOCK` 里调 `log()` → **死锁** | `log()` 与 DB/文件 IO 一律在锁外（四段式骨架见 §4.3） |
| 2 | 用 `shutil.copy2` 备份 SQLite | 必须用 `sqlite3` 在线 `backup()`（WAL） |
| 3 | 改 `extension/` 或 `ui/*.html` 后以为立刻生效 | 重启工具 + `chrome://extensions` 点「重新加载」 |
| 4 | 改了 `ui/page.html` 却忘了重算 R5 基线 | 改它没问题，但必须**同时**更新 `_TMPL_SHA` 与 `_BUILT_SHA`（漏一条就红）。给副页面加**专有**样式仍要写进 `ui/manual.html` / `ui/query.html` 的第二个 `<style>` —— page.html 那份是三个页面共用的 |
| 5 | 按 url 删明细行 | 必须按 `rid` |
| 6 | 只删明细不删客户库（**自动链路**，或手动那条「已入库但 Excel 没写成功」的保留行） | 那种情况必须**双删**，否则是假删除；手动的普通行与灰字行则**不许**动库 |
| 7 | 让 `popup.js` 直接 `fetch` | 必须经 `chrome.sendMessage` → background 代发（0 次 `fetch(` 是硬断言） |
| 8 | 让明细行数 = Excel 行数 | Excel **只写新增**；UI 必须把「有效数 / 采集总数」两组数一起报出来 |
| 9 | 用 `from core.paths import ENRICH_FILE` | 它是唯一会被重新赋值的模块级变量 → 一律 `paths.ENRICH_FILE` |
| 10 | 在 `core/` 里用相对导入 / 在入口用相对导入 | 入口只能**绝对导入**（外部脚本无包上下文） |
| 11 | 并行 Edit 同一个文件 | 会静默覆盖，串行改 |
| 12 | 回归脚本打桩后忘了护栏 → 写进真实库 | `m.db.db_path = <tmp>` + `_under_tmp()` 自检 |
| 13 | 拿固定条数当回归基线 | 用户在用扩展持续采集，**按 source 分布 + 测试域名残留**复核 |
| 14 | 改 `PREFERRED_PORTS` 忘了同步 `ports.js` | 两边一起改（`_check_ext.py` 有硬断言） |
| 15 | 改国家/条件时动了元组长度 | `COUNTRIES` 是 4 元组、前端按 5 元组注入，改长度会连带炸两处。新增国家相关数据（如 `COUNTRY_LIMITS`）要**另开独立字典**，别塞进 `COUNTRIES` |
| 16 | 写「删除」时没挡空输入 | `db_delete_customer('')` / `db_delete_customers_by_ids([])` 都必须**直接返回 0**；少了这道门，一次空 key / 空 id 就等于 `DELETE FROM customers`（清库） |
| 17 | 在删除接口里图省事用了 `STATE_LOCK` | 全程不持锁（`backup_db_before_delete()` 内部的 `log()` 也要抢它，非可重入 → 死锁）。R9 用 AST 断言钉住了这条 |
| 18 | 前端把每行 ✕ / 勾选框的监听逐行绑 | 行是 `innerHTML` 整表重画的 → 必须事件**委托**到 `#resBody`，否则翻页/重查后按钮全失灵 |
| 19 | 用原生 `confirm()` / `alert()` 做二次确认 | 位置与样式全由浏览器定（贴窗口**顶部**，用户明确嫌不方便）→ 一律用页面自己的居中模态框（`#delModal`）。`_check_page.py` R9 断言整页里 `confirm(` 为 0；⚠️ 别把带括号的 `confirm()` 写进注释，会把这断言撞红。**例外：`ui/manual.html`（约第 408 行「确定删除这一条吗？」）保留原生 `confirm`** —— 用户 2026-10-02 拍板**暂不改**（别主动去改，改它要连带同步 `_check_manual_ui.py` + R7） |
| 20 | 把弹窗/JS 要取的 DOM 节点放在 `<script>` **之后** | 本页脚本是**立即执行的 IIFE**，解析到那一刻就 `getElementById` → 拿到 `null` → 绑事件抛错 → `init()` 整体中断、**筛选面板全空白**（无弹窗报错，极易误判成后端挂了）。**必须放在 `<script>` 之前** |
| 21 | 主动去读 / 比对 `output/` 与 `DB/backups/` 里的文件 | 这两个是**运行产物目录**，内容随时在变（用户在自采、也在自己清理），与代码改造无关。**默认不读内容**，也别因为「少了几份」就当成 bug 去排查（2026-10-02 实测白查了好几轮，用户已确认 `DB/backups/` 少了 6 份、`关键词库.json.bak*`、`客户库.sqlite3.bak_标注空行业_*` **都是他自己删的，与程序/回归脚本无关** —— 别去「恢复」，也别再排查）。只在用户点名要看某一份时才读 |
| 22 | 新增「用户手写查询」这类入口时只放宽**一处**校验 | 同一件事有**三道**门槛：前端 `start()` 的 `if (!products.trim())` 与 `if (source !== 'maps' && !conditions.length)`、后端 `api_start` 的 `if not products`。只改一处 → 用户仍被「请填写产品关键词」挡住（前端过不了就压根发不出请求；后端没改则 400）。**三处一起放宽**（2026-10-02 M14 实测） |
| 23 | 绕开条件模板时把 `cond_list` 留成空列表 | `run_search` 是**双层**循环 `for pq in pq_list: for cname2, tmpl in cond_list:` —— 留空则内层永不进入 → **静默跑 0 条查询**（只在日志里写「本轮新增 0 个网站」，不报错）。给一个占位模板 `[('自定义', '{p}')]` 就能原样复用这套循环，不必另写一套 |
| 24 | 以为 `site:.us` 能筛出美国客户 / 把 `site:` 当「限国家」 | `site:` 是**限域名**，靠 ccTLD 与国家强绑定才等效，**美国是例外**（`.com` 为主、`.us` 极少）→ M15 里美国 `site` 留空。且 `site:.uk` **能**匹配 `.co.uk`（`site:` 支持 TLD），不必写 `co.uk`。核心认知：**「限定更严 ≠ 更准」**（法国加 `cr` 实测 10→7 条、真客户反被挤掉） |
| 25 | 用 `str(inspect.signature(fn))` 做**文本**断言默认值 | 签名里是**求值后**的 `country_limit='none'`，不是源码文本 `COUNTRY_LIMIT_DEFAULT` → 改用 `sig = inspect.signature(fn); sig.parameters['country_limit'].default == 'none'`（`_check_page.py` R11 踩过） |
| 26 | 回归整体变红就一头扎进业务逻辑查 | 先看**错误类型**：出现 `disk I/O error` / `database or disk is full` / `attempt to write a readonly database` → **先查磁盘剩余空间**。2026-10-02 实测：`C:` 只剩 2.34 GB 时 6 项 DB 相关回归集体假红（临时客户库默认落系统盘 `C:`）。根治 = `_run_all_reg.py` 已把子进程 `TMPDIR/TEMP/TMP` 钉到 `.workbuddy/_reg_tmp`（项目盘），**别再改回系统 TEMP** |
| 27 | 给「运行中可删」的实时明细只判 `STATE['running']` | 导出飞书时 `running` 仍是 `True`、`phase=='export'`，而 `STATE['rows']` 还留着**上一轮**的行 → 允许删会删掉「Excel 早已写好」的库行。**必须判 `running and phase=='search'`**（2026-10-02 M16） |
| 28 | 整表增量重画只按「长度变小」判失效 | 「删 1 条 + 加 1 条」净长度不变 → **漏重画**（行内 ✕ 停在错行）。补一条 `rows[last].n !== renderedTail`；且 `start()` 里 `renderedTail` 必须与 `renderedRows` **一起**清零，否则新一轮一直空白（2026-10-02 M16） |
| 29 | 给「结果落盘前过滤」加了墓碑，却只在 `api_start` 清零 | 直调 worker 的路径不会经过 `api_start` → 上一轮的墓碑**跨轮误杀**这一轮同号的行。**两个 worker 的开头也要清 `STATE['rows_deleted'] = []`**（2026-10-02 M16） |
| 30 | 往 `ui/page.html` 共享 `<style>` 里加「通用名」选择器 | 那份 CSS 被注入 `/manual` `/db` → `.modal` / `.btn-danger` / `.row-del` / `.live-del` / `#delModal` 全是别处已占用的名字，撞了会静默改外观。**新选择器一律加专属前缀**（本轮用 `livedel-`），`_check_page.py` R12 有**负向断言**盯着这些名字不许出现 |
| 31 | 用 `int(raw)` 解析前端传来的行号 `n` | Python `isinstance(True, int)` 为真 → `int(True) == 1` → **误删第一行**。解析前先 `if isinstance(raw, bool): raw = None`（2026-10-02 M16） |
| 32 | 用 `ast.Name` 断言「代码里用了 `STATE['xxx']`」 | 字典取值是 `ast.Subscript`（`value` 为 `ast.Name('STATE')`、`slice` 为 `ast.Constant`），**不是** `ast.Name`。写个小助手收集 `STATE[...]` 的常量键再断言（`_check_page.py` R12 踩过） |
| 33 | 做「必填」时只删了**一处**兜底默认值 | 前端 `parseInt(x.value \|\| '10')` 与后端 `data.get('target_count', 10)` 是**两道独立的兜底**，删一边等于没必填（另一边照样静默补默认值）。**两处一起删**，并各留一条负向断言（`_check_page.py` R13 用 AST 断言后端那侧没有第二个参数） |
| 34 | 挪动/插入主页卡片后只改了 `<h3>` 里的编号 | 编号还会出现在**用户可见的提示语**里：`start()` 的两条 alert、组合预览的占位文案（`#comboSummary`）、`#rawCard` 的说明段。漏改**不报任何错**，只是提示语指到错的步骤。R13 + `_check_live_ui` G 段一起守 |
| 35 | 搬走一个代码块时顺手「润色」了里面的文案 | 页面里有些文案是**别处断言的锚点**（例：`_check_page.py` 的 `expects` 里有 `'按新增个数计'`，它就在被搬走的采集数量 `.note` 里）。搬迁时文本要**逐字保留**，只改位置 |
| 36 | 用 `parseInt(el.value)` 读数字输入框 | 空串 → `NaN`（这条对了），但 `parseInt('1e2') === 1`，而数字框里 `1e2` 是合法的 100。**一律用 `el.valueAsNumber`**（空/非法得 `NaN`，语义与输入框一致） |
| 37 | 把「两个页面共用的 UI」塞进**其中一个页面的模板**里共享 | 想在 `ui/page.html` 里写一段 `<script>` 再正则抠出来注入另一页 → 抠 `<script>` 的正则极脆（页面自己就警告过这一点），而且它本来就住在某个消费者的模板里。**正解：独立文件 + 新占位符**（`ui/live-table.js` + `LIVE_TABLE_JS_PLACEHOLDER`，与 `<style>` 的 `PAGE_CSS_PLACEHOLDER` 注入机制同构）；也别用 `<script src>`（会撞掉所有按 `m.PAGE_HTML` 做**逐字子串**的断言，且项目没有 `static/` 目录）（2026-10-03 M18） |
| 38 | 共享组件里用顶层 `let/const`，页面里又有同名 `function` | 跨 `<script>` 的**顶层 `let/const` 与另一段脚本里的 `function` 重名 → `SyntaxError: Identifier 'X' has already been declared`**。静态检查（`node --check`）只查单段脚本，抓不到跨段冲突；而浏览器是**整段脚本一个字符都不执行** → 症状是「页面控件全空白」，极易误判成后端挂了。**组件一律闭包，全局只暴露一个工厂名**（`makeLiveTable`），两页各留薄封装（2026-10-03 M18） |
| 39 | 用「备份目录里文件名的集合差集」断言「删前备份发生过」 | `backup_db_before_delete()` 的备份名**只精确到秒**（`客户库_删除前_%Y%m%d_%H%M%S`）→ 同一秒内删两次，第二次**直接覆盖同名文件** → 差集是空的 → **假红**（`_smoke_search.py` 实测踩过：段④ 与前一段「运行中删除」落在同一秒）。改判「接口返回的那个文件**这次有没有被写过**」（新增，或 mtime 变新）。⚠️ 生产环境有 300 秒节流，不会撞名 —— 纯**测试侧**脆弱点（2026-10-03） |
| 40 | 泛化/重构后，把「逐字子串断言」当成碰都不能碰的圣旨 | 反过来也错：`ui/live-table.js` 一到位，`fetch('/api/live/delete')` 整串就不存在了。**该改的是断言而不是代码** —— 拆成「页面的 cfg 里确实写了这个接口」+「组件确实 `fetch(endpoint)`」两条一起钉，语义反而更强。R12 里那批 verbatim 断言（`renderedTail` / `closest('.livedel-btn')` / `classList.toggle('livedel-ro'` / `id="liveDelModal"`）**逐条对着新代码重新对过一遍**才算改完（2026-10-03 M18） |

### 9.3 改完必须做的

1. **跑受影响的单项回归**，再跑 `.workbuddy/_run_all_reg.py`（**23 项**）—— **全部 EXIT=0** 才算过。
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
| 加「让用户手写完整查询」的入口 | `run_search(..., raw_queries=…)` 这个开关（见 **M14**）—— ⛔ 记得三处校验一起放宽、`cond_list` 给占位模板、`china_filters` 置空 |
| 改地图采集 | `客户开发工具.py` `run_maps` / `maps_*` |
| 改抓邮箱/电话 | `客户开发工具.py` `clean_emails` / `clean_phones` / `enrich` / `_find_contact_url` |
| 改评分 | `客户开发工具.py` `score_item` / `rating` |
| 改首页顶栏导航 | `ui/page.html` 的 `.nav` / `.nav-a`（⚠️ 动它就连带要重算 `_check_page.py` R5 的 `_TMPL_SHA` / `_BUILT_SHA`） |
| 改页面 | `ui/page.html` / `ui/manual.html` / `ui/query.html`（⚠️ 改了 `page.html` 必须重算 R5 两条基线） |
| 改客户库查询页 | `ui/query.html` + `core/db.py` 末段「客户库查询」+ 入口 `/api/db/*`（⚠️ 导出必须落 `output/查询导出/` 子目录） |
| 改查询结果的删除 | `core/db.py::db_delete_customers_by_ids` + `客户开发工具.py::api_db_delete` + `ui/query.html::deleteRows`（⛔ 不持锁、必须按主键、删前备份；R9 有 AST 断言） |
| 改首页「本轮已入库明细」的逐行删除 | `客户开发工具.py::api_live_delete` + `core/state.py::STATE['rows_deleted']` + **`ui/live-table.js`（共享组件，见 M18）**（⛔ 仅采集中可点、墓碑保证不进 Excel、新样式加 `livedel-` 前缀；R12 有断言） |
| 改「本轮明细」这张表（加列 / 改渲染 / 改确认框） | **`ui/live-table.js` 一处改、两页同时变**（主页 `/` 与 `/manual`）—— 两页差异只走 `cfg`（keyField / endpoint / showExisted / badgeTitle / canDelete / afterRemove）；⛔ 改完必须**重启工具**，并同时跑 `_check_page.py` R12 + `_check_live_ui.py` + `_check_manual_ui.py`（见 **M18**） |
| 改主页卡片顺序 / 编号 | `ui/page.html` 的 `<h3>` 文字（编号是**硬编码**的，没有计数器）**+ 三处用户可见提示语**（`start()` 的 alert、`#comboSummary` 占位、`#rawCard` 说明）；⛔ 必须重算 R5 两条基线，并同步 R13 / `_check_live_ui` G 段（见 **M11** 的「主页卡片顺序」） |
| 改采集数量的必填规则 | `ui/page.html::start()`（读值只用 `valueAsNumber`，⛔ 不许兜底默认值）+ `客户开发工具.py::api_start`（`data.get('target_count')` ⛔ 不许带缺省值）—— 两处必须同时改，见 **M17** / §9.2 #33 |
| 结果 Excel 行数比实时明细少 | 正常，三个原因：① excel 只写新增（老客户不写）② 明细里被 ✕ 删过（见 **M16**）③ 本轮 0 新增则不产出文件 |
| 把原生弹窗换成居中模态框 | `ui/query.html`（`#delModal` 样式 + HTML + `askDeleteConfirm`/`closeDeleteConfirm`）—— ⛔ 弹窗 HTML 必须放 `<script>` **之前**；H 段断言「居中 ±2px」、R9 断言整页无 `confirm(` |
| 加/改筛选维度 | `core/db.py` `_query_where()` + `db_facet_counts()`（前端零改动，选项自动出现） |
| 清垃圾/误采记录 | `/db` 筛出来 → 勾选 → 「删除选中」（删前自动备份）；或按 id 直接删 |
| 批量补某列为空的记录 | `标注空行业.py`（默认 dry-run）/ `重标行业.py`（改旧口径）——先看不写，`--apply` 才落库 |
| 改扩展 | `extension/`（改完必须点「重新加载」） |
| 改数据库结构 | `core/db.py` + `.workbuddy/_check_db_keys.py` |
| 改结果 Excel 列 | ⛔ 不要改（10 列硬契约） |
| 改飞书导出 | `客户开发工具.py` `build_feishu_records` / `run_export_feishu` |
| 改关键词库 | `关键词库.json` + `.workbuddy/_kwlib_check.py`（注意 CRLF 字节约定） |
| 加行业 | 技能 `keyword-lib-extend` |
| 加新回归项 | `.workbuddy/_run_all_reg.py` 的 `ITEMS` + `.gitignore` 白名单 |
| 查历史决策 | `.workbuddy/memory/MEMORY.md` + `memory/2026-09-27~30.md` |
| 查最近一次回归结论 | `.workbuddy/_reg_summary.txt` |
