# 项目长期记忆：D:\waimao\dp（外贸客户开发工具）

## 定位
谷歌外贸客户开发工具：搜索潜在客户 → 就地补全邮箱电话 → 评分 → 存 SQLite → 导出飞书多维表格。全部集于单文件 `客户开发工具.py`（Flask 本地网页 http://127.0.0.1:5000，启动 `启动客户开发工具.bat`）。

## 版本管理
- 已是 git 仓库（`git init -b main`）。附注标签 **`V1.0`**（提交 `07f146a`）、**`V1.1`**（提交 `7690296`，2026-09-28 全功能版）。问「是否已版本化」先 `git tag -l`，别凭印象。
- **V1.1 快照内容**：搜索补全一体化闭环 + 条件词 8 语言本地化 + 结果输出改 `output/` + 补历史欠账脚本 + 客户库 150 条 + output/ 下 11 份结果 xlsx；跟踪 33 个文件。
- 打标签流程（踩过的坑）：`git add -A` 后要**关掉 `core.quotepath`**（`git -c core.quotepath=false ls-files`）才能读到中文文件名，否则全是八进制转义导致校验读不出来；`git rev-parse V1.1` 返回的是**标签对象** hash，提交 hash 要用 `git rev-parse "V1.1^{commit}"`。
- `.gitignore` 排除：`__pycache__/`、`*.py[cod]`、`.venv/`、`venv/`、`.idea/`、`.vscode/`、`~$*`、`*.tmp`、`.workbuddy/_*`、`*.log`。**`.venv` 28MB/571 文件必须保持排除**（每次提交后确认跟踪数 33 左右）。
- ⚠️ `.workbuddy/关键词组合预览.png` 因文件名不带 `_` 前缀，**被跟踪进去了**（属临时截图）。要清就 `git rm --cached` 并给 .gitignore 补 `.workbuddy/*.png`。
- 回滚：`git checkout V1.1 -- 客户开发工具.py` / `-- DB/客户库.sqlite3`，或复制 `DB/backups/` 里的备份。
- ⚠️ 本机 git 身份是占位值（`github用户名` / `github注册邮箱`），push 远端前用户需自行更正。

## 文件约定
- 数据库：`DB/客户库.sqlite3`（**必须在 DB 子文件夹**），表 `customers`，按 `website_key`（域名）去重，WAL 模式；备份放 `DB/backups/`。
- 行业字段 `customers.industry`：**搜索时由关键词库「行业」下拉自动带入**，取值 = 词库 7 个（宠物用品/LED照明/家具/服装/机械零部件/户外用品/食品）；`回填行业.py` 写的是旧三值（宠物用品/家具家居/汽配）→ 两套未统一，见「数据质量待办」。
- **结果 Excel**：每轮只产出一份，名 `行业-YYYYMMDD_HHMM-主国家.xlsx`（如 `宠物用品-20260928_0145-美国.xlsx`），**统一写在 `output/` 子文件夹**（2026-09-28 起）。`build_result_name()` 拼名、`ts_result_path(industry, country)` 生成（同分钟重名加 `_2`）；目录由 `output_dir()` 提供（不存在自动 `makedirs`，建不了退回程序根目录）、`_app_dir()` 返回脚本所在目录。行业取本轮选的行业（`run_search`→`enrich_core(industry=)` 传参，缺省 `_pick_industry()`）；国家取结果里条数最多的（`_pick_country()`，多国只写主国家）；取不到用 `未分类`/`未知国家`；`_safe_name_part()` 去 Windows 非法字符。⚠️ 文件名以行业开头，**字典序≠时间序**，故 `find_latest_result()` 用 `_result_time_key()` 解析 8 位日期+4 位时间排序（解析不到退回 mtime）；**扫描顺序 output/ → 程序根目录**（兼容早先写在根目录的老文件）；`LEGACY_RESULT_FILES` 排除 `~$` 锁文件、旧名 `客户结果_含联系方式与评分.xlsx` 和已停用的旧 5 列 `客户搜索结果_20260928_0118.xlsx`。`STATE['output']` 存 `output/<文件名>`（带目录前缀，界面/日志可见），「📂 打开结果文件夹」按钮 → `/api/open_folder` → `os.startfile(output_dir())`。
- 补历史欠账：`补历史欠账.py`（`--dry` 只列清单不访问）+ `补历史欠账.bat`（双击跑，**GBK 编码**，cmd 代码页 936）；加载主工具模块后调 `enrich_core(industry='')`，跑完照常写结果 Excel。
- 其他脚本：`同步数据库到飞书.py`（`--dry-run`）、`回填行业.py`（`--dry-run`/`--db-only`/`--feishu-only`/`--overwrite`）、`demo.py`（环境诊断）、`gen_import.py`（旧 JSON 生成，**仍写死旧文件名**）、`import_records*.json`（旧数据）。
- 已废弃但保留：`找客户_谷歌半自动.py`（有 NameError bug）、`补全联系方式与评分.py`（功能已并入主工具）。

## 关键词库（关键词库.json）
- 三级结构 `{行业: {细分品类: {具体产品: [词条]}}}`；7 行业 / 9 细分品类 / 30 产品 / 85 词条。
- 词条字段：`en,cn,de,fr,es,ar` 标准 6 项；`fa`（波斯语）**仅食品 33 条有**；`it,nl,tr` **85 条全有**。
- 语言下拉 `#kwLang`：空项 + en/de/fr/es/ar/fa/it/nl/tr。
- 备份：`.bak`（2 级旧版）、`.bak2`（补三语前）。改词库用一次性 Python 脚本整体重写（按 `en` 原文做键匹配），**结构变更必须同步改前端 JS**，纯加词不用。

## 国家 → 语言 联动
- `_build_page()` 把 `COUNTRIES` 的 `hl` 注入前端：`counts_js = [(code, name, 默认选中, hl), ...]`；前端 `COUNTRY_LANG` + `applyCountryLang()`，**只要该国语言在下拉里有选项就自动选中**，没有则置空。
- ⚠️ 曾经的 `langHasData()` 守卫**已按用户要求删除**（它让伊朗/阿富汗在非食品行业全部留空），现在 25/25 国全部能联动。`#countries` 有 `onchange="onCountry()"`，`onIndustry()` 首行也调 `applyCountryLang()`。
- 已知副作用（用户接受）：非食品行业选伊朗/阿富汗 → 标签显示波斯语但词条回落英文。

## 搜索条件与「国家筛选」的实现（2026-09-28 多语言化）
- **国家筛选不在搜索词里，而在 URL 参数上**：`COUNTRIES` 是 `(代码, 名称, gl, hl)` 四元组（法国 = `('fr','法国','fr','fr')`），`run_search` 里 `country_params = f'&gl={gl}&hl={hl}'`，`search_url()` 拼成 `google.com/search?q=<公式>&gl=fr&hl=fr`（翻页再 `&start=10`）。`gl` = 搜索偏好国家，`hl` = 界面语言。用户参考的那条 URL 结构与此完全一致。
- ⚠️ **「5. 关键词组合预览」以前只画 `q`，没画 `gl/hl`** → 用户以为没做国家筛选（2026-09-28 已修）：每条公式行末尾追加灰色 `&gl=fr&hl=fr`（`.cmb-arg`，带 tooltip），汇总行补「条件词语言：法语」。复制仍复制裸公式（不含参数）。前端 `curLang()` / `countryParams()` 必须与后端保持一致；`counts_js` 因此改为 5 元组 `(代码, 名称, 默认勾选, hl, gl)`，前端存 `COUNTRY_LANG` / `COUNTRY_GL`。
- **搜索条件已多语言化**（2026-09-28）：`CONDITIONS` 改为 **2 元组 `(key, 中文名)`**；公式骨架在 `COND_TEMPLATE`（含 `{p}` 与 `{role}`）；角色词在 `COND_ROLES[key][lang]`，**8 种语言 en/fr/de/es/it/nl/tr/ar**（`COND_LANGS`），缺该语言回落 `en`（波斯语 `fa` 暂缺，与「伊朗/阿富汗词条回落英文」一致）。`cond_template(key, lang)` 是唯一出口，**后端 `run_search` 与前端预览都必须走它**。
  - 语言优先级：**前端传入 `lang`（`#kwLang` 的值）→ 该国 `hl` → `en`**。前端 `start()` 会 POST `lang`，`/api/start` 透传给 `run_search(..., lang='')`。
  - ⚠️ 这是**搜索质量的根因级修复**：只写英文条件词去搜法语/德语市场，等于在非英语页面里找英文词，命中的多是英文版块或 B2B 名录站。实测法国预览已变成 `"nouilles" (grossiste OR distributeur)` 与 `(importateur OR "société de négoce")`。
- ⚠️ **条件模板里绝对不要再给 `{p}` 加引号**（2026-09-28 修复的老 bug）：`pq_list` 里的产品词**已经**被包成 `"xxx"`，`contact`/`linkedin` 两个模板原来写成 `"{p}"` → 一直拼出 `site:linkedin.com/in ""nouilles""` 双引号。现已改为 `inurl:contact {p}` / `site:linkedin.com/in {p} ({role})`。
- **`cr`/`lr`（谷歌高级搜索的「地区/语言」）实测不值得加**（2026-09-28 真机四组对比，探针 `.workbuddy/_probe_filter.py`）：`cr=countryFR` 是按**主机托管国**过滤，法国 B2B 商大量用 `.com`（miamland/epicerie-grossiste/agidra/destockplus），加 cr 反而把真客户挤出结果。`.fr` 占比：现状 `gl/hl` **50%**（10 条）> 叠加 cr/lr 56%（9 条）> 单用 cr/lr **29%**（7 条）> 无参数 25%（8 条）。即「什么都不加」最差、`gl/hl` 已经是最优性价比，cr/lr 只让结果变少、收益边际。用户 2026-09-28 拍板保持现状。
- 若要城市级精度，真正有效的参数是 `uule`（把所在地编码到城市），不是 cr/lr。

## 任务流水线（搜索+补全 = 一体化闭环，2026-09-28 定稿）
- `run_search(...)` 自身即闭环。主循环每拿到一个新网站：① `db_upsert_customer` 登记线索 → ② **立刻** `enrich(page, url)` 抓邮箱/电话 → ③ 评分 → ④ 再 upsert 覆盖（空值不覆盖有效值）→ ⑤ 追加 `all_rows`。凑够 `target_count` 个**新增网站**即停（按新网站数计，不按是否抓到联系方式计——用户拍板）。
- **没有第二段补全**：整轮结束在 `finally` 里 `page.quit()` 之后 `_save_enrich_excel(all_rows, industry)` 落盘（放 finally 才能保证中途「停止」不白跑）。浏览器整轮只开关一次。每条多花 5~15 秒，目标 10 条约多 2~3 分钟。
- `auto_enrich=False`（前端 `#autoEnrich` 取消勾选）退化为只收集线索：跳过 enrich、邮箱电话留空、仍落盘 Excel。默认勾选。
- ⛔ **「补全联系方式+评分」按钮已删除**（2026-09-28 第三次提出后拍板）：连带 `/api/enrich`、`enrich()` JS、`btnEnrich`、`run_enrich()`、`.btn-enrich` CSS、`poll()` 的 enrich 分支全部清除。历史欠账只走命令行脚本。**但 `enrich_core` / `_enrich_worklist` / `enrich()` / `_save_enrich_excel` 必须保留**——脚本要用，搜索链路也在用，别再当死代码删。
- ⚠️ **标签页陷阱**：`enrich()` 用 `page.new_tab()` 访问客户站，`open_search` 用 `page.get()`，而 `ChromiumPage` 操作「当前活动标签」→ 补全后必须 `_back_to_search(page, search_tab_id)` 切回搜索页，否则下一步搜索会导航到客户站上。`search_tab_id` 创建浏览器后取一次、首次导航后补取一次兜底。
- ⚠️ `ChromiumTab` **没有 `new_tab()`**（4.1.1.4 实测），而 `resolve_goto` 兜底要调 `page.new_tab()` → 搜索必须继续由 `ChromiumPage` 承担，别改成独立 tab 对象。
- **结果文件是 10 列硬契约**（`_save_enrich_excel` 写 / 飞书 `build_feishu_records` 按下标读 / 启动 `init_customer_db` 按下标读），列名与顺序**一个都不能改**；每项须含 `title/url/emails/phones/contact_url/score/rating/snippet/formula/country/industry`。
- 模块级 `ENRICH_FILE = find_latest_result()` 运行时指针 + `build_feishu_records()` 找不到时警告返回 `[]` 的保护，均不变。
- 前端状态：`counter`（每 1 秒轮询刷新「本轮新增 N 个网站」）、`dbCounter`（**已改为随轮询实时刷新**，文案「SQLite 已存 N 条（已评分 M）」，数据来自 `/api/status` 的 `db_total`/`db_verified`）。`/api/status` 返回 logs/result_count/phase/**rows**/db_total/db_verified；`STATE` 里 `phase` 仅 search / export。
- **实时入库明细表**（2026-09-28 新增）：页面上「状态行」与「日志框」之间有一张 `📥 本轮已入库明细（实时）` 表格（`#liveBody`/`#liveCount`/`#liveEmpty`）。后端每入库一条就往 `STATE['rows']` 追加 `{n,title,url,emails,phones,contact_url,score,rating,industry,country}`（**在 `STATE_LOCK` 内 append**，`/api/start` 里 `rows=[]` 清空）；前端 `renderRows(rows)` **增量追加**新行（不清空重绘，保住滚动位置），新行带 `row-new` 淡入高亮，有邮箱显示绿色等宽字体、无则显示灰色「未抓到」，公司名是外链新窗口打开，域名另起一行；长邮箱用 `max-width+ellipsis` 不撑破表格。`start()` 里清空 `renderedRows` 与表格。
- ⚠️ **worklist 判据是「邮箱和电话都为空」**（非「补过没补过」），所以历史欠账脚本会反复访问「访问过但一个联系方式都没抓到」的站（2026-09-28 实测 26 条）。彻底修需加 `enriched_at` 列（用户尚未拍板）。
- 回归验证脚本在 **`.workbuddy/`**（已被 gitignore，用绝对路径加载主工具）：`_smoke_search.py` 打桩测一体化闭环（不联网、不开浏览器，DB 与结果文件指向临时目录），并断言 `STATE['rows']` 实时明细与 `/api/status` 返回的 `rows`/`db_total`；`_check_page.py` 校验页面文案、占位符替换、内嵌 JS 语法（`node --check`）、标签配对，断言补全按钮痕迹已清除、实时明细表元素与 `renderRows(d.rows)`/`db_total` 就位；`_check_live_ui.py` 起临时 Flask（端口 5012）+ Chrome 打开页面、注入假数据后截图 `.workbuddy/_live_ui.png`，断言行数/徽章/空态隐藏/表格不撑破容器。**改完搜索链路或前端后各跑一遍**。

## 谷歌搜索抓取链路（最易碎，2026-09-28 大修）
- 判断结果是否渲染好：`RESULT_LINK_CSS = 'css:a:has(h3)'` 的条数（`count_results()`）。⚠️ 旧 `page.ele('div#search')` **已失效**（新版谷歌没 `#search`/`#rso`），别再改回去。
- 开搜索页必须走 **`open_search(page, formula, country_params, start=0, min_items=3, attempts=3)`**：多轮重开，前 2 轮直连 `/search?q=`，第 3 轮用搜索框输入兜底。谷歌偶尔返回「壳页面」（搜索框在、结果区空，伴随 `Updating location`）——`page.refresh()` **救不回来**，**重新导航一次即正常**。
- ⚠️⚠️ **「结果没渲染出来」有两种完全不同的原因，日志里分不开（2026-09-28 真机实测锁定，未修）**：
  - ① **壳页面**（上面那种，重开一次能好）；
  - ② **谷歌「零结果页」**——页面上写着 `Your search - … - did not match any documents`，`a:has(h3)`=0，**重试同一条 URL 永远没用**（实测重开 3 次全败，含搜索框兜底）。截图证据 `.workbuddy/_fail_q1_p0.png`。
  - **触发条件 = 新会话的第一个谷歌请求 + 重公式**：同一浏览器里，33 词的公式**首次**请求 → 0 条零结果页；**同一浏览器稍后再发同一条公式 → 10 条**。对照实验（`.workbuddy/_probe_open_search.py`）：A(33词,首次) 0 条 → B(21词) 10 条 → C(14词) 10 条 → D(=A,33词,再次) **10 条**。另一组：浏览器起来先发一条最简 `search?q=noodles` → 重公式立刻 10 条。
  - **结论**：`gl/hl`+公式本身都没问题；是「**冷会话首请求**」被谷歌降级。可用修法（用户拍板后再改）：软预热（先发一条最简单的 `search?q=<首个产品词>`，**不是首页**）、零结果时先换 URL 再重发原公式、把零结果页与壳页面在日志里区分开、公式减负（现中国过滤默认全开让公式涨到 **33 词**，逼近谷歌 ~32 词实际上限）。
- **不要加谷歌首页预热**：实测更易触发地区识别中间态导致空结果页。每个搜索 URL 自带 `gl`/`hl`。**注意区分**：首页预热有害，但「先发一条最简 `/search?q=` 请求」实测有益（见上条）。
- `is_blocked()` 三层：① `BLOCK_SUBSTR`(`['ubuy','europages','exportgenius']`) 子串匹配 → ② `SEARCH_ENGINE_PREFIX=('google.','bing.','yahoo.','duckduckgo.','baidu.','yandex.')` 前缀 → ③ `BLOCK_DOMAINS` **精确或后缀匹配**（`netloc == d or netloc.endswith('.'+d)`）+ **`netloc.endswith('.cn')` 全局兜底**。注意「子域自动覆盖」只对 BLOCK_DOMAINS 成立，加 `xxx.com` 就能连带拦掉 `a.xxx.com`。已补 `indiamart.com`/`trade.gov`/`worldstopexports.com`/`dailyvoice.com`/`taobao.com`/`tmall.com`。`EXCLUDE_OPTIONS` 是**查询词级**排除（UI 勾选框 + 默认全开，`EXCLUDE_DEFAULT` 全部拼进 `q`），与域名黑名单是两套东西，加平台站建议**两边都加**。
- ⚠️ **结果链接是谷歌跳转链，必须经 `resolve_goto(page, href, card)` 换真地址**：① 已是目标站 → 原样；② `/url?q=<明文>` → `parse_qs`；③ `/goto?url=<加密>` → 解不开，先取卡片 `<cite>`（`_cite_domain()`，零成本，实测与真实跳转同域），再不行才开标签页让谷歌 302（4.1 秒/条）。**判断是否跳转链必须用 `_is_search_engine_url()`**（去 `www.` 比 `SEARCH_ENGINE_PREFIX`）——旧代码硬编码 `google.com/goto`，在 `google.com.hk/goto` 上匹配失败 → 原样返回 → 又被黑名单丢掉，**一页全军覆没**（实测 10 条全丢，修复后留 9 条）。
- 走 cite 快路径时 `website` 只到域名级（如 `https://www.miamland.com`），`/url?q=` 时是完整 URL；同一公司多页面会被 `url_key`（netloc+path）合并成一条。
- ⚠️ **谷歌会限流**：密集请求连续返回壳页面，三次重试全失败后跳过本页；**等 90 秒即恢复**。排查时别误判成代码 bug。今日曾触发验证码，需手动过。
- 主循环每查询打一行统计（候选/黑名单/本页重复/库已有/新增/其中抓到邮箱）+ 整轮总账——用户报「数量填 10 无效/库不更新」时靠它定位「压根没抓到结果」。
- **页面卡片顺序**：1 目标国家 → 📋 产品关键词库（行业/细分品类/具体产品/语言 四级联动）→ 2 产品关键词（OR/AND/分别搜）→ 3 搜索条件 → 4 参数（`#pages`、`#targetCount` 本轮新增网站数 10-100、`#autoEnrich`、`#excludes`）→ **5 关键词组合预览**（纯展示不参与提交）。
- 「5 关键词组合预览」：`renderCombos()` 用注入的 `COND_TMPL`（`conds_js` 四元组第 4 项）算公式，**规则必须与后端 `run_search` 一致**（OR→`"a" OR "b"`、AND→`"a" "b"`、分别搜→每词一条），尾部灰字是排除词；`COMBO_CACHE` 供「复制全部组合」。

## 飞书多维表格（外贸客户管理表）
- BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`；表 `客户信息`（TABLE_ID `tblY38YnVIQ5AYYA`）。
- CLI：`C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`

### lark-cli 踩坑
1. 调用前必须 `pop('HERMES_HOME')`，否则报异常
2. `+record-list --limit` **上限 200**，翻页用 `--offset`
3. JSON 格式：顶层 `raw['data']`，其下 `data`(行矩阵) / `fields`(列名) / `record_id_list`(记录 ID，与行同下标) 三者平行数组
4. 鉴权参数是 **`--base-token`**，写 `--app-token` 会被拒
5. **官网字段名就是 `官网`**（另有 公司名称/备注/电话/行业/国家地区/来源渠道/跟进状态/使用的搜索公式/邮箱/公司类型/联系人/职位/城市/LinkedIn/下次跟进日期/上次跟进日期，共 17 个）；按「网站/网址」查会静默返回 0 命中（假阴性），务必先打印 `fields` 核对
6. `邮箱` 字段**只接受单个合规邮箱**，多邮箱报 800010407 → 其余写入 `备注`
7. `来源渠道`/`跟进状态`/`国家地区` 是 select，值要用数组如 `["谷歌搜索"]`
8. 国家名映射：本地「沙特」→ 飞书「沙特阿拉伯」
9. 写入用 `+record-batch-create --json @文件`，格式 `{"create_records":[...]}`
10. `+field-update` 是**全量 PUT**（非增量补丁）：改 select 选项必须带全量列表，按 `name` 匹配可保留原选项；**改前快照、改后逐条核对**
- 飞书「行业」字段（select，field id `fldH9rx3py`）选项仍是旧四值（宠物用品/家具家居/汽配/其他）。飞书还有 16 条垃圾记录待删，record_id 存 `.workbuddy/_todo.json`（如 `recvwfe0shTJJM`=sourceready.com）。

## 本机环境注意事项
- bash 环境残缺（`dirname`/`ls`/`grep`/`tail` 不可用），命令一律用 `python -c` 或 PowerShell。
- PowerShell 工具**输出不回显**，结果写临时文件后 Read。
- `wmic` 被安全策略屏蔽，查进程命令行用 `Get-CimInstance Win32_Process`；查文件占用用 `rstrtmgr.dll`（RmStartSession/RmRegisterResources/RmGetList）。
- **删文件进回收站**：`Add-Type` 与 `New-Object -ComObject` 均被拦截。用 Python `ctypes.windll.shell32.SHFileOperationW`（`FO_DELETE` + `FOF_ALLOWUNDO|FOF_NOCONFIRMATION|FOF_SILENT|FOF_NOERRORUI`，`pFrom` 用 `create_unicode_buffer(path+'\0')`）。⚠️ 返回非 0（如 ret=2）也可能**实际已成功**，必须 `os.path.exists()` 复查。
- 回收站核对：读 `D:\$Recycle.Bin\<SID>\` 的 `$I*`（`[8:16]`=原大小，`[24:]`=UTF-16LE 原路径）配 `$R*`；该目录 1.2 万+ 条目，**必须定向搜关键字**。
- Python：`D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`
- ⚠️ **禁止并行 Edit 同一文件**（会写入覆盖，静默冲掉前一处改动——`is_blocked` 改动就是这样丢的）。同一文件逐个 Edit，改完用 grep/`inspect.getsource()` 复核。
- 改完 `PAGE_HTML` 相关代码要**重启工具**才生效。
- 真机验证页面可用 `m.app.run(port=5011)` 起临时实例 + `m.create_browser_page()` 截图/`run_js` 读写 DOM，不碰真实客户库。

## 数据质量待办
- 库里混有平台类垃圾域名（joybuy.fr / dreamstime / chegg.com / thomasnet / trendyol / u-buy.jp / petz.ae / suppliergo / archive.org / tiktok 等）与旧行业残留，约 25~36 条未清。本地库 2026-09-28 曾从 120 清理到 90 条。
- `PRODUCT_WORDS = ['litter','liner','cat','pet']` 写死猫砂垫品类且**是子串匹配无词边界**——`...?ca**cat**cha_type=` 会白送 10 分；换行业必须同步修改。
- ⛔ **评分体系在非英语场景方向是反的（2026-09-28 逐条复盘 20 条法国结果实锤，未修）**：
  - `CTYPE_WORDS = ['wholesale','distributor','importer','trading','dealer','supplier','bulk']` 全是**英文**，法语 `grossiste/distributeur/fournisseur/importateur` 一个不认 → 真客户 `miamland.com`（标题就是 «Grossiste Pâtes et Nouilles»）只有 10 分。
  - ⚠️ **注意与「条件词已多语言化」的区别**：搜索用的条件词现在会按语言切（`COND_ROLES`），但**评分用的 `CTYPE_WORDS` / `PRODUCT_WORDS` 仍是写死英文**，两套词表没打通。所以法语搜索的召回变好了，评分却仍认不出 `grossiste` → 本地真客户分低。
  - 反直觉：`fr.kompass.com/y/importer/...`、`douane.gouv.fr/demarche/importer-...` 因 URL 含英文 `importer` 白拿 +25 → 35 分。**英文词表奖励了 B2B 名录站和政府指引页，惩罚真客户**
  - `score_item()` **只有加分项、无任何减分/否决** → 「抓到邮箱电话」≈「高分」：`agriculture.canada.ca`（加拿大农业部）55 分 = 30邮箱+15电话+10非博客，与真批发商 `dca-distribution.fr` 55 分**构成完全一致**
  - 根治要三件事：① `CTYPE_WORDS` 多语言化（可直接复用 `COND_ROLES` 的思路）② `PRODUCT_WORDS` 按本轮产品词动态传入并加词边界 ③ 加否决/减分项（`.gov`/`.gc.ca`、点评站、餐馆、菜谱、歌词、B2B 名录、新闻、企业黄页）。单纯抬高导出阈值治不了。
- **查询语义**：OR 作用域已于 2026-09-28 修好——`CONDITIONS` 里含 OR 的模板**全部用括号锁住同义词组**（`{p} (wholesaler OR distributor)`），别去掉括号（不加会读成 `({p} wholesaler) OR distributor`，拉进任意行业的同类角色）。① 条件词多语言化同日完成（详见上面「搜索条件与『国家筛选』的实现」），法国实测 `"nouilles" (grossiste OR distributeur)` 精准命中法语批发商。
- **行业取值两头不一致**：`回填行业.py` 写 宠物用品/家具家居/汽配，关键词库行业下拉是 宠物用品/LED照明/家具/服装/机械零部件/户外用品/食品，飞书「行业」选项又是旧四值 → 待统一。
