# 细节备份：功能坑 / 回归脆弱点 / 本机环境 / 外部站点

> MEMORY.md 有注入长度上限，超了会被截断 → 「细节」放这里，「硬约束」留在 MEMORY.md。
> **改 飞书 / 搜索 / 地图 / 扩展 / 词库 / 本机环境 / 回归脚本 / 海关采集 之前，先读本文件。**

## 飞书 / 搜索 / 地图 / 扩展（坑全在档案 M1/M2/M5/M8/M9，动手前必读）
- ① 飞书调用前 `pop('HERMES_HOME')`，**字段名就叫 `官网`**，`+field-update` 是**全量 PUT**，结果 Excel **无来源列** → `build_feishu_records()` 按 domain 回库查来源（**50 分门槛对 `[手动采集]` 豁免**）。
- ② 词库 `cond_template(key, lang)` 是**唯一出口**，模板 `{p}` **别加引号**、含 OR **必须用括号**；`COUNTRIES` 是 **4 元组**而前端按 **5 元组**注入（改长度炸两处）；改库后跑 `_kwlib_check.py`。
- ③ 开页必须走 `open_search()`，判跳转必须用 `_is_search_engine_url()`（硬编码 `google.com/goto` 在 `.com.hk` 上一页 10 条全丢）；`enrich()` 用 `new_tab()` 而 `open_search` 用 `get()` → 补全后必须 `_back_to_search()`（`ChromiumTab` **没有 `new_tab()`**）。
- ④ 扩展 `background.js` 是**唯一 fetch 出口**（`popup.js` 里 `fetch(` 必须为 **0**）；CORS 只回显 `chrome-extension://`（**绝不 `*`**）；地图滚 `div[role="feed"]` **本身不是 window** 且**身份词必须拼进查询词**（`maps_role_word`）。
- ⑤ **邮箱噪声过滤**（`_is_noise_email()`，2026-10-10 加）两处**别改回去**：
  - 倍图规则 `NOISE_EMAIL_DIM_RE = ^(?:\d+x|x\d+)$` **绝不能加裸数字分支 `^\d+$`** —— 会误杀 `163.com` / `126.com` / `139.com` 这类**纯数字 label 的合法邮域**（实测确认）。
  - 宿主黑名单**必须后缀匹配**（`dom == h or dom.endswith('.' + h)`），老写法 `n in dom` 会把 `mywix.com` / `shopwix.com` 一起误杀。
  - 过滤判据**只加在 `clean_emails` 这一处**即可覆盖全部 4 条链路；**不要去剥 `<script>`**（会让 JSON-LD 里的真实联系邮箱一起丢）。`EMAIL_OK` 有 3 份独立副本，改抽取不改导出（老脏数据仍会进 Excel/飞书）。

## 本机环境 / 数据待办（清单见档案 §7、§7.5、§9.4）
- bash 残缺（`dirname`/`ls`/`grep`/`tail` 不可用）→ 用 `python -c`；**别从 Bash 里 invoke PowerShell**；`wmic` 屏蔽 → `Get-CimInstance Win32_Process`。项目解释器 `D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`（managed 3.13.12 没装 DrissionPage/Flask）；启动 = 根目录 `python 客户开发工具.py`。TCP 保留段每次开机漂移 → **别把「某端口被保留」写进断言**（`_check_startup` 原 `assert got_port != 5000` 就是这类假红；2026-10-06 已改成 `can_bind(got_port)` + Flask 能起来。查证：`netsh int ipv4 show excludedportrange protocol=tcp` 现在最早一段是 **5357**，5000 已可用）。`C:` 紧张 → 回归临时目录已钉 D:。
- ⛔ **评分在非英语场景方向是反的**（法国实锤，未修）：`CTYPE_WORDS` 全英文、`score_item()` **只有加分无减分**。其余待办：平台垃圾域名 25~38 条未清、`重标行业.py` 待改 **23 条**（未 `--apply`）、评分/冷会话/飞书垃圾/阶段 B 拆包未拍板、**M16/M17/M18 未 commit**。
- ✅ 已拍板（别再当待办）：`DB/backups/` 少掉的几份 + `关键词库.json.bak*` 是用户自己删的，不恢复、不排查。

## 回归脆弱点（假红 ≠ 产品 bug）—— 红了先看错误类型
- 别写死端口原因 `'10013'`；**也别写死「某端口被保留」**（`_check_startup` 原 `assert got_port != 5000`，TCP 排除区间随开机漂移 → 环境变好了反而报红；已改 `can_bind(got_port)`）。
- 别写死 managed 运行时的**版本号目录**：`_check_ext.py` / `_run_all_reg.py` 原写死 `node\versions\22.22.2-3\node.exe`，本机升到 `22.22.2-6` 后 `_check_ext` 的 B 组与两个 JS 冒烟**全部 FileNotFoundError**（看着像「回归红了」，其实是环境漂移）→ 已改成扫 `versions/*/node.exe` 取最新，末位才退回旧写死路径。
- 别 sleep 等 async → 轮询；截图只当证据（`try/except`）且**固定定位元素必须视口截图**。
- `_smoke_ext_live` 两遍共用 `core.db` → 时间戳要清零；`<select>` 赋不存在的 value 会被忽略 → 用 `createElement('option')`。
- `send_file` 持句柄 → 删前 `dl.close()`；别沿用上一段页面状态；行名/数量动态取。
- 临时库默认落 `C:`（满则 `disk I/O error`、一批 DB 项集体假红）→ 已钉 `TMPDIR/TEMP/TMP` 到 `.workbuddy/_reg_tmp`。
  - ⚠️ 同类症状还有 **`sqlite3.OperationalError: attempt to write a readonly database`**（杀软/IO 抖动锁住刚建出来的 sqlite，或 `-wal/-shm` 建不出来）—— **单跑一遍往往就绿**，别去改产品代码。判据：红了先看错误类型，再看**单跑能不能复现**。
  - 注意：`TEMP` 的钉扎只在**走 `_run_all_reg.py`** 时生效；**单跑某个脚本**时它仍落 `C:\Users\admin\AppData\Local\Temp`（所以单跑更容易撞见这类假红）。
- **备份名只到秒** → 同秒删两次覆盖同名 → 「文件名差集」断言假红 → 改判 **mtime**。

## verbatim / 静态断言注意
- `_check_page.py` R4 glue：`'from core.ui import PAGE_HTML, _build_page'` 必须**单独一行**。
- R12 一批 verbatim 断言（`renderedTail`/`closest('.livedel-btn')`/`id="liveDelModal"`/两条 CSS 规则/`Escape`/`Enter`/两页 `<thead>` 逐字相等…）—— 泛化后要**逐条对着新代码重对**，**该改断言就别改代码**。
- 静态断言看**代码**不看源码文本：用 `ast`；`STATE['xxx']` 是 `ast.Subscript`+`ast.Constant`，不是 `ast.Name`。
- `_smoke_ext_popup.js` 的 DOM 桩很薄（无 `dataset/classList/closest`，`document` 只有 `getElementById`）。

## 「本轮明细」计数口径（M19，2026-10-10）
- 徽章 / 状态行报**两组数**：`有效` = 新增（`st.added`，＝结果 Excel 的行数）/ `共` = 明细行数（`session_rows.length` = 新增 + 已在库）。
- ⛔ **本轮已结束时**（`session_active == false`）`_flush_manual_session` 会把 `session_rows` 清空、但**刻意留着 `added`/`existed`** 给 `roundTally` 拼「本轮写入 X 行新客户」→ 徽章与悬停**必须按 `session_active` 门禁取这两个数**，否则会显示 **「有效 5 / 共 0」**（自相矛盾）。`_smoke_ext_popup.js` 7a 段、`_check_manual_ui.py` E 段的 `liveBadgeText(null,0)` / `{session_active:false,…}` 两条断言就是钉这个的（改动前真跑红过一次）。
- 这份口径有**三处独立实现**，改口径要一起改：`ui/manual.html::liveBadgeText()`、`extension/popup.js::renderSession()`、以及共享组件 `ui/live-table.js`（主页那张仍走默认 `n + ' 条'`，它 `showExisted:false`、N 天然＝有效数）。**`popup.js` 那份不在共享组件里**。
- 改 `ui/live-table.js` → **只重算 `_check_page.py` 的 `_BUILT_SHA`**（`_TMPL_SHA` 是 `ui/page.html` 的原文，不动）。

## 海关商品编码采集（`海关商品编码采集.py` + 同名 `.bat`，2026-10-06）
- ⛔ 站点 `stats.customs.gov.cn` 挂**瑞数信息动态防护**：普通 HTTP 客户端一律返回 **412**，响应体是 `$_ts` 变量 + 混淆 JS（`/Qy6JDI4LYvbD/….js`）+ meta refresh + `SF_cookie_251`。**纯 requests / urllib 拿不到任何数据** → 只能真浏览器（复用 `create_browser_page()`，别另写一套 `ChromiumOptions`）。
- 入口：`GET /queryData/selectCodeTs`（**服务端整页渲染**，不是 AJAX）；菜单里的入口是 `/paramManager/selComplexList`（商品参数）。
- 取数配方：在 `#Search_form` 里设 `codeLength=8`（**隐藏域和 4 个同名 radio 都要设**）+ `pageSize=200`（**页面默认是 10**，不设会变成 897 页）+ `yearId` + `codeTsList=''` + `searchKey=''` + `pageNum=n` → `form.submit()` → 整页跳转。
- **参数闸门**：`yearId='2025'` → **8969** 条 / 45 页；`yearId=''`（不限年份）→ **104238** 条 / 522 页。核对：44×200 + 末页 169 = 8969；首行 `01012100 改良种用马`，末行 `99000000 跨境电商B2B简化申报商品`。
- ⛔ 名称取 `.th-line` 的 **`title` 属性**：可见文本被 CSS 截断（8969 条里 35 条形如 `…`）。
- ⛔ 就绪判据 = 「`hidPageNum` == 目标页号 **且** 行数 > 0」；只看「有没有行」会在提交后的一瞬间**静默读到上一页**。
- `page.run_js` 里**裸 IIFE 必须加外层 `return`**（`return (function(){…})();`），否则取不到返回值 → 会被误判成「找不到 `#Search_form`」。
- `.bat` 用 `Write` 工具落盘即 **GBK + CRLF**（实测，与既有两个 `.bat` 一致）；**别用 bash heredoc 拼**（`\\` 会被改写成 `//` → 路径坏掉 + 中文脚本名「找不到文件」）。
- ⛔ `page.get('http://stats.customs.gov.cn/')` 会**偶发**返回 **39 字节空文档**（`<html><head></head><body></body></html>`）。这**不是被封**：同一时刻 `requests` 仍能拿到标准的 412 挑战页（~2440 字节）。空文档**不会自愈，傻等只会超时** → 必须**重新导航**重试（`_open()` 已做 4 轮重开 + 每轮最多 20s 轮询）。
- 断点缓存 `.workbuddy/_海关编码_pages.json`：45 页全命中 → 直接汇总、**不开浏览器**（秒级）；`--fresh` 强制重抓，`--dry` 只探总数。
