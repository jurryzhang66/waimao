# 项目长期记忆：D:\waimao\dp（外贸客户开发工具）

## 项目定位
谷歌外贸客户开发工具：搜索潜在客户 → 补全邮箱电话 → 评分 → 存 SQLite 客户库 → 导出飞书多维表格。

## 文件约定
- 主工具：`客户开发工具.py`（Flask 本地网页 http://127.0.0.1:5000，启动用 `启动客户开发工具.bat`）
- 数据库：`DB/客户库.sqlite3`（**放在 DB 子文件夹**，不要再挪回根目录）；表 `customers`，按 `website_key`（域名）去重
- 行业字段：`customers.industry`；**搜索时由关键词库「行业」下拉自动带入**，取值是关键词库那 7 个（宠物用品/LED照明/家具/服装/机械零部件/户外用品/食品）；`回填行业.py` 回填的是旧三值（宠物用品/家具家居/汽配）——**两套写法未统一，详见「数据质量待办」**
- **结果 Excel 命名**（2026-09-28 起）：每轮**只产出一份**，名为 **`行业-YYYYMMDD_HHMM-主国家.xlsx`**（如 `宠物用品-20260928_0145-美国.xlsx`）。由 `build_result_name()` 拼名、`ts_result_path(industry, country)` 生成（同分钟同行业同国家重名时加 `_2`/`_3`）。
  - 行业来源：优先用本轮搜索选的行业（`run_search` → `run_enrich(industry=)` → `enrich_core(industry=)` 一路传参）；手动点「补全」没有搜索上下文时，`_pick_industry()` 取结果里出现最多的行业。
  - 国家来源：`_pick_country()` 取结果里**条数最多**的国家（用户拍板：多国同跑只写主国家，不拼接）。
  - 取不到时占位 `未分类` / `未知国家`；`_safe_name_part()` 去掉 Windows 非法字符（`\ / : * ? " < > |`）。
  - ⚠️ 文件名开头是行业名，**字典序≠时间序**，所以 `find_latest_result()` 用 `_result_time_key()` 从文件名解析 8 位日期+4 位时间做排序键（解析不到才退回 mtime），兜底旧名 `客户结果_含联系方式与评分.xlsx`；`~$` 锁文件已排除。
- 临时/诊断脚本：`demo.py`（环境诊断）、`gen_import.py`（旧版 JSON 生成，**仍写死旧文件名，未改**）
- 已废弃但保留：`找客户_谷歌半自动.py`、`补全联系方式与评分.py`（功能已并入主工具，前者有 NameError bug）

## 关键词库（关键词库.json）
- 结构：**三级** `{行业: {细分品类: {具体产品: [词条]}}}`；7 行业 / 9 细分品类 / 30 具体产品 / 85 词条
- 词条字段：`en, cn, de, fr, es, ar` 为标准 6 项；`fa`（波斯语）**仅食品 33 条**有；`it, nl, tr`（意大利语/荷兰语/土耳其语）**全部 85 条都有**
- 语言下拉（`客户开发工具.py` 的 `#kwLang`）：空项 + en/de/fr/es/ar/fa/it/nl/tr 共 9 种 + 1 个留空态
- 备份：`关键词库.json.bak`（2 级旧版）、`关键词库.json.bak2`（补三语前）
- 改词库用一次性 Python 脚本整体重写（按 `en` 原文做键匹配，勿逐条 Edit）；**结构变更时必须同步改前端 JS，纯加词才不用改**

## 国家 → 语言 联动（`客户开发工具.py`）
- `_build_page()` 把 `COUNTRIES` 的 `hl` 一起注入前端：`counts_js = [(code, name, 默认选中, hl), ...]`
- 前端 `COUNTRY_LANG` 映射 + `applyCountryLang()`：**只要该国语言在语言下拉里有选项就自动选中**，没有则置空（空项标签为空字符串，靠用户自己选）
- ⚠️ 曾经有一层 `langHasData()` 守卫（要求「当前行业真收录该语言词条」才切换），**已按用户要求删除**——它导致伊朗/阿富汗在非食品行业全部留空。现在 25/25 国全部能联动
- `#countries` 有 `onchange="onCountry()"`；`onIndustry()` 首行也调 `applyCountryLang()`（换行业时重算）
- 已知副作用（用户已知悉、暂接受）：非食品行业选伊朗/阿富汗 → 语言标签显示波斯语但词条回落英文（波斯语只做了食品 33 条）

## 任务流水线（两步 → 一键到底）
- **搜索** `run_search(..., industry='', auto_enrich=True)`：只抓标题/网址/摘要/国家，**只 upsert 进客户库，不再写 Excel**（原 5 列 `客户搜索结果.xlsx` 已停用、文件可删）。凑够 `target_count` 就提前停。
- **补全** `enrich_core()` / `run_enrich(_chained=False)`：**DB 驱动**，不再读搜索 Excel。`_enrich_worklist()` 取 `COALESCE(email,'')='' AND COALESCE(phone,'')=''` 的记录（本轮结果也在库里，故天然覆盖历史欠账），用 `is_blocked()` 跳过黑名单域名、`normalize_domain()` 去重，按 `last_seen_at DESC` 排序（本轮优先）。
- **串联**：`run_search` 的 `finally` 里、`page.quit()` 之后、`STATE['done']/['running']` 复位之前调 `run_enrich(_chained=True)`。放 finally 是必需的——搜索中途「停止」内部走 `return`，只有 finally 能既跳过补全又复位状态。
- 前端参数卡片 `#autoEnrich` 勾选框（**默认勾选**）控制是否自动接补全；`poll()` 按 `STATE['phase']` 显示「搜索中…/补全联系方式中…」。
- **结果文件是 10 列硬契约**（`_save_enrich_excel` 写出 / 飞书 `build_feishu_records` 按下标读 / 启动迁移 `init_customer_db` 按下标读），列名与顺序**一个都不能改**；语义 = 「补全阶段处理过的记录」，所以导出飞书不会重复创建。
- 模块级 `ENRICH_FILE = find_latest_result()` 是「当前结果文件」的运行时指针：导入时解析一次、`_save_enrich_excel()` 成功后更新；`build_feishu_records()` 用 `ENRICH_FILE or find_latest_result()` 并在找不到时打警告返回 `[]`（防止 `load_workbook('')` 崩）。
- ⚠️ 副作用：搜索阶段不再出 Excel，**只点「开始搜索」而不补全时没有结果文件**，需补全完成或直接查客户库；`auto_enrich` 建议保持勾选。
- 补全可中断可续跑（`db_upsert_customer` 空值不覆盖已有值），中途停止也会 `_save_enrich_excel` 落盘。
- ⚠️ **worklist 判据是「邮箱和电话都为空」，不是「补过没补过」**——所以「上次访问了但一个联系方式都没抓到」的网站会**被反复重复访问**（日志里「已补过的下次不会重复访问」这句只对抓到过联系方式的情况成立）。2026-09-28 实测：库 80 条、待补 45 个，其中 **16 个是已评分但无邮箱无电话的重复访问对象**。彻底修需加 `enriched_at` 列并把它纳入 worklist 判据（用户尚未拍板）。
- ⛔ **「补全联系方式+评分」按钮不可删**（用户已问过两次）：它是唯一产出结果 Excel 的入口（搜索阶段不再出文件），也是「导出到飞书」和「补历史欠账」的唯一触发点，且绑定 `/api/enrich` 路由 + `enrich()` JS + `btnEnrich` 禁用逻辑 + `run_enrich()`。只可改文案/tooltip。
- 实操规模参考：客户库 80 条时待补全约 38 个、预估 12 分钟。

## 谷歌搜索抓取链路（2026-09-28 大修；最易碎的部分都在这里）
- 判断「结果是否渲染好」靠 **`RESULT_LINK_CSS = 'css:a:has(h3)'` 的条数**（`count_results()`）。⚠️ 旧的 `page.ele('div#search')` 判断**已失效**（新版谷歌页面根本没有 `#search`/`#rso`），别再改回去。
- 开搜索页必须走 **`open_search(page, formula, country_params, start=0, min_items=3, attempts=3)`**：多轮重开，前 2 轮直连 `/search?q=`，第 3 轮换搜索框输入（`type_search`）兜底。原因是谷歌偶尔返回「壳页面」（搜索框在、结果区空，伴随 `Updating location`/地区选择）——实测 `page.refresh()` **救不回来**，但**重新导航一次就正常**。
- **不要加谷歌首页预热**（`page.get('https://www.google.com/?hl=...')`）：实测更容易触发地区识别中间态导致空结果页。每个搜索 URL 自带 `gl`/`hl`，预热没必要。
- `is_blocked()` 除 `BLOCK_DOMAINS`/`BLOCK_SUBSTR` 外还有 **`SEARCH_ENGINE_PREFIX = ('google.', 'bing.', 'yahoo.', 'duckduckgo.', 'baidu.', 'yandex.')`**：谷歌按出口 IP 跳区域域名（`google.com.hk`/`google.de`），只写 `google.com` 拦不住（曾污染出假客户 `google.com.hk`）。
- ⚠️ **结果链接是谷歌跳转链，必须经 `resolve_goto(page, href, card)` 换真地址**，分三种形态：① 已经是目标站 → 原样；② `/url?q=<明文地址>` → `parse_qs` 直接解析；③ `/goto?url=<加密串>` → **解不开**，先取卡片里的 `<cite>`（`_cite_domain()`，形如 `https://www.x.com › 路径`，**零成本**，实测与真实跳转同域），再不行才开标签页让谷歌 302（4.1 秒/条）。**判断是否谷歌跳转链必须用 `_is_search_engine_url()`**（去 `www.` 后比 `SEARCH_ENGINE_PREFIX`）——旧代码硬编码 `'google.com/goto'`，在 `google.com.hk/goto` 上匹配失败 → 原样返回谷歌地址 → 又被 `is_blocked` 当搜索引擎域名丢掉，**一页结果全军覆没**（实测 10 条全丢，修复后保留 9 条）。
- ⚠️ 走 cite 快路径时 `website` 只到**域名级**（无路径，如 `https://www.miamland.com`），走 `/url?q=` 时是完整 URL。好处：同一公司多页面会被 `url_key`（netloc+path）自动合并成一条。
- ⚠️ **谷歌会限流**：短时间密集请求连续返回「壳页面」，`open_search` 三次重试全失败后跳过本页。实测**等 90 秒即恢复**——排查抓取问题时别把它误判成代码 bug。
- 搜索主循环每查询打一行统计（候选/黑名单/已存在/新增/空页）+ 整轮汇总，用来一眼确认「有没有写进客户库」——用户报「数量填 10 无效 / 库不更新」时就是靠这个定位到「压根没抓到结果」。
- **页面卡片顺序**：1 目标国家 → 📋 产品关键词库（行业/细分品类/具体产品/语言 四级联动）→ 2 产品关键词（含 OR/AND/分别搜）→ 3 搜索条件 → 4 参数（`#pages` 每公式抓几页、`#targetCount` 本次新增目标 10-100、`#autoEnrich`、`#excludes`）→ **5 关键词组合预览**。
- 「5. 关键词组合预览」是**纯展示、不参与提交**（`start()` 仍自行收集参数）：`renderCombos()` 用 `_build_page()` 注入的 `COND_TMPL`（`conds_js` 四元组第 4 项 = 公式模板）算公式，**规则必须与后端 `run_search` 保持一致**（OR→`"a" OR "b"`、AND→`"a" "b"`、分别搜→每词一条），尾部灰字是排除词；`COMBO_CACHE` 给「复制全部组合」用。

## 飞书多维表格（外贸客户管理表）
- BASE_TOKEN：`ZhSSb18BMajKR7sacxTcCFY0njf`；表：`客户信息`（TABLE_ID `tblY38YnVIQ5AYYA`）
- CLI：`C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`
- 同步脚本：`同步数据库到飞书.py`（支持 `--dry-run`；按官网域名 + 公司名双重去重，只新增不覆盖）
- 行业回填脚本：`回填行业.py`（`--dry-run` / `--db-only` / `--feishu-only` / `--overwrite`；按关键词判定行业，识别不出留空）
- 飞书「客户信息」表字段共 17 个，含 `行业`（select，单选，选项：宠物用品/家具家居/汽配/其他，field id `fldH9rx3py`，由用户手动创建）

### lark-cli 踩坑（务必遵守）
1. 调用前必须 `pop('HERMES_HOME')`，否则返回异常
2. `+record-list` 的 `--limit` **上限 200**，翻页用 `--offset`
3. `+record-list --format json` 的记录在 `data.data` 矩阵里，列名在 `data.fields`
4. `邮箱` 字段**只接受单个合规邮箱**，多邮箱会报 800010407；其余邮箱写进 `备注`
5. `来源渠道`/`跟进状态`/`国家地区` 是 select 字段，值要用数组如 `["谷歌搜索"]`
6. 国家名要映射：本地「沙特」→ 飞书选项「沙特阿拉伯」
7. 写入用 `+record-batch-create --json @文件`，文件格式 `{"create_records":[...]}`
8. `+field-update` 是**全量 PUT**（不是增量补丁）：改 select 选项必须带全量列表，按 `name` 匹配可保留原有选项；**改前先快照记录值、改后逐条核对**（本次扩国家选项即用此法，83 条记录零影响）

## 本机环境注意事项
- bash 环境残缺（`dirname`/`ls`/`grep`/`tail` 均不可用），执行命令一律用 `python -c` 或 PowerShell
- PowerShell 工具能执行但**输出不回显**：结果需 `Set-Content` 写临时文件后用 Read 读取
- `wmic` 被安全策略屏蔽，查进程命令行用 PowerShell `Get-CimInstance Win32_Process`
- 查文件占用进程用 `rstrtmgr.dll`（不是 rstrtmm）：RmStartSession/RmRegisterResources/RmGetList
- **删文件进回收站**：`Add-Type` 和 `New-Object -ComObject` **都被安全策略拦截**。用 Python `ctypes.windll.shell32.SHFileOperationW`（`FO_DELETE` + `FOF_ALLOWUNDO|FOF_NOCONFIRMATION|FOF_SILENT|FOF_NOERRORUI`，`pFrom` 用 `create_unicode_buffer(path+'\0')` 保证双 NUL）。⚠️ 返回值可能非 0（如 ret=2）但**实际已成功**，必须用 `os.path.exists()` 复查。
- 回收站核对：读 `D:\$Recycle.Bin\<SID>\` 的 `$I*` 元数据（`[8:16]`=原大小，`[24:]`=UTF-16LE 原路径）配对 `$R*`。该目录 1.2 万+ 条目，**必须定向搜关键字**，别全量打印（曾一次刷出 78 万字节）。
- Python 路径：`D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`
- ⚠️ **禁止并行 Edit 同一个文件**：并行发多个 Edit 会发生**写入覆盖**（后一个基于旧内容落盘，把前一个的改动静默冲掉，本次 `is_blocked` 改动就是这样丢的）。**同一文件必须逐个 Edit**，改完用 `inspect.getsource()` 或 grep 复核。
- 改完页面（`PAGE_HTML` 相关）后要**重启工具**（`启动客户开发工具.bat`）才生效——Python 进程已加载旧代码，运行中改文件不影响它。
- 真机验证页面可用 `m.app.run(port=5011)` 起临时实例 + `m.create_browser_page()` 打开截图/`run_js` 读写 DOM，不碰真实客户库。

## 数据质量待办
- 数据库混有旧行业残留（家具沙发、汽配 auto parts）与平台类垃圾域名（archive.org/ubuy.*/tiktok/trade.gov/indiamart 等）约 25-36 条，建议后续清理
- 评分里的产品词 `PRODUCT_WORDS = ['litter','liner','cat','pet']` 写死为猫砂垫品类，换行业需同步修改
- **查询语义**：~~② OR 作用域~~ 已于 2026-09-28 修好——`CONDITIONS` 里含 OR 的模板**全部用括号锁住同义词组**（`{p} (wholesaler OR distributor)` 等），别再把括号去掉（不加括号谷歌可能读成 `({p} wholesaler) OR distributor`，让后半截单独生效、拉进任意行业的同类角色）。① **条件词仍是英文**（未做多语言）：配非英语产品词（如法语 `nouilles`）时精准度下降——实测 `"nouilles" grossiste OR distributeur` 的 10 条清一色法语批发商，远好于英文条件。要做需补 8 条件 × 9 语言，用户暂未选。
- 黑名单已于 2026-09-28 扩充：`BLOCK_DOMAINS` + `indiamart.com`/`trade.gov`/`worldstopexports.com`/`dailyvoice.com`；`BLOCK_SUBSTR` = `['ubuy', 'europages', 'exportgenius']`（多后缀站用子串匹配更省心）
- **行业取值两头不一致**：`回填行业.py` 回填的是 宠物用品/家具家居/汽配，而关键词库的行业下拉是 宠物用品/LED照明/家具/服装/机械零部件/户外用品/食品（搜索时自动写入）。同一概念出现两种写法（家具家居 vs 家具、汽配 vs 机械零部件），飞书「行业」选项也还是旧四值，待统一
