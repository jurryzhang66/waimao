# 项目长期记忆：D:\waimao\dp（外贸客户开发工具）

## 定位
谷歌外贸客户开发工具：搜索潜在客户 → 就地补全邮箱电话 → 评分 → 存 SQLite → 导出飞书。集于单文件 `客户开发工具.py`（Flask 本地页，`启动客户开发工具.bat` 启动）。**改 `PAGE_HTML` 相关代码必须重启工具才生效。**
- ⚠️ **端口不写死**：`PREFERRED_PORTS=(5000,8000,8080,8765,9000,7000,6500,5800,5555)` + `pick_port()` 启动时实测挑一个能 bind 的（Windows 把成片 TCP 端口保留给 Hyper-V/WinNAT，落在保留段里 bind 报 `WSAEACCES(10013)`「以一种访问权限不允许的方式做了一个访问套接字的尝试」，而 `netstat` 看不到占用，极易误判成「端口被抢」；保留段每次开机漂移，故不能固定）。本机 5000 被圈走 → 实际跑在 **http://127.0.0.1:8000/**。日志会打印真实地址，看日志为准。

## 版本管理
- git 仓库（`main`）。标签：**V1.0** `07f146a`、**V1.1** `7690296`、**V1.2** `556d857`。先 `git tag -l` 再答，别凭印象。
- 坑：① `git add -A` 后用 `git -c core.quotepath=false ls-files` 才读得到中文名；② `git rev-parse V1.2` 给的是**标签对象**，提交 hash 要 `git rev-parse "V1.2^{commit}"`。
- `.gitignore` 排除 `__pycache__/`、`*.py[cod]`、`.venv/`(28MB/571文件，必须保持排除)、`.idea/`、`.vscode/`、`~$*`、`*.tmp`、`.workbuddy/_*`、`*.log`。跟踪数约 34。⚠️ `.workbuddy/关键词组合预览.png` 因无 `_` 前缀被跟踪（临时截图，可 `git rm --cached`）。
- 回滚：`git checkout V1.2 -- 客户开发工具.py`，或复制 `DB/backups/`。
- ⚠️ 本机 git 身份是占位值（`github用户名`/`github注册邮箱`），push 前用户需改。
- ⚠️ **禁止并行 Edit 同一文件**（会静默覆盖前一处改动），逐个 Edit 后复核。

## 文件与数据约定
- 库：`DB/客户库.sqlite3`（**必须在 DB 子文件夹**），表 `customers`，按 `website_key` 去重，WAL；备份 `DB/backups/`。
- 结果 Excel：每轮一份，名 `行业-YYYYMMDD_HHMM-主国家.xlsx`，写在 **`output/`**（`output_dir()`/`ts_result_path()`/`build_result_name()`）。文件名**字典序≠时间序**，`find_latest_result()` 用 `_result_time_key()` 解析日期时间；扫描顺序 output/ → 程序根目录；`LEGACY_RESULT_FILES` 排除旧名与 `~$` 锁文件。`STATE['output']` 存 `output/<文件名>`。「📂 打开结果文件夹」→ `/api/open_folder`。
- ⛔ **结果文件 10 列硬契约**（`_save_enrich_excel` 写、飞书 `build_feishu_records` 与启动 `init_customer_db` 按下标读）：列名与顺序**一个都不能改**；每项须含 `title/url/emails/phones/contact_url/score/rating/snippet/formula/country/industry`。
- 脚本：`补历史欠账.py`（`--dry` 只列清单）+ `.bat`（双击，**GBK 编码**）；`同步数据库到飞书.py`（`--dry-run`）；`回填行业.py`；`demo.py`（环境诊断）。已废弃保留：`找客户_谷歌半自动.py`（有 bug）、`补全联系方式与评分.py`。
- ⚠️ **`.workbuddy/` 与程序零耦合**：全项目对它的引用 = **0 处**，删掉程序照跑。里面只有 AI 记忆（`memory/`）、回归脚本（`_smoke_*`/`_check_*`/`_verify_*`）、一次性探针（`_probe_*`/`_diag_*`）、截图、`_todo.json`（飞书 16 条待删 record_id）。**别删**的是：`memory/MEMORY.md`、`_todo.json`、`_fail_q1_p0.png`（未修的零结果页证据）、`_smoke_maps.py`/`_check_page.py`/`_check_startup.py` 等回归脚本。
- ⚠️ `.gitignore` 只写了 `.workbuddy/_*`，所以 `memory/*.md` 与 `关键词组合预览.png` **被 git 跟踪**（后者是文件名缺 `_` 前缀的历史遗留）。

## 关键词库（关键词库.json）
- `{行业:{细分品类:{具体产品:[词条]}}}`，7 行业 / 9 品类 / 30 产品 / 85 词条。词条字段 `en,cn,de,fr,es,ar` 标准 6 项；`fa` 仅食品 33 条；`it,nl,tr` 85 条全有。
- 改库用一次性 Python 脚本按 `en` 原文做键匹配整体重写；**结构变更必须同步改前端 JS**。备份 `.bak`/`.bak2`。

## 国家 → 语言联动
- `_build_page()` 注入 `counts_js = [(code,name,默认勾选,hl,gl), ...]`；前端 `COUNTRY_LANG`/`COUNTRY_GL` + `applyCountryLang()`，只要该国语言在下拉有选项就自动选中（`langHasData()` 守卫已按用户要求删除）。
- 已知副作用（用户接受）：非食品行业选伊朗/阿富汗 → 标签显示波斯语但词条回落英文。

## 搜索条件多语言化
- `CONDITIONS` 是 **2 元组 `(key, 中文名)`**；骨架在 `COND_TEMPLATE`（含 `{p}`/`{role}`）；角色词 `COND_ROLES[key][lang]`（**8 语言 en/fr/de/es/it/nl/tr/ar**，缺则回落 en，`fa` 暂缺）。`cond_template(key, lang)` 是唯一出口，**后端 `run_search` 与前端预览都必须走它**。
- 语言优先级：前端 `#kwLang` 的 lang → 该国 `hl` → `en`。前端 `start()` POST `lang`，`/api/start` 透传。
- ⚠️ 模板里**不要给 `{p}` 加引号**（`pq_list` 已包好 `"xxx"`），否则拼出 `""nouilles""`。含 OR 的模板**必须用括号锁住同义词组**（`{p} (wholesaler OR distributor)`），去掉会读成 `({p} wholesaler) OR distributor`。
- **国家筛选靠 URL 参数，不在搜索词里**：`COUNTRIES` 4 元组 `(code,name,gl,hl)`，`&gl=<偏好国家>&hl=<界面语言>`。预览面板每条公式尾部显示灰字 `&gl=&hl=`（复制仍复制裸公式）。
- `cr`/`lr`（谷歌高级搜索地区/语言）**实测不值得加**（真机四组对比：`gl/hl` 50% > 叠加 56% 但条数少 > 单用 cr/lr 29% > 无参 25%）。cr 按**主机托管国**过滤，法国 B2B 多用 `.com`，加了反而挤出真客户。城市级精度要 `uule`。用户已拍板保持现状。

## 任务流水线（搜索+补全一体化闭环）
- `run_search(...)` 自身即闭环：每拿到新网站 → `db_upsert_customer` → **立刻** `enrich()` → 评分 → 再 upsert（空值不覆盖）→ 追加 `all_rows` + `STATE['rows']`。凑够 `target_count` 个**新增网站**即停。
- 整轮结束在 `finally` 里 `page.quit()` 后落盘（保证中途「停止」不白跑）；浏览器整轮只开关一次。`auto_enrich=False` 退化为只收线索。
- ⛔ **「补全联系方式+评分」按钮已删除**（连带 `/api/enrich`、`run_enrich()`、`btnEnrich` 等）。**但 `enrich_core`/`_enrich_worklist`/`enrich()`/`_save_enrich_excel` 必须保留**（脚本与搜索链路都在用），别再当死代码删。
- ⚠️ **标签页陷阱**：`enrich()` 用 `page.new_tab()` 开客户站，`open_search` 用 `page.get()`，`ChromiumPage` 操作当前活动标签 → 补全后必须 `_back_to_search(page, search_tab_id)`。⚠️ `ChromiumTab` **没有 `new_tab()`**，搜索必须由 `ChromiumPage` 承担。
- 前端：`counter`/`dbCounter` 随 `poll()` 每秒刷新（`/api/status` 返回 logs/result_count/phase/**rows**/db_total/db_verified）。**实时入库明细表** `#liveBody`（在状态行与日志框之间），`renderRows()` 增量追加、新行淡入、有邮箱绿色等宽、无则灰「未抓到」。
- ⚠️ worklist 判据是「邮箱电话都为空」非「补过没补过」→ 欠账脚本会反复访问抓不到联系方式的站（实测 26 条）。彻底修需加 `enriched_at` 列（未拍板）。

## 谷歌搜索抓取链路（最易碎）
- 判渲染：`RESULT_LINK_CSS = 'css:a:has(h3)'` 条数（`count_results()`）。旧 `page.ele('div#search')` **已失效**，别改回去。
- 开页必须走 `open_search(page, formula, country_params, start=0, min_items=3, attempts=3)`：前 2 轮直连 `/search?q=`，第 3 轮用搜索框兜底。**壳页面**（搜索框在、结果空、`Updating location`）`refresh()` 救不回，**重新导航即可**。
- ⚠️⚠️ **「结果没渲染出来」两种成因，日志分不开（未修）**：① 壳页面（重开能好）；② **谷歌零结果页**（`did not match any documents`，重试同 URL 永远没用，证据 `.workbuddy/_fail_q1_p0.png`）。触发条件 = **新会话第一个谷歌请求 + 重公式**：同浏览器里 33 词公式首次 → 0 条，稍后同一公式 → 10 条（对照组见 `.workbuddy/_probe_open_search.py`）。结论：是**冷会话首请求被降级**，不是 gl/hl 或公式的问题。待拍板修法：软预热（先发一条最简 `search?q=<首个产品词>`，**不是首页**）/ 零结果先换 URL 再重发 / 日志区分两种失败 / 公式减负（中国过滤全开让公式涨到 **33 词**，逼近谷歌 ~32 词上限）。
- `is_blocked()` 三层：`BLOCK_SUBSTR`(`ubuy`/`europages`/`exportgenius`) → `SEARCH_ENGINE_PREFIX`(google./bing./yahoo./duckduckgo./baidu./yandex.) → `BLOCK_DOMAINS` 精确或后缀匹配 + `endswith('.cn')` 兜底。已补 indiamart/trade.gov/worldstopexports/dailyvoice/taobao/tmall。`EXCLUDE_OPTIONS` 是**查询词级**排除（默认全开），与域名黑名单两套，加平台站**两边都加**。
- ⚠️ 结果链接是跳转链，必须 `resolve_goto(page, href, card)`：`/url?q=` 明文解开；`/goto?url=` 加密解不开 → 先取卡片 `<cite>`（`_cite_domain()`），再不行才开标签让谷歌 302（4.1s/条）。**判断跳转链必须用 `_is_search_engine_url()`**（去 `www.` 比前缀）——旧代码硬编码 `google.com/goto`，在 `google.com.hk` 上失配 → 一页 10 条全丢。
- ⚠️ **谷歌限流**：密集请求连返壳页面，三次重试失败跳过本页；**等 90 秒恢复**。别误判成 bug。
- 页面卡顺序：1 目标国家 → 📋 关键词库 → 2 产品关键词（OR/AND/分别搜）→ 3 搜索条件 → 4 参数（`#pages`/`#targetCount`/`#autoEnrich`/`#excludes`）→ 5 关键词组合预览（纯展示，`renderCombos()` 规则必须与后端一致，`COMBO_CACHE` 供复制）。

## 谷歌地图采集（2026-09-29 新增，P0+P1）
- 入口：`/api/start` 按 `source`（`google` 默认 / `maps`）分流到 `run_maps(products, cond_keys, countries, city, target_count, industry, auto_enrich, lang, china_filters)`。前端「4. 参数」卡有数据源单选 + `#mapsCity` 城市框；`onSource()` 切换时隐藏翻页/排除词，显示地图说明。
- 关键选择器：结果列表 `div[role="feed"]`（**要滚 feed 元素本身，不能滚 window**）；卡片 `a[href*="/maps/place/"]`；详情字段靠 `data-item-id` 三件套（`phone:tel:` / `authority`(官网) / `address`）。
- ⚠️ **`maps_detail` 必须用「直接导航到 place URL」而非「点卡片」**：真机实测点开第一条后结果列表被详情替换，其余卡片句柄全 `NoRectError`。改为 `maps_collect_hrefs()` 先把 href 收成字符串，再逐条 `page.get(place_url)`（真机 4/4 全中 5 字段，~1s/条）。
- ⚠️ **身份词必须拼进地图查询词**（`maps_role_word(cond_keys, lang)` 取第一个勾选条件的第一个角色词），否则只返回餐馆（搜 `nouilles` 全是 `Restaurant chinois`）。
- 去重键：`MAPS_PLACE_ID_RE` 抓 `!1s0x...:0x...` → `maps_place_key(url)`，`normalize_domain()` 有 maps 分支。
- 地区定位：`COUNTRY_CENTERS`（25 国中心经纬度，`MAPS_CENTER_DEFAULT='us'`）+ 城市输入框，`maps_search_url(query, country_code, gl, hl, city)` 拼 `https://www.google.com/maps/search/<q>/@<lat>,<lng>,11z?hl=&gl=`。
- 单次硬上限 ~120 条（滚动 `maps_feed_scroll`/`maps_collect_hrefs` 有 `max_rounds` 上限，达上限/到底即停）。达目标即停，落盘复用 10 列 Excel。

## 回归验证脚本（在 `.workbuddy/`，已 gitignore，用绝对路径加载主工具）
- `_smoke_search.py`：打桩测 `run_search` 闭环（不联网不开浏览器，DB 与结果文件指向临时目录），断言入库数/补全次数/切回标签/浏览器开关/`STATE['rows']`/`/api/status`。
- `_check_page.py`：校验页面文案、占位符替换、内嵌 JS 语法（`node --check`）、标签配对、数据源切换元素。
- `_check_live_ui.py`：起临时 Flask(5012)+Chrome 截图 `.workbuddy/_live_ui.png`（先 `m.app.run(port=5011)` 起临时实例可同理真机验页面，不碰真实客户库）。
- `_verify_maps_base.py`：校验国家坐标/地图 URL/去重键。
- `_probe_maps.py`：真机探针地图选择器（可传参 `python _probe_maps.py "nouilles grossiste" Lyon`）。
- **改完搜索链路或前端后各跑一遍。**

## 飞书多维表格
- BASE_TOKEN `ZhSSb18BMajKR7sacxTcCFY0njf`；表 `客户信息` TABLE_ID `tblY38YnVIQ5AYYA`。
- CLI：`C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe`
- 坑：① 调用前 `pop('HERMES_HOME')`；② `+record-list --limit` 上限 200，翻页 `--offset`；③ 返回 `raw['data']` 下 `data`/`fields`/`record_id_list` 平行数组；④ 鉴权参数是 `--base-token`；⑤ **官网字段名就叫 `官网`**（共 17 字段），按「网站/网址」查会静默 0 命中；⑥ `邮箱` 只接受单个合规邮箱，多余写入 `备注`；⑦ `来源渠道`/`跟进状态`/`国家地区` 是 select，值用数组；⑧ 本地「沙特」→ 飞书「沙特阿拉伯」；⑨ 写入用 `+record-batch-create --json @文件`，格式 `{"create_records":[...]}`；⑩ `+field-update` 是**全量 PUT**，改前快照改后核对。
- 飞书「行业」字段选项仍是旧四值；16 条垃圾记录待删，ID 存 `.workbuddy/_todo.json`。

## 本机环境
- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c` 或 PowerShell；PowerShell 输出不回显 → 写临时文件再 Read。
- `wmic` 被屏蔽 → 用 `Get-CimInstance Win32_Process`；查文件占用用 `rstrtmgr.dll`。
- ⚠️ **本机 TCP 端口保留段（Hyper-V/WinNAT）**：`netsh interface ipv4 show excludedportrange protocol=tcp` 实测保留 `4710-4809 / 4810-4909 / 4910-5009 / 5010-5109 / 5110-5209 / 5210-5309 / 5357 / 5358-5457 / 6064-6163 / 50000-50059`，**5000/5011/5012/5013 全都绑不上**（裸 bind 报 errno 13）。可用低端口：`5310-5356`、`5458-6063`、`6164+`、`8000`。**任何本地服务的端口都要能自动避让，别写死**。
- 删文件进回收站：`Add-Type`/`COM` 被拦 → Python `ctypes` 调 `SHFileOperationW`（`FO_DELETE`+`FOF_ALLOWUNDO|...`）。⚠️ 返回非 0 也可能已成功，必须 `os.path.exists()` 复查。
- Python：`D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`

## 数据质量待办
- 库里混有平台垃圾域名（joybuy.fr/dreamstime/chegg/thomasnet/trendyol/u-buy/petz.ae/suppliergo/archive.org/tiktok 等）约 25~36 条未清（2026-09-28 曾从 120 清到 90）。
- `PRODUCT_WORDS = ['litter','liner','cat','pet']` 写死猫砂垫且**子串匹配无词边界**（`?cacatcha_type=` 白送 10 分）；换行业必须同步改。
- ⛔ **评分在非英语场景方向是反的（20 条法国结果复盘实锤，未修）**：`CTYPE_WORDS`(`wholesale/distributor/importer/trading/dealer/supplier/bulk`) 全是英文，法语 `grossiste/distributeur/fournisseur/importateur` 一个不认 → 真客户 `miamland.com`（标题 «Grossiste Pâtes et Nouilles»）只 10 分；而 `fr.kompass.com/y/importer/`（B2B 名录）因 URL 含英文 `importer` 白拿 35 分。⚠️ 与「条件词已多语言化」是**两套词表**（`COND_ROLES` 搜索用、`CTYPE_WORDS` 评分用），没打通。`score_item()` **只有加分无减分** → 「抓到邮箱电话」≈「高分」（农业部站与真批发商同为 55 分）。根治三件事：① `CTYPE_WORDS` 多语言化 ② `PRODUCT_WORDS` 按本轮产品词动态传入+词边界 ③ 加否决/减分项（`.gov`/`.gc.ca`、点评站、餐馆、菜谱、歌词、B2B 名录、新闻、企业黄页）。
- **行业取值两头不一致**：`回填行业.py` 写 宠物用品/家具家居/汽配，词库下拉是 宠物用品/LED照明/家具/服装/机械零部件/户外用品/食品，飞书又是旧四值 → 待统一。
- 未拍板遗留：① 「半自动组合/纯手工输入」单选（用户提过）未实现；② 冷会话首请求降级修法未定；③ 飞书 16 条垃圾待删；④ 客户库 id=154 淘宝记录待清。
