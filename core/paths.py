# -*- coding: utf-8 -*-
"""结果 Excel 命名、输出目录、程序根定位、最新结果查找、当前结果文件（原 `客户开发工具.py` 第 261–352 行整段搬入）。

本模块零 core 内依赖（只用标准库），处在依赖图底层，不会成环。

⚠️ 本文件里 `_app_dir()` 的语义是「**项目根**」（入口脚本、output/、DB/、ui/ 所在处），
   不是「本文件所在目录」—— 搬家时这一点必须显式处理，见该函数注释。
"""
import glob
import os
import re
from datetime import datetime

# ================= 结果 Excel 命名 =================
# 每轮生成一份结果文件，命名：行业-日期_时间-主国家.xlsx，例 宠物用品-20260928_0145-加拿大.xlsx
# 搜索过程中每条线索就地补全联系方式，整轮结束时（含中途停止）写出这一份唯一产物，固定 10 列。
LEGACY_RESULT_FILES = (
    '客户结果_含联系方式与评分.xlsx',            # 最早的手工文件名
    '客户搜索结果_20260928_0118.xlsx',           # 已停用的旧 5 列搜索文件
)   # 旧名字：仅兜底读取，不再生成，也不参与「最新结果」评选
RESULT_DATE_RE = re.compile(r'\d{8}')                        # 结果文件名必带 8 位日期
OUTPUT_DIRNAME = 'output'   # 所有结果 Excel 统一放这个子文件夹，程序目录不再堆文件
# 谷歌地图 place 链接里的稳定标识段（/maps/place/<名字>/@lat,lng,11z/data=...!1s0x...:0x...）
MAPS_PLACE_ID_RE = re.compile(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', re.I)


def _app_dir():
    """程序根目录（入口脚本 `客户开发工具.py`、output/、DB/、ui/ 所在处）。

    ⚠️⚠️ 这是本模块唯一「搬家后会静默出错」的地方，绝不能图省事写成
    `os.path.dirname(os.path.abspath(__file__))`：
    本文件位于 <root>/core/paths.py，那样算出来是 <root>/core，
    于是 output_dir() 变成 <root>/core/output、db_path() 变成 <root>/core/DB/客户库.sqlite3
    —— 等于换了一份**空数据库**，工具看起来像「客户全丢了」，而且不报任何错。
    所以这里取「上一级」，并额外向上探测入口脚本兜底（万一以后包被挪到更深一层）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.dirname(here)                       # 正常即 <root>
    probe = d
    for _ in range(4):
        if os.path.exists(os.path.join(probe, '客户开发工具.py')):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:                         # 到盘符根了，别再往上
            break
        probe = parent
    return d


def output_dir():
    """结果 Excel 的输出目录（绝对路径）；不存在就自动创建。"""
    d = os.path.join(_app_dir(), OUTPUT_DIRNAME)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return _app_dir()   # 创建失败（如只读磁盘）时退回程序目录，保证仍能出文件
    return d


def _safe_name_part(text, default):
    """把行业/国家变成安全的文件名片段，去掉 Windows 非法字符。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', '', (text or '').strip())
    s = s.strip(' .')
    return s or default


def build_result_name(industry, country):
    """行业-日期_时间-主国家.xlsx（日期精确到分）。"""
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    return (f'{_safe_name_part(industry, "未分类")}-{stamp}'
            f'-{_safe_name_part(country, "未知国家")}.xlsx')


def ts_result_path(industry='', country=''):
    """本轮结果 Excel 的绝对路径（存于 output/ 子目录）；同分钟同行业同国家重名时自动加 _2/_3，避免覆盖。"""
    base_dir = output_dir()
    stem = build_result_name(industry, country)[:-len('.xlsx')]
    path = os.path.join(base_dir, stem + '.xlsx')
    n = 2
    while os.path.exists(path):
        path = os.path.join(base_dir, f'{stem}_{n}.xlsx')
        n += 1
    return path


# ================= 客户库查询的导出（/db 页用，与「本轮结果」完全隔离）=================
QUERY_EXPORT_DIRNAME = '查询导出'


def query_export_dir():
    """查询导出目录 = output/查询导出/。

    ⚠️⚠️ 必须是**子目录**，不能直接落 output/ 根下：
        `find_latest_result()` 只 glob output/ 一层，并且靠「文件名里有 8 位日期」
        筛候选 —— 查询导出表的名字天然带日期，一旦落在根下就会被它选中当
        「最新结果文件」，把飞书导出的目标劫持到一份查询结果上。
        放进子目录后 glob 扫不到，两条链路彻底隔离。
    """
    d = os.path.join(output_dir(), QUERY_EXPORT_DIRNAME)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return output_dir()          # 建不出子目录时退回 output/，保证仍能出文件
    return d


def build_query_export_name(count=0):
    """查询导出文件名：查询导出-日期_时间-共N条.xlsx（精确到秒，避免连续导出互相覆盖）。"""
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f'查询导出-{stamp}-共{int(count)}条.xlsx'


def ts_query_export_path(count=0):
    """查询导出文件的绝对路径；同秒重名时自动加 _2/_3。"""
    d = query_export_dir()
    stem = build_query_export_name(count)[:-len('.xlsx')]
    path = os.path.join(d, stem + '.xlsx')
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f'{stem}_{n}.xlsx')
        n += 1
    return path


def _result_time_key(path):
    """结果文件的排序键：优先取文件名里的日期+时间（如 宠物用品-20260928_0145-加拿大.xlsx
    -> 202609280145）。文件名开头是行业名，所以不能用整个文件名排序；用 mtime 又会被
    「打开旧文件另存一下」带偏，故从名字里解析时间，解析不到才退回 mtime。"""
    m = re.search(r'(\d{8})(?:_(\d{4}))?', os.path.basename(path))
    stamp = (m.group(1) + (m.group(2) or '')) if m else ''
    return (stamp, os.path.getmtime(path))


def find_latest_result():
    """找最近一次生成的结果 Excel。优先 output/ 子目录，其次程序根目录（兼容早先版本
    直接写在根目录的老文件）；都没有时回退到旧文件名。"""
    search_dirs = [output_dir(), _app_dir()]
    try:
        cands = []
        for d in search_dirs:
            for p in glob.glob(os.path.join(d, '*.xlsx')):
                name = os.path.basename(p)
                if name.startswith('~$') or name in LEGACY_RESULT_FILES:
                    continue
                if RESULT_DATE_RE.search(name):
                    cands.append(p)
        if cands:
            return max(cands, key=_result_time_key)
    except Exception:
        pass
    for d in search_dirs:
        for name in LEGACY_RESULT_FILES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return ''


# 当前结果文件；每轮任务结束会指向新的时间戳文件。
# ⚠️ 这是全项目唯一「会被重新赋值」的模块级变量。它搬进本模块后：
#   · 入口与 core/db.py 一律按 `paths.ENRICH_FILE` 读写（属性访问才拿到活值）；
#   · 入口用 PEP 562 模块级 __getattr__ 把它转发给老脚本（补历史欠账.py 读 kf.ENRICH_FILE）；
#   · 任何人都不许 `from core.paths import ENRICH_FILE` —— 那只是 import 那一刻的快照。
ENRICH_FILE = find_latest_result()
DB_DIR = 'DB'                  # 数据库统一放在 DB 子文件夹
DB_FILE = '客户库.sqlite3'
