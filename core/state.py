# -*- coding: utf-8 -*-
"""飞书导出配置 + 运行时状态（原 `客户开发工具.py` 第 353–374 行的配置/状态段，加上 `log()` 函数）。

`log()` 为什么必须放在这一层：`core/db.py` 的 `init_customer_db()` 会调 `log()`。
如果 `log` 留在入口 `客户开发工具.py` 里，`core/db.py` 就得反过来 import 入口模块
（入口又会 import core.db）—— 形成循环导入。放在这里，依赖方向恒定：
state ← db、state ← 入口，无环。

STATE 是**可变对象**（dict）+ STATE_LOCK 是 Lock，所以入口和其它模块用
`from core.state import STATE` 导入同一个对象即可，改内容不需要任何转发。
这一点和 `core/paths.py` 的 ENRICH_FILE（会被整体重新赋值）完全不同 —— 那个才需要 PEP 562 转发。
"""
import threading

# ================= 飞书导出配置 =================
BASE_TOKEN = 'ZhSSb18BMajKR7sacxTcCFY0njf'   # 飞书客户管理多维表格
TABLE_ID = 'tblY38YnVIQ5AYYA'                # 客户数据表 ID
LARK_CLI = r'C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe'
IMPORT_JSON = 'import_records.json'           # 导出时生成的临时 JSON
# 本地国家简称 -> 飞书「国家/地区」选项名（飞书叫"沙特阿拉伯"，代码里简称"沙特"）
COUNTRY_STANDARD = {'沙特': '沙特阿拉伯', '加拿大(法语)': '加拿大'}

# ================= 全局运行状态 =================
STATE = {
    'running': False,
    'phase': '',           # search / export
    # 本轮数据源：'google' / 'maps'（api_start 写入）。/api/status 会带给页面 ——
    # ⚠️ 手机 / 平板打开页面时**没有经过 start()**，收不到本地的 RUN_SOURCE，
    #    只能靠这里回传，否则地图任务会显示成「搜索中 / 个网站」。
    'source': 'google',
    'logs': [],
    'result_count': 0,
    # 本轮采集明细（供前端实时表格显示：公司/域名/邮箱/电话/评分/行业/国家）。
    # ⛔ 自动链路（run_search / run_maps）**采集时不写客户库**了（2026-10-13）：
    #    这些行一直只在内存里，直到用户点「📥 导出 Excel」才由 /api/export_excel 逐条入库 + 落盘。
    #    所以元素必须是**完整 11 键行**（含 snippet / formula，`_row10()` 落盘要用），
    #    再加一个本轮内唯一的 `n`（前端 ✕ 用它定位）。它就是「待导出的那一份」，
    #    **不需要再维护第二个列表** —— 这也是原来那套墓碑机制能整条下线的原因。
    'rows': [],
    'done': False,
    'output': '',
    'stop': False,
    # ---- 「待核对 / 待导出」状态（自动链路，2026-10-13）----
    # 采集跑完（含中途点「停止」）不再自动写结果 Excel，只把这里置 True：
    # 用户先核对明细、删掉不想要的行，再点「📥 导出 Excel」才 ① 逐条入库 ② 写表。
    # 同一时刻最多一轮待导出；api_start 重置、/api/export_excel 成功后清掉。
    'pending_export': False,
    'export_error': '',    # 导出失败原因（前端红字提示；数据保留，可直接重试）
    # 轮次序号（M28）：凡是「清空 logs 开新一轮」的地方（api_start / api_export_feishu）
    # 都要 +1。/api/status 回传给页面 —— 前端靠它判断「日志被清过了」，把本地的日志游标
    # `since` 归零。没有它时，另一台设备（手机）的 since 会停在上一轮的大数字，
    # 后端切片 `logs[since:]` 永远为空 → 日志区永久空白，且不报任何错。
    'round': 0,
}
STATE_LOCK = threading.Lock()

# ================= 手动采集（Chrome 扩展 / /manual 页）专用状态 =================
# ⚠️ 为什么不复用 STATE['running'] / STATE['stop']：
#    那两个是给自动链路（run_search / run_maps）用的开关，手动采集**允许**在自动任务之外
#    独立进行；一旦共用，点「停止手动采集」会把正在跑的自动搜索一起杀掉。
# ⚠️ 复用同一把 STATE_LOCK 保护（够用，且避免再多一把锁的嵌套顺序问题）。
#
# 这里有两套并行但不同层级的语义，别混：
#   · 「本轮会话」（session_*）：手动采集的**收集批**。扩展单点与批量粘贴都往里攒，
#     点「🏁 结束并生成 Excel」时才一次性落盘成一份结果 Excel（对齐自动搜索的整轮落盘）。
#     added/existed/failed/upgraded 这四个计数也是**本轮**语义（开轮时清零）。
#   · 「批量任务」（running/stop/total/done/current）：只是本轮里的一个可选子过程
#     （/manual 页粘贴一批网址串行跑）。一轮里可以跑多次批量。
MANUAL_STATE = {
    # ---- 批量任务语义（单条采集不置 running）----
    'running': False,      # 批量队列是否在跑
    'stop': False,         # 只停手动队列
    'total': 0,            # 本次批量总数
    'done': 0,             # 本次批量已处理条数
    'current': '',         # 当前正在处理的网址
    # ---- 本轮会话语义（added/existed/failed/upgraded 都按本轮统计）----
    'added': 0,            # 本轮新增入库
    'existed': 0,          # 本轮已在库里跳过
    'failed': 0,           # 本轮失败
    'upgraded': 0,         # 本轮走了「升级到 Chromium」的次数
    'session_active': False,      # 本轮是否进行中（唯一权威开关）
    'session_started_at': 0.0,    # 本轮开始时间戳
    # 本轮明细 list，元素带 kind：'added'（11 键完整行）/ 'existed'（仅 title+url）
    # ⚠️ 还带 rid：本轮内自增的行号（取值自 session_rid_seq）。删除单条靠它精确指认 ——
    #    同一个 url 在同一轮里可能既有一条 added 又有一条 existed（第二次采被去重跳过），
    #    按 url 删会一次删两条。
    'session_rows': [],
    'session_rid_seq': 0,         # rid 发号器（开轮时清零）
    'session_industry': '',       # 本轮行业口径（开轮那一刻记下，中途改表单不覆盖）
    'session_country': '',        # 本轮国家口径（同上）
    'session_excel': '',          # 上次结束并生成的**文件基名**（前端显示用）
    'session_error': '',          # 落盘失败原因（前端红字提示，保留数据可直接重试）
    'session_finish_pending': False,  # 批量运行中点「结束」的挂起标志，由 worker 的 finally 消费
    # ---- 扩展心跳 ----
    'ext_last_seen': 0.0,  # 扩展最后一次调接口的时间戳（当心跳用）
}


def log(msg):
    """同时打印到控制台和写到日志队列（前端轮询读取）"""
    line = str(msg)
    with STATE_LOCK:
        STATE['logs'].append(line)
    print(line)
