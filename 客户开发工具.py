# -*- coding: utf-8 -*-
"""
谷歌客户开发网页工具（本地运行）
在浏览器里填产品词、勾选搜索条件、选国家，点"开始搜索"自动执行。
搜索与补全已合并为一个闭环：每搜到一个新网站，立刻访问它抓邮箱/电话并评分，
然后再去搜下一个；凑够目标数量就停，最后写出带邮箱/电话/评分的客户名单。
（批量清理客户库历史欠账的能力保留在命令行脚本「补历史欠账.py」里，界面上没有按钮。）

启动方法：python 客户开发工具.py  （会自动打开浏览器页面）
依赖：Flask、DrissionPage、openpyxl
"""
import threading
import time
import random
import re
import os
import glob
import json
import subprocess
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
import webbrowser
import tempfile
import socket
from urllib.parse import quote, parse_qs, urlparse, urljoin

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.common import Keys
from openpyxl import Workbook, load_workbook
from flask import Flask, request, jsonify

# ================= 可配置常量 =================
# 搜索条件（来自手册第2/3/11章），网页上可勾选
# ⚠️ 含 OR 的模板一律用括号把「同义词组」锁在一起：`A B OR C` 里 OR 往左管到哪儿谷歌的解读是模糊的，
# 不锁会退化成 `(A B) OR C`，让 C 单独生效、把任意行业的同类角色拉进结果（实测确认）。括号谷歌支持。
# 搜索条件：(key, 中文名)。顺序即页面上的顺序，前两个默认勾选。
CONDITIONS = [
    ('wholesale',   '找批发商/分销商'),
    ('importer',    '找进口商/贸易商'),
    ('buyer',       '找采购/买家'),
    ('oem',         '找OEM贴牌客户'),
    ('retailer',    '找零售商/连锁门店'),
    ('project',     '找工程/项目客户'),
    ('exhibitor',   '找协会/展会名录'),
    ('contact',     '直达联系页'),
    ('linkedin',    '找采购决策人(领英)'),
]

# 公式骨架：{p} = 产品词，{role} = 本地化角色词（见 COND_ROLES）
COND_TEMPLATE = {
    'wholesale': '{p} ({role})',
    'importer':  '{p} ({role})',
    'oem':       '{p} ({role})',
    'retailer':  '{p} ({role})',
    'project':   '{p} ({role})',
    'exhibitor': '{p} ({role}) filetype:pdf',
    # ⚠️ {p} 本身已带引号（run_search 里 pq_list 就包好了），这里绝对不能再加引号，
    # 否则会拼出 site:linkedin.com/in ""nouilles"" 这种双引号（2026-09-28 修）。
    'contact':   'inurl:contact {p}',            # 无角色词，各语言一致
    'linkedin':  'site:linkedin.com/in {p} ({role})',
}

# 角色词的本地化表达。⚠️ 这一点很关键：只写英文条件词去搜法语/德语市场时，
# 谷歌是在非英语页面里找英文词，命中的多是英文版块或 B2B 名录站，真正的本地买家反而搜不到。
# 缺失的语言自动回落到 en（如波斯语 fa 暂缺，与「伊朗/阿富汗词条回落英文」的已知行为一致）。
COND_ROLES = {
    'wholesale': {
        'en': 'wholesaler OR distributor',
        'fr': 'grossiste OR distributeur',
        'de': 'Großhändler OR Distributor',
        'es': 'mayorista OR distribuidor',
        'it': 'grossista OR distributore',
        'nl': 'groothandel OR distributeur',
        'tr': 'toptancı OR distribütör',
        'ar': 'تاجر جملة OR موزع',
    },
    'importer': {
        'en': 'importer OR "trading company"',
        'fr': 'importateur OR "société de négoce"',
        'de': 'Importeur OR Handelsunternehmen',
        'es': 'importador OR "empresa comercializadora"',
        'it': 'importatore OR "società commerciale"',
        'nl': 'importeur OR handelsonderneming',
        'tr': 'ithalatçı OR "ticaret şirketi"',
        'ar': 'مستورد OR "شركة تجارية"',
    },
    'oem': {
        'en': 'OEM OR "private label" OR "own brand" OR "brand owner"',
        'fr': 'OEM OR "marque distributeur" OR "marque propre" OR acheteur',
        'de': 'OEM OR "Private Label" OR Eigenmarke OR Markeninhaber',
        'es': 'OEM OR "marca blanca" OR "marca propia" OR propietario de marca',
        'it': 'OEM OR "marca privata" OR "marchio proprio" OR titolare del marchio',
        'nl': 'OEM OR "huismerk" OR "eigen merk" OR merkeigenaar',
        'tr': 'OEM OR "özel marka" OR "kendi markası" OR marka sahibi',
        'ar': 'OEM OR "العلامة الخاصة" OR "علامة تجارية خاصة"',
    },
    'buyer': {
        'en': 'buyer OR procurement OR purchasing OR sourcing',
        'fr': 'acheteur OR achats OR approvisionnement OR sourcing',
        'de': 'Einkäufer OR Einkauf OR Beschaffung OR Sourcing',
        'es': 'comprador OR compras OR aprovisionamiento OR abastecimiento',
        'it': 'buyer OR acquisti OR approvvigionamento OR sourcing',
        'nl': 'inkoper OR inkoop OR sourcing OR procurement',
        'tr': 'alıcı OR satın alma OR tedarik OR sourcing',
        'ar': 'مشتري OR مشتريات OR توريد OR مصادر',
    },
    'retailer': {
        'en': 'retailer OR "chain store"',
        'fr': 'détaillant OR "chaîne de magasins"',
        'de': 'Einzelhändler OR Ladenkette',
        'es': 'minorista OR "cadena de tiendas"',
        'it': 'dettagliante OR "catena di negozi"',
        'nl': 'detailhandel OR winkelketen',
        'tr': 'perakendeci OR "zincir mağaza"',
        'ar': 'تاجر تجزئة OR "سلسلة متاجر"',
    },
    'project': {
        'en': 'project OR contractor OR tender',
        'fr': "projet OR entrepreneur OR appel d'offres",
        'de': 'Projekt OR Auftragnehmer OR Ausschreibung',
        'es': 'proyecto OR contratista OR licitación',
        'it': 'progetto OR appaltatore OR gara',
        'nl': 'project OR aannemer OR aanbesteding',
        'tr': 'proje OR yüklenici OR ihale',
        'ar': 'مشروع OR مقاول OR مناقصة',
    },
    'exhibitor': {
        'en': 'association OR "exhibitor list"',
        'fr': 'association OR "liste des exposants"',
        'de': 'Verband OR Ausstellerliste',
        'es': 'asociación OR "lista de expositores"',
        'it': 'associazione OR "elenco espositori"',
        'nl': 'vereniging OR deelnemerslijst',
        'tr': 'dernek OR "fuar katılımcı listesi"',
        'ar': 'جمعية OR "قائمة العارضين"',
    },
    'linkedin': {
        'en': 'purchasing OR procurement OR buyer',
        'fr': 'achats OR approvisionnement OR acheteur',
        'de': 'Einkauf OR Beschaffung OR Einkäufer',
        'es': 'compras OR aprovisionamiento OR comprador',
        'it': 'acquisti OR approvvigionamento OR acquirente',
        'nl': 'inkoop OR inkoopbeheer OR inkoper',
        'tr': 'satın alma OR tedarik OR alıcı',
        'ar': 'مشتريات OR توريد OR مشتري',
    },
}

# 有本地化角色词的语言（fa 暂缺 → 回落英文）
COND_LANGS = ('en', 'fr', 'de', 'es', 'it', 'nl', 'tr', 'ar')


def cond_template(key, lang='en'):
    """返回某条件的公式模板（仍含 {p} 占位符），角色词按语言本地化，缺该语言则回落英文。"""
    tpl = COND_TEMPLATE.get(key, '{p}')
    if '{role}' not in tpl:
        return tpl
    roles = COND_ROLES.get(key, {})
    word = roles.get(lang) or roles.get('en') or ''
    return tpl.replace('{role}', word)

# 产品关键词库数据文件（行业 → 产品 → 关键词，三级分类）
# 以后加行业/产品/关键词直接编辑这个 JSON 文件，不用改代码
KEYWORD_LIB = '关键词库.json'

# 国家列表：(代码, 名称, gl, hl)
COUNTRIES = [
    ('us', '美国', 'us', 'en'),
    ('ca', '加拿大', 'ca', 'en'),
    ('uk', '英国', 'uk', 'en'),
    ('de', '德国', 'de', 'de'),
    ('fr', '法国', 'fr', 'fr'),
    ('it', '意大利', 'it', 'it'),
    ('es', '西班牙', 'es', 'es'),
    ('nl', '荷兰', 'nl', 'nl'),
    ('be', '比利时', 'be', 'fr'),
    ('ch', '瑞士', 'ch', 'fr'),
    ('ma', '摩洛哥', 'ma', 'fr'),
    ('dz', '阿尔及利亚', 'dz', 'fr'),
    ('tn', '突尼斯', 'tn', 'fr'),
    ('sn', '塞内加尔', 'sn', 'fr'),
    ('ca_fr', '加拿大(法语)', 'ca', 'fr'),
    ('ae', '阿联酋', 'ae', 'en'),
    ('sa', '沙特', 'sa', 'ar'),
    ('qa', '卡塔尔', 'qa', 'en'),
    ('kw', '科威特', 'kw', 'en'),
    ('om', '阿曼', 'om', 'en'),
    ('bh', '巴林', 'bh', 'en'),
    ('eg', '埃及', 'eg', 'ar'),
    ('ir', '伊朗', 'ir', 'fa'),
    ('af', '阿富汗', 'af', 'fa'),
    ('tr', '土耳其', 'tr', 'tr'),
]

# 国家中心经纬度：仅「谷歌地图」数据源用来定位地图视野（@lat,lng,zoom）。
# 刻意做成独立字典而不并进 COUNTRIES —— COUNTRIES 是 4 元组，前端 counts_js 按 5 元组注入、
# run_search 按 4 元组解包，改元组长度会连带炸掉两处。
COUNTRY_CENTERS = {
    'us': (39.83, -98.58), 'ca': (56.13, -106.35), 'uk': (54.00, -2.00),
    'de': (51.17, 10.45), 'fr': (46.60, 2.21), 'it': (41.87, 12.57),
    'es': (40.46, -3.75), 'nl': (52.13, 5.29), 'be': (50.50, 4.47),
    'ch': (46.82, 8.23), 'ma': (31.79, -7.09), 'dz': (28.03, 1.66),
    'tn': (33.89, 9.54), 'sn': (14.50, -14.45),
    'ca_fr': (46.81, -71.21),          # 加拿大法语区锁定魁北克
    'ae': (23.42, 53.85), 'sa': (23.89, 45.08), 'qa': (25.35, 51.18),
    'kw': (29.31, 47.48), 'om': (21.51, 55.92), 'bh': (26.07, 50.55),
    'eg': (26.82, 30.80), 'ir': (32.43, 53.69), 'af': (33.94, 67.71),
    'tr': (38.96, 35.24),
}
MAPS_CENTER_DEFAULT = 'us'   # 取不到国家中心坐标时的兜底

# 排除条件（网页上可勾选，每项带说明）：(key, 排除词, 说明)
EXCLUDE_OPTIONS = [
    ('amazon', '-amazon', '亚马逊（电商平台）'),
    ('ebay', '-ebay', 'eBay（电商平台）'),
    ('etsy', '-etsy', 'Etsy（电商平台）'),
    ('wikipedia', '-wikipedia', '维基百科（百科）'),
]
EXCLUDE_DEFAULT = ' '.join(v for _, v, _ in EXCLUDE_OPTIONS)

# 中国商家过滤：全部默认开启；query 为空的项目只在结果/联系方式阶段判断。
# key, 搜索公式排除词, 页面标签, 说明
CHINA_FILTER_OPTIONS = [
    ('alibaba', '-alibaba', '排除 Alibaba', '中国 B2B 平台'),
    ('made-in-china', '-made-in-china', '排除 Made-in-China', '中国 B2B 平台'),
    ('globalsources', '-globalsources', '排除 Global Sources', '供应商聚合平台'),
    ('1688', '-1688', '排除 1688', '中国 B2B 平台'),
    ('taobao', '-taobao -tmall', '排除淘宝 / 天猫', '中国电商平台'),
    ('cn', '-site:.cn', '排除 .cn 域名', '中国域名'),
    ('supplier_words', '-"China manufacturer" -"Chinese supplier"', '排除中国供应商关键词', '中国供应商/制造商表达'),
    ('factory_words', '-"factory in China" -"China factory"', '排除中国工厂关键词', '中国工厂表达'),
    ('made_in_china_words', '-"made in China"', '排除中国制造关键词', '中国制造表达'),
    ('platform_words', '', '排除中国供应商平台关键词', 'supplier platform / B2B 平台信号'),
    ('phone_86', '', '排除 +86 中国电话', '联系方式信号'),
    ('wechat', '', '排除微信 / WeChat', '联系方式信号'),
    ('qq', '', '排除 QQ', '联系方式信号'),
    ('address_cn', '', '排除中文地址或明显中国地址', '地址/语言信号'),
    ('email_cn', '', '排除中国供应商邮箱或 .cn 邮箱', '邮箱域名信号'),
    ('competitor_cn', '', '排除明显中国同行网站', '中国同行/工厂信号'),
    ('directory_cn', '', '排除中国 B2B 名录和供应商聚合站', '名录/聚合站信号'),
]
CHINA_FILTER_DEFAULTS = {k for k, _, _, _ in CHINA_FILTER_OPTIONS}

BLOCK_DOMAINS = [
    'amazon.com', 'ebay.com', 'etsy.com', 'walmart.com', 'wikipedia.org',
    'youtube.com', 'facebook.com', 'instagram.com', 'linkedin.com',
    'reddit.com', 'pinterest.com', 'google.com',
    'sec.gov', 'archive.org', 'tiktok.com', 'sourceready.com',
    'investorroom.com', 'nbd.ltd',
    # 行业名录 / 数据站 / 政府统计站：不是买家，但常年在搜索首页（实测混入）
    'indiamart.com', 'trade.gov', 'worldstopexports.com', 'dailyvoice.com',
]
# 子串匹配：这些站有多个后缀（.com/.fr/.co.uk）或域名变体，逐个列举容易漏
BLOCK_SUBSTR = ['ubuy', 'europages', 'exportgenius']
# 搜索引擎自身的域名族：谷歌会按出口 IP 跳到 google.com.hk / google.de 等区域站，
# 只写 'google.com' 拦不住，结果里会混进谷歌内部链接（曾污染出假客户 google.com.hk）。
SEARCH_ENGINE_PREFIX = ('google.', 'bing.', 'yahoo.', 'duckduckgo.', 'baidu.', 'yandex.')

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
    """程序所在目录（主工具脚本所在处）。"""
    return os.path.dirname(os.path.abspath(__file__))


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


ENRICH_FILE = find_latest_result()   # 当前结果文件；每轮任务结束会指向新的时间戳文件
DB_DIR = 'DB'                  # 数据库统一放在 DB 子文件夹
DB_FILE = '客户库.sqlite3'

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
    'logs': [],
    'result_count': 0,
    'rows': [],            # 本轮已入库明细（供前端实时表格显示：公司/域名/邮箱/电话/评分）
    'done': False,
    'output': '',
    'stop': False,
}
STATE_LOCK = threading.Lock()


# ================= SQLite 客户库 =================
def db_path():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_dir = os.path.join(base_dir, DB_DIR)
    os.makedirs(db_dir, exist_ok=True)   # DB 文件夹不存在时自动创建
    return os.path.join(db_dir, DB_FILE)


def maps_place_key(url):
    """从谷歌地图 place 链接里提取稳定去重键（结尾的 0x...:0x... 十六进制段）。
    比商家名可靠（同名商家多），也比 place_id 好取（place_id 还得额外解析一次）。
    取不到返回空串。"""
    m = MAPS_PLACE_ID_RE.search(url or '')
    return ('maps:' + m.group(1).lower()) if m else ''


def normalize_domain(url):
    """把网址规整为稳定的公司去重键。"""
    try:
        raw = (url or '').strip().lower()
        if '@' in raw and '://' not in raw:
            return ''
        # 谷歌地图 place 链接：没官网的商家会落到这里。必须给个稳定键，
        # 否则 netloc 全是 google.com —— 既被搜索引擎黑名单拦掉，又互相覆盖成一条。
        mk = maps_place_key(raw)
        if mk:
            return mk
        netloc = urlparse(raw if '://' in raw else 'https://' + raw).netloc
        netloc = netloc.split(':', 1)[0].removeprefix('www.')
        return netloc
    except Exception:
        return ''


def normalize_email(email):
    return (email or '').strip().lower()


def db_connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_customer_db():
    """初始化客户库，并把已有评分 Excel 导入一次。"""
    with closing(db_connect()) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            website_key TEXT UNIQUE,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            contact_url TEXT DEFAULT '',
            country TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            score INTEGER,
            rating TEXT DEFAULT '',
            snippet TEXT DEFAULT '',
            search_formula TEXT DEFAULT '',
            source TEXT DEFAULT '谷歌搜索',
            status TEXT DEFAULT '未联系',
            next_follow_up TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            verified_at TEXT DEFAULT ''
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email)')
        # 老库升级：补齐后加的列（已有 DB 不会因缺列报错）
        cols = [r[1] for r in conn.execute('PRAGMA table_info(customers)')]
        if 'industry' not in cols:
            conn.execute("ALTER TABLE customers ADD COLUMN industry TEXT DEFAULT ''")
        conn.commit()
    # 只在库为空时迁移旧结果，保证重复运行不会重复导入。
    with closing(db_connect()) as conn:
        empty = conn.execute('SELECT 1 FROM customers LIMIT 1').fetchone() is None
    if empty and os.path.exists(ENRICH_FILE):
        try:
            wb = load_workbook(ENRICH_FILE, read_only=True)
            ws = wb.active
            for r in ws.iter_rows(min_row=2, values_only=True):
                if r and len(r) > 1 and r[1]:
                    db_upsert_customer({
                        'company_name': r[0], 'website': r[1],
                        'email': r[2] or '', 'phone': r[3] or '',
                        'contact_url': r[4] or '', 'score': r[5],
                        'rating': r[6] or '', 'snippet': r[7] or '',
                        'search_formula': r[8] or '',
                        'country': r[9] if len(r) > 9 else '',
                    })
            wb.close()
            log('✅ 已将现有评分 Excel 导入 SQLite 客户库')
        except Exception as ex:
            log(f'⚠️ 旧 Excel 导入客户库失败：{type(ex).__name__}: {ex}')


def db_upsert_customer(data):
    """新增或合并客户；空值不会覆盖数据库里已有的有效值。"""
    website = (data.get('website') or '').strip()
    website_key = normalize_domain(website)
    email = normalize_email(data.get('email', ''))
    if not website_key and not email:
        return False
    fields = {
        'company_name': data.get('company_name', ''), 'website': website,
        'email': email, 'phone': data.get('phone', ''),
        'contact_url': data.get('contact_url', ''), 'country': data.get('country', ''),
        'industry': data.get('industry', ''),
        'score': data.get('score'), 'rating': data.get('rating', ''),
        'snippet': data.get('snippet', ''), 'search_formula': data.get('search_formula', ''),
        'source': data.get('source', '谷歌搜索'), 'notes': data.get('notes', ''),
    }
    with closing(db_connect()) as conn:
        row = None
        if website_key:
            row = conn.execute('SELECT * FROM customers WHERE website_key=?', (website_key,)).fetchone()
        if row is None and email:
            row = conn.execute('SELECT * FROM customers WHERE lower(email)=?', (email,)).fetchone()
        if row is None:
            conn.execute('''INSERT INTO customers
                (company_name,website,website_key,email,phone,contact_url,country,industry,score,rating,
                 snippet,search_formula,source,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (fields['company_name'], fields['website'], website_key, fields['email'],
                 fields['phone'], fields['contact_url'], fields['country'], fields['industry'],
                 fields['score'], fields['rating'], fields['snippet'], fields['search_formula'],
                 fields['source'], fields['notes']))
            conn.commit()
            return True
        updates = []
        values = []
        for key, value in fields.items():
            if value not in ('', None) and (key != 'score' or isinstance(value, (int, float))):
                updates.append(f'{key}=?')
                values.append(value)
        if website_key and not row['website_key']:
            updates.append('website_key=?')
            values.append(website_key)
        updates.append("last_seen_at=datetime('now','localtime')")
        values.append(row['id'])
        conn.execute(f"UPDATE customers SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()
        return False


def db_stats():
    init_customer_db()
    with closing(db_connect()) as conn:
        total = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM customers WHERE score IS NOT NULL").fetchone()[0]
    return {'total': total, 'verified': verified, 'file': DB_DIR + '/' + DB_FILE}


def log(msg):
    """同时打印到控制台和写到日志队列（前端轮询读取）"""
    line = str(msg)
    with STATE_LOCK:
        STATE['logs'].append(line)
    print(line)


def create_browser_page():
    """启动独立的 Chrome 调试实例，避免依赖用户手工开启 9222 端口。"""
    profile_dir = tempfile.mkdtemp(prefix='waimao_dp_chrome_')
    # 先向系统申请一个空闲端口，避免固定 9222 被其它 Chrome 占用。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        debug_port = sock.getsockname()[1]
    options = ChromiumOptions().set_local_port(debug_port)
    chrome_candidates = [
        # Playwright 自带的 Chromium 不受用户现有 Chrome 进程和配置影响。
        r'C:\Users\admin\AppData\Local\ms-playwright\chromium-1200\chrome-win64\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    ]
    chrome_path = next((p for p in chrome_candidates if os.path.exists(p)), '')
    if chrome_path:
        options.set_browser_path(chrome_path)
    options.set_user_data_path(profile_dir)
    options.set_argument('--remote-allow-origins=*')
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-popup-blocking')
    log('启动独立浏览器实例（自动分配调试端口）...')
    return ChromiumPage(options)


# ================= 搜索核心（复用原脚本） =================
def is_blocked(href):
    if not href or not href.startswith('http'):
        return True
    netloc = urlparse(href).netloc.lower().split(':', 1)[0].removeprefix('www.')
    if any(s in netloc for s in BLOCK_SUBSTR):
        return True
    if netloc.startswith(SEARCH_ENGINE_PREFIX):     # google.com.hk / google.de 等区域域名
        return True
    return any(netloc == d or netloc.endswith('.' + d) for d in BLOCK_DOMAINS)


def china_filter_terms(enabled_keys):
    """返回当前勾选的、需要追加到 Google 公式的排除词。"""
    enabled = set(enabled_keys or ())
    return ' '.join(query for key, query, _, _ in CHINA_FILTER_OPTIONS
                    if key in enabled and query).strip()


def china_filter_reasons(title, url, snippet='', emails=None, phones=None,
                         html_text='', enabled_keys=None):
    """按勾选项返回明确的中国供应商过滤原因。

    单独出现 China/中文/中国进口不会触发过滤；只有和供应商、工厂、联系方式或
    中国平台等明确信号组合时才过滤，避免误删真实海外进口商。
    """
    enabled = set(enabled_keys or ())
    if not enabled:
        return []
    emails = emails or []
    phones = phones or []
    text = ' '.join(str(x or '') for x in (title, url, snippet, html_text)).lower()
    host = normalize_domain(url)
    reasons = []

    platform_hosts = {
        'alibaba': ('alibaba.com',),
        'made-in-china': ('made-in-china.com',),
        'globalsources': ('globalsources.com',),
        '1688': ('1688.com',),
        'taobao': ('taobao.com', 'tmall.com'),
    }
    for key, hosts in platform_hosts.items():
        if key in enabled and any(host == h or host.endswith('.' + h) for h in hosts):
            reasons.append(f'命中{key}平台')

    if 'cn' in enabled and (host.endswith('.cn') or host == 'cn'):
        reasons.append('网站域名为 .cn')

    supplier_signal = bool(re.search(
        r'china\s+(?:manufacturer|supplier|factory|wholesaler)|'
        r'chinese\s+(?:manufacturer|supplier|factory)|'
        r'中国(?:供应商|厂家|工厂|制造商)', text, re.I))
    factory_signal = bool(re.search(
        r'(?:factory|manufacturer|supplier)\s+(?:in|from)\s+china|'
        r'(?:china|chinese)\s+(?:factory|manufacturer|supplier)', text, re.I))
    made_signal = bool(re.search(r'(?:made|manufactured)\s+in\s+china|中国制造', text, re.I))
    chinese_signal = bool(re.search(r'[\u4e00-\u9fff]', text))

    if 'supplier_words' in enabled and supplier_signal:
        reasons.append('标题/摘要命中中国供应商关键词')
    if 'factory_words' in enabled and factory_signal:
        reasons.append('标题/摘要命中中国工厂关键词')
    if 'made_in_china_words' in enabled and made_signal:
        reasons.append('标题/摘要命中中国制造关键词')

    platform_signal = bool(re.search(
        r'(?:supplier|manufacturer|factory)\s+(?:directory|platform|marketplace)|'
        r'b2b\s+(?:platform|marketplace)|供应商平台|供应商名录|厂家直销', text, re.I))
    if 'platform_words' in enabled and platform_signal and (supplier_signal or chinese_signal):
        reasons.append('命中中国供应商平台关键词')

    if 'phone_86' in enabled and (re.search(r'\+\s*86(?:[\s().-]*\d){6,}', text)
                                  or any(re.search(r'\+\s*86(?:[\s().-]*\d){6,}', str(p)) for p in phones)):
        reasons.append('联系方式含 +86 中国电话')
    if 'wechat' in enabled and re.search(r'\bwechat\b|\bweixin\b|微信', text, re.I):
        reasons.append('页面含微信/WeChat')
    if 'qq' in enabled and re.search(r'\bqq\b|腾讯', text, re.I):
        reasons.append('页面含 QQ')

    address_signal = bool(re.search(
        r'(?:中国|china|广东|浙江|江苏|福建|山东|深圳|广州|东莞|义乌|宁波|佛山)'
        r'.{0,40}(?:地址|工厂|厂家|制造|supplier|factory|manufacturer|road|street|road)', text, re.I))
    if 'address_cn' in enabled and address_signal:
        reasons.append('页面含明显中国地址/工厂信息')

    if 'email_cn' in enabled and any(str(e).lower().split('@')[-1].endswith('.cn') for e in emails):
        reasons.append('邮箱域名为 .cn')

    if 'competitor_cn' in enabled and (supplier_signal or factory_signal or (made_signal and chinese_signal)):
        reasons.append('命中明显中国同行/工厂信号')

    directory_signal = any(x in host for x in ('1688.com', 'alibaba.com', 'made-in-china.com',
                                                'globalsources.com', 'taobao.com', 'tmall.com'))
    if 'directory_cn' in enabled and directory_signal:
        reasons.append('命中中国 B2B 名录/供应商聚合站')
    return list(dict.fromkeys(reasons))


def url_key(href):
    p = urlparse(href)
    return p.netloc + p.path.rstrip('/')


def has_captcha(page):
    try:
        return 'unusual traffic' in page.html or bool(page.ele('#captcha-form', timeout=1))
    except Exception:
        return False


def wait_captcha(page, max_wait=180):
    if not has_captcha(page):
        return True
    log('⚠️ 检测到谷歌人机验证，请在浏览器窗口手动完成（脚本每3秒检测，最多等3分钟）')
    waited = 0
    while waited < max_wait and not STATE['stop']:
        time.sleep(3)
        waited += 3
        if not has_captcha(page):
            log('✅ 验证完成，继续')
            return True
    return False


def sleep_check(seconds):
    """可被停止标志打断的睡眠；正常睡完返回 True，被停止则 False"""
    end = time.time() + seconds
    while time.time() < end:
        if STATE['stop']:
            return False
        time.sleep(min(0.5, max(0, end - time.time())))
    return True


RESULT_LINK_CSS = 'css:a:has(h3)'      # 自然结果的标题链接


def search_url(formula, country_params='', start=0):
    """直连搜索 URL。实测向搜索框打字会先落到首页的 "Updating location..." 中间态，
    结果迟迟不渲染（a:has(h3) 抓到 0 条）；直连 /search?q= 则立刻有 9~10 条结果。"""
    url = 'https://www.google.com/search?q=' + quote(formula) + country_params
    if start:
        url += f'&start={start}'
    return url


def maps_search_url(query, country_code=MAPS_CENTER_DEFAULT, gl='', hl='en', city=''):
    """谷歌地图搜索 URL（路径式，非官方 api=1 形态 —— 路径式批量名录更稳）。

    定位靠两层：① 城市名直接进查询词（Google 官方推荐的位置限定方式，比 gl 硬）；
    ② @lat,lng,zoom 把地图视野锁到该国中心，影响返回的商家范围。
    hl/gl 与网页搜索是同一套参数语义。
    """
    q = ' '.join(x for x in ((query or '').strip(), (city or '').strip()) if x).strip()
    lat, lng = COUNTRY_CENTERS.get(country_code, COUNTRY_CENTERS[MAPS_CENTER_DEFAULT])
    url = f'https://www.google.com/maps/search/{quote(q)}/@{lat},{lng},11z'
    extra = []
    if hl:
        extra.append(f'hl={hl}')
    if gl:
        extra.append(f'gl={gl}')
    return url + (('?' + '&'.join(extra)) if extra else '')


def count_results(page):
    try:
        return len(page.eles(RESULT_LINK_CSS, timeout=1))
    except Exception:
        return 0


def wait_results(page, min_items=3, timeout=12):
    """等结果真正渲染出来再抓。旧版判断 div#search 已失效（新版谷歌页面没有 #search/#rso），
    改为数「标题链接」条数，并等它稳定两轮。返回 True 表示已就绪。"""
    end = time.time() + timeout
    last, stable, tick = -1, 0, 0
    while time.time() < end:
        n = count_results(page)
        if n >= min_items:
            if n == last:
                stable += 1
                if stable >= 1:
                    return True
            else:
                stable = 0
            last = n
        else:
            tick += 1
            if tick % 5 == 0 and has_captcha(page):     # page.html 较贵，每 5 秒才查一次
                if not wait_captcha(page):
                    return False
        time.sleep(1)
    return False


def type_search(page, formula):
    """兜底策略：向搜索框输入关键词并回车。返回是否成功发出。"""
    try:
        box = page.ele('textarea[name=q]', timeout=8) or page.ele('input[name=q]', timeout=5)
    except Exception:
        box = None
    if not box:
        return False
    try:
        box.click()
        time.sleep(random.uniform(0.3, 0.8))
        box.input(formula, clear=True)
        time.sleep(random.uniform(0.5, 1.2))
        box.input(Keys.ENTER)
        return True
    except Exception:
        return False


def open_search(page, formula, country_params, start=0, min_items=3, attempts=3):
    """打开搜索结果页，并确认结果真的渲染出来。
    实测谷歌偶尔只返回一个「壳页面」：搜索框在、结果区是空的（同时混着
    "Updating location" / 地区选择），此时 page.refresh() 无效，**重新导航一次即可恢复**。
    所以这里做多轮重开，最后一轮换成搜索框输入兜底。"""
    for i in range(attempts):
        if i:
            if not sleep_check(random.uniform(1.0, 2.5)):
                return False
        try:
            if i == attempts - 1:
                type_search(page, formula)              # 最后一轮换策略
            else:
                page.get(search_url(formula, country_params, start))
        except Exception as e:
            log(f'   打开搜索页失败（第 {i + 1} 次）：{type(e).__name__}: {e}')
            continue
        if wait_results(page, min_items=min_items, timeout=12):
            if i:
                log(f'   ↻ 第 {i + 1} 次重新打开后结果才渲染出来')
            return True
        if i < attempts - 1:
            log(f'   ↻ 结果没渲染出来（第 {i + 1} 次），重新打开搜索页…')
    log(f'   ⚠️ 连续 {attempts} 次都没取到结果，跳过本页')
    return False


def _is_search_engine_url(href):
    """是否落在搜索引擎自己的域名上（含 google.com.hk / google.de 这类区域站）。"""
    try:
        host = urlparse(href).netloc.lower().split(':', 1)[0].removeprefix('www.')
    except Exception:
        return False
    return host.startswith(SEARCH_ENGINE_PREFIX)


def _cite_domain(card):
    """结果卡片里的 <cite> 写着客户真实网址（形如「https://www.x.com › 路径」）。
    谷歌 /goto?url=<加密串> 没法直接解析，而 cite 是零成本的真域名来源（实测与真实跳转同域）。"""
    node = card
    for _ in range(4):
        try:
            node = node.parent()
        except Exception:
            break
        if node is None:
            break
        try:
            c = node.ele('css:cite', timeout=0)
        except Exception:
            c = None
        if not c:
            continue
        try:
            txt = (c.text or '').strip()
        except Exception:
            continue
        mm = re.search(r'https?://[^\s›]+', txt)
        if mm:
            return mm.group(0).rstrip('/')
        mm = re.match(r'([\w.-]+\.[a-z]{2,})', txt)
        if mm:
            return 'https://' + mm.group(1)
    return ''


def resolve_goto(page, href, card=None):
    """把结果链接换成客户真实网址，三种形态依次处理：
      ① 已经是目标站地址     → 原样返回
      ② /url?q=<明文地址>    → 直接解析（免联网）
      ③ /goto?url=<加密串>   → 无法解析：先用卡片里的 <cite>（真实域名、零成本），
                               再不行才真开一个标签让谷歌 302 跳过去。
    ⚠️ 区域域名（google.com.hk / google.de）同样算谷歌跳转链。原来只认 'google.com/goto'，
    在区域站下整条结果会被当成谷歌自己的链接、遭黑名单丢弃（实测一页 10 条全丢光）。"""
    href = (href or '').strip()
    if not href:
        return href
    if not _is_search_engine_url(href):
        return href
    try:
        q = parse_qs(urlparse(href).query).get('q', [''])[0]
    except Exception:
        q = ''
    if q.startswith('http'):
        return q
    dom = _cite_domain(card) if card is not None else ''
    if dom:
        return dom
    tab = None
    try:
        tab = page.new_tab(href)
        tab.wait.doc_loaded(timeout=15)
        time.sleep(0.4)
        return tab.url
    except Exception:
        return None
    finally:
        if tab:
            try:
                tab.close()
            except Exception:
                pass


def _closest_snippet(node):
    """往上找摘要容器；取不到就返回空字符串（绝不为此抛异常打断整轮搜索）。"""
    cur = node
    for _ in range(4):
        try:
            cur = cur.parent()
        except Exception:
            return ''
        if cur is None:
            return ''
        for css in ('css:.VwiC3b', 'css:[data-sncf]', 'css:span.aCOpRe',
                    'css:div[style*="line-clamp"]'):
            try:
                s = cur.ele(css, timeout=0)
            except Exception:
                s = None
            if s:
                try:
                    return (s.text or '').strip()
                except Exception:
                    return ''
    return ''


def extract_results(page, seen_titles, china_filters=None):
    """抓取一页自然结果。返回 (结果列表, 被黑名单过滤的条数)。
    seen_titles 只在确认保留后才写入，避免被过滤掉的标题污染去重集合。
    DrissionPage 4.1 的 parent() 找不到元素会抛异常而不是返回 None，故一律包 try。"""
    results, blocked = [], 0
    china_reasons = Counter()
    try:
        anchors = page.eles(RESULT_LINK_CSS, timeout=10)
    except Exception:
        anchors = []
    for a in anchors:
        try:
            h3 = a.ele('tag:h3', timeout=0)
            title = (h3.text or '').strip() if h3 else ''
        except Exception:
            title = ''
        if not title or title.startswith('AI Mode'):
            continue
        if title in seen_titles:
            continue
        try:
            raw = (a.attr('href') or '').strip()
        except Exception:
            raw = ''
        real = resolve_goto(page, raw, a)      # 传 a 是为了能从卡片 <cite> 兜底取真域名
        if not real or is_blocked(real):
            blocked += 1
            continue
        snippet = _closest_snippet(h3)
        reasons = china_filter_reasons(title, real, snippet=snippet,
                                       enabled_keys=china_filters)
        if reasons:
            blocked += 1
            for reason in reasons:
                china_reasons[reason] += 1
            continue
        seen_titles.add(title)
        results.append({'title': title, 'url': real, 'snippet': snippet})
    return results, blocked, dict(china_reasons)


# ================= 补全评分（复用原脚本） =================
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
EMAIL_OK = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$')
PHONE_RE = re.compile(r'(?:\+\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}')
NOISE_EMAIL = ['wixpress.com', 'shopify.com', 'squarespace.com', 'wix.com',
               'example.com', 'example.org', 'schema.org', 'google.com',
               'wordpress.org', 'myshopify.com']
CONTACT_PATHS = ['/contact', '/contact-us', '/pages/contact-us', '/contactus']
CTYPE_WORDS = ['wholesale', 'distributor', 'importer', 'trading', 'dealer', 'supplier', 'bulk']
PRODUCT_WORDS = ['litter', 'liner', 'cat', 'pet']
BLOG_WORDS = ['blog', 'news', 'article', 'tips-and-advice']


def clean_emails(html):
    out = []
    for m in EMAIL_RE.findall(html):
        dom = m.split('@')[1].lower()
        if any(n in dom for n in NOISE_EMAIL):
            continue
        if m.lower() not in out:
            out.append(m.lower())
    return out[:3]


def clean_phones(html):
    out = []
    for m in PHONE_RE.findall(html):
        m = m.strip()
        if m and m not in out:
            out.append(m)
    return out[:3]


def enrich(page, url):
    info = {'emails': [], 'phones': [], 'contact_url': '', 'china_signal_text': ''}
    signal_parts = []
    tab = None
    try:
        tab = page.new_tab(url)
        tab.wait.doc_loaded(timeout=10)
        html = tab.html or ''
        signal_parts.append(html[:80000])
        info['emails'] = clean_emails(html)
        info['phones'] = clean_phones(html)
        if not info['emails']:
            p = urlparse(url)
            base = f'{p.scheme}://{p.netloc}/'
            for path in CONTACT_PATHS[:2]:
                try:
                    tab.get(urljoin(base, path.lstrip('/')))
                    tab.wait.doc_loaded(timeout=8)
                except Exception:
                    continue
                contact_html = tab.html or ''
                signal_parts.append(contact_html[:80000])
                e = clean_emails(contact_html)
                if e:
                    info['emails'] = e
                    info['phones'] = info['phones'] or clean_phones(contact_html)
                    info['contact_url'] = tab.url
                    break
    except Exception as ex:
        log(f'   访问失败: {url[:50]} {type(ex).__name__}')
    finally:
        if tab:
            try:
                tab.close()
            except Exception:
                pass
    info['china_signal_text'] = '\n'.join(signal_parts)
    return info


def _back_to_search(page, tab_id):
    """补全时会新开临时标签页去访问客户网站，抓完把活动标签切回搜索主标签，
    避免下一步 open_search 的导航落到客户网站上。
    即使切不回去也不致命（enrich 自己会关掉临时标签），所以吞掉异常。"""
    if not tab_id:
        return
    try:
        page.activate_tab(tab_id)
    except Exception:
        pass


def score_item(title, url, info):
    s = 0
    text = (title + ' ' + url).lower()
    if info['emails']:
        s += 30
    if info['phones']:
        s += 15
    if info['contact_url']:
        s += 10
    if any(w in text for w in CTYPE_WORDS):
        s += 25
    if any(w in text for w in PRODUCT_WORDS):
        s += 10
    if not any(w in text for w in BLOG_WORDS):
        s += 10
    return s


def rating(s):
    if s >= 70:
        return '重点客户'
    if s >= 50:
        return '普通客户'
    return '观察'


# ================= 谷歌地图名录采集（与网页搜索并列的第二条链路） =================
# 地图与网页搜索是两条独立链路：run_search 一行不动，这里自成一套。
# 三条与网页搜索不同的硬事实：
#   ① 电话/官网/完整地址只存在于「左侧详情面板」，列表卡片层拿不到 → 必须逐条点开；
#   ② 单次搜索硬上限约 120 条，滚到底会出「…the end of the list」→ 到末尾就收手，不硬凑；
#   ③ 定位靠「城市名进查询词 + @lat,lng 视野」，且结果受出口 IP 所在地影响。
MAPS_FEED_CSS = 'css:div[role="feed"]'
MAPS_CARD_CSS = 'css:div[role="feed"] a[href*="/maps/place/"]'
# 详情面板就绪判据：这三个 data-item-id 锚点因无障碍依赖而比混淆 class 稳得多
MAPS_DETAIL_READY = (
    'css:button[data-item-id="address"]',
    'css:button[data-item-id^="phone:tel:"]',
    'css:a[data-item-id="authority"]',
)
# 列表末尾提示（hl 会让文案本地化，所以多语言都要认）
MAPS_END_HINTS = ('reached the end of the list', 'fin de la liste', 'ende der liste',
                  'final de la lista', 'fine dell', 'einde van de lijst',
                  'listenin sonuna', 'نهاية القائمة')


def db_has_customer(website):
    """库里是否已有这个网站（只查不写）。用来在「点开详情 + 访问官网」之前就跳过老客户，
    省掉最贵的那两步 —— 比 run_search 里「先插一条再判断」的做法省事。"""
    key = normalize_domain(website)
    if not key:
        return False
    with closing(db_connect()) as conn:
        return conn.execute('SELECT 1 FROM customers WHERE website_key=? LIMIT 1',
                            (key,)).fetchone() is not None


def _maps_attr(page, css, attr=None, timeout=1):
    """读一个元素的属性/文本/绝对链接；找不到或读失败都返回空串。
    地图 DOM 会小幅改版，这里全程容错，宁可字段留空也不要整轮崩掉。"""
    try:
        el = page.ele(css, timeout=timeout)
    except Exception:
        el = None
    if not el:
        return ''
    try:
        if attr == 'link':
            return (el.link or '').strip()
        if attr:
            return (el.attr(attr) or '').strip()
        return (el.text or '').strip()
    except Exception:
        return ''


def maps_consent_wall(page):
    """谷歌地图首访可能弹 Cookie 同意墙，挡住列表与详情面板。"""
    try:
        if 'consent.google' in (page.url or '').lower():
            return True
        return bool(page.ele('css:form[action*="consent"]', timeout=0.5))
    except Exception:
        return False


def maps_open(page, url, attempts=2):
    """打开地图搜索页并等结果列表出现。返回 True 表示有列表。
    注意地图**没有**网页搜索那种「零结果页」，判据就是 feed 在不在。"""
    for i in range(attempts):
        if STATE['stop']:
            return False
        try:
            page.get(url)
            page.wait.doc_loaded(timeout=15)
        except Exception as e:
            log(f'⚠️ 地图页打开失败（第 {i + 1} 次）：{type(e).__name__}')
            continue
        if maps_consent_wall(page):
            log('⚠️ 谷歌地图弹出 Cookie 同意墙：请在浏览器窗口点「全部接受」，脚本最多等 60 秒')
            for _ in range(30):
                if STATE['stop']:
                    return False
                time.sleep(2)
                if not maps_consent_wall(page):
                    break
        if not wait_captcha(page):
            return False
        if page.ele(MAPS_FEED_CSS, timeout=12):
            return True
        log(f'↻ 地图结果列表没渲染出来（第 {i + 1} 次），重新打开…')
        if not sleep_check(2):
            return False
    return False


def maps_cards(page):
    """当前 feed 里的商家卡片链接（列表层只有名称/评分/类目，拿不到电话官网）。"""
    try:
        return page.eles(MAPS_CARD_CSS, timeout=5) or []
    except Exception:
        return []


def maps_reached_end(feed):
    """feed 里出现「已到列表末尾」提示就该停止滚动。"""
    if feed is None:
        return False
    try:
        text = (feed.text or '').lower()
    except Exception:
        return False
    return any(h in text for h in MAPS_END_HINTS)


def maps_feed_scroll(page, want, max_rounds=16):
    """滚动结果面板加载更多商家，返回卡片列表。
    ⚠️ 必须滚 feed 元素本身 —— 滚 window 在地图上完全无效（实测）。
    退出条件三条：够 want 条 / 连续两轮不增长 / 命中列表末尾提示。"""
    cards = maps_cards(page)
    if not cards:
        return []
    try:
        feed = page.ele(MAPS_FEED_CSS, timeout=5)
    except Exception:
        feed = None
    stalled = 0
    for _ in range(max_rounds):
        if STATE['stop'] or len(cards) >= want:
            break
        try:
            if feed:
                feed.scroll.to_bottom()
            else:
                page.scroll.down(2000)
        except Exception:
            try:
                page.run_js('const f=document.querySelector(\'div[role="feed"]\');'
                            'if(f){f.scrollTop=f.scrollHeight;}')
            except Exception:
                pass
        if not sleep_check(random.uniform(1.5, 2.5)):
            break
        new_cards = maps_cards(page)
        if len(new_cards) > len(cards):
            cards = new_cards
            stalled = 0
            try:
                feed = page.ele(MAPS_FEED_CSS, timeout=3)
            except Exception:
                pass
        else:
            stalled += 1
        if stalled >= 2 or maps_reached_end(feed):
            break
    return cards


def maps_collect_hrefs(page, want, max_rounds=16):
    """滚列表 → 把商家链接取成字符串列表。
    刻意转成字符串再返回：元素句柄在页面导航后会失效，字符串不会。"""
    cards = maps_feed_scroll(page, want, max_rounds)
    hrefs, seen_h = [], set()
    for c in cards:
        try:
            h = (c.link or c.attr('href') or '').strip()
        except Exception:
            continue
        if h and h not in seen_h:
            seen_h.add(h)
            hrefs.append(h)
    return hrefs


def maps_detail(page, place_url):
    """导航到某个商家的 place 页面并读左侧详情面板。读不到返回 None。

    ⚠️ 不要改成「逐个点列表卡片」：真机实测点开第一条后，搜索结果列表就被详情页替换掉，
    剩下的卡片元素立刻全部失效（NoRectError）。所以直接导航到卡片 href 指向的 place URL ——
    每条多一次页面加载（约 2~3 秒），但彻底摆脱 SPA 元素失效问题。
    面板里各字段都可能合法缺失（有的商家就是没电话、没官网），缺了就留空，不算失败。
    """
    try:
        page.get(place_url)
        page.wait.doc_loaded(timeout=15)
    except Exception as e:
        log(f'     · 打开商家页失败：{type(e).__name__}')
        return None
    ready = False
    for _ in range(10):
        if STATE['stop']:
            return None
        for css in MAPS_DETAIL_READY:
            try:
                if page.ele(css, timeout=0.8):
                    ready = True
                    break
            except Exception:
                continue
        if ready:
            break
        time.sleep(0.3)
    if not ready:
        return None
    # 电话：data-item-id 形如 phone:tel:+3347889xxxx —— 与界面语言无关，最稳
    phone = ''
    try:
        el = page.ele('css:button[data-item-id^="phone:tel:"]', timeout=1)
        if el:
            phone = (el.attr('data-item-id') or '').split('phone:tel:', 1)[-1].strip()
            if not phone:
                phone = (el.attr('aria-label') or '').split(':', 1)[-1].strip()
    except Exception:
        phone = ''
    website = _maps_attr(page, 'css:a[data-item-id="authority"]', attr='link', timeout=1)
    address = ''
    try:
        el = page.ele('css:button[data-item-id="address"]', timeout=1)
        if el:
            address = (el.attr('aria-label') or '').split(':', 1)[-1].strip() \
                or (el.text or '').strip()
    except Exception:
        address = ''
    category = _maps_attr(page, 'css:button[jsaction*="category"]', timeout=0.6) \
        or _maps_attr(page, 'css:button.DkEaL', timeout=0.6)
    return {
        'name': _maps_attr(page, 'css:h1', timeout=1),
        'phone': phone,
        'website': website,
        'address': address,
        'category': category,
        'place_url': (page.url or place_url),
    }


# ================= 后台任务 =================
def run_search(products, cond_keys, countries, pages, exclude, match='or', target_count=10, industry='',
               auto_enrich=True, lang='', china_filters=None):
    """搜索 + 补全一体化闭环：每搜到一个新网站，立刻访问它抓邮箱/电话并评分、回写客户库，
    然后再去搜下一个；凑够 target_count 个新增网站就停。
    lang = 条件词的搜索语言（如 fr），留空则按所搜国家的 hl 自动取，取不到用 en。
    auto_enrich=False 时退化为「只收集网站线索」（邮箱电话留空、评分按无联系方式算），便于快速铺量。
    目标数量按「本轮新增网站数」计算。整轮结束（含中途停止）写出唯一一份结果 Excel。"""
    page = None
    china_filters = set(CHINA_FILTER_DEFAULTS if china_filters is None else china_filters)
    search_tab_id = None      # 搜索主标签 id：补全会开临时标签，抓完要切回来
    all_rows = []             # 本轮结果（已就地补全），在 finally 里落盘
    search_ok = True
    try:
        init_customer_db()
        STATE['phase'] = 'search'
        log(f'启动浏览器... 产品 {len(products)} 个 × 条件 {len(cond_keys)} 个 × 国家 {len(countries)} 个')
        page = create_browser_page()
        try:
            search_tab_id = page.tab_id    # 记下搜索主标签，补全用临时标签时才好切回来
        except Exception:
            search_tab_id = None
        # 不再先开首页预热：实测「先开首页再搜」更容易触发谷歌的地区识别中间态
        # （Updating location…），导致结果页只渲染出搜索框。每个搜索 URL 自带 gl/hl，预热没必要。

        # 条件数只用于估算总查询数；真正的公式模板按国家语言在下面逐个组装
        cond_count = sum(1 for k, _ in CONDITIONS if k in cond_keys)
        pwords = ['"' + p.strip().strip('"') + '"' for p in products]
        if match == 'and':
            pq_list = [' '.join(pwords)]
        elif match == 'each':
            pq_list = pwords
        else:
            pq_list = [' OR '.join(pwords)]
        total = len(pq_list) * cond_count * len(countries)
        q_index = 0
        seen = set()
        seen_titles = set()
        reached_target = False
        # 整轮汇总统计：让「到底有没有写进客户库」一眼可见
        total_stat = {'cand': 0, 'blocked': 0, 'dup': 0, 'existing': 0, 'added': 0,
                      'mail': 0, 'empty': 0, 'china': Counter()}

        for code, cname, gl, hl in countries:
            country_params = f'&gl={gl}&hl={hl}'
            # 条件词按「搜索语言」本地化：法国站用 grossiste/importateur 这类本地词，
            # 否则就是在法语页面里找英文词，命中的多是非目标站。语言优先级：前端传入 → 该国 hl → en。
            lang = (lang or '').strip() or hl or 'en'
            cond_list = [(name, cond_template(k, lang)) for k, name in CONDITIONS if k in cond_keys]
            log(f'========== 国家：{cname}（gl={gl} hl={hl} · 条件词语言 {lang}） ==========')
            for pq in pq_list:
                for cname2, tmpl in cond_list:
                    if STATE['stop']:
                        log('已停止')
                        return
                    q_index += 1
                    china_exclude = china_filter_terms(china_filters)
                    formula = f'{tmpl.replace("{p}", pq)} {exclude} {china_exclude}'.strip()
                    log(f'[{q_index}/{total}] 搜索({cname}·{cname2})：{pq}')
                    # 打开并确认结果已渲染（内置多次重开，专治谷歌的「壳页面」）
                    open_search(page, formula, country_params)
                    if search_tab_id is None:
                        try:
                            search_tab_id = page.tab_id   # 首次导航后标签一定就绪，补取一次兜底
                        except Exception:
                            pass
                    if not wait_captcha(page):
                        continue
                    stat = {'cand': 0, 'blocked': 0, 'dup': 0, 'existing': 0, 'added': 0,
                            'mail': 0, 'china': Counter()}
                    for pg in range(pages):
                        if pg > 0:
                            if not open_search(page, formula, country_params, pg * 10):
                                break
                            if not wait_captcha(page):
                                break
                        items, blocked_n, china_reasons = extract_results(page, seen_titles, china_filters)
                        stat['cand'] += len(items) + blocked_n
                        stat['blocked'] += blocked_n
                        stat['china'].update(china_reasons)
                        for item in items:
                            key = url_key(item['url'])
                            if key in seen:
                                stat['dup'] += 1
                                continue
                            seen.add(key)
                            item['formula'] = formula
                            item['country'] = cname
                            # ① 就地补全这一个网站；联系方式信号过滤必须发生在入库之前。
                            info = {'emails': [], 'phones': [], 'contact_url': ''}
                            if auto_enrich and not STATE['stop']:
                                info = enrich(page, item['url'])
                                _back_to_search(page, search_tab_id)
                            contact_reasons = china_filter_reasons(
                                item['title'], item['url'], item['snippet'],
                                emails=info.get('emails'), phones=info.get('phones'),
                                html_text=info.get('china_signal_text', ''),
                                enabled_keys=china_filters)
                            if contact_reasons:
                                stat['blocked'] += 1
                                stat['china'].update(contact_reasons)
                                log(f'   过滤：{item["title"][:40]}（{"；".join(contact_reasons)}）')
                                continue
                            # ② 登记线索：已在客户库中的公司不再作为新线索重复展示。
                            existed = not db_upsert_customer({
                                'company_name': item['title'], 'website': item['url'],
                                'snippet': item['snippet'], 'search_formula': formula,
                                'country': cname, 'industry': industry,
                            })
                            if existed:
                                stat['existing'] += 1
                                log(f'   ↩ 已存在，跳过重复客户：{item["title"][:45]}')
                                continue
                            # ③ 用补全结果更新刚才的线索记录。
                            s = score_item(item['title'], item['url'], info)
                            if auto_enrich:
                                # 用补全结果覆盖刚才的线索记录（空值不会冲掉库里已有的有效值）
                                db_upsert_customer({
                                    'company_name': item['title'], 'website': item['url'],
                                    'email': ' / '.join(info['emails']),
                                    'phone': ' / '.join(info['phones']),
                                    'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                                    'snippet': item['snippet'], 'search_formula': formula,
                                    'country': cname, 'industry': industry,
                                })
                            all_rows.append({**item, **info, 'score': s, 'rating': rating(s),
                                             'industry': industry})
                            stat['added'] += 1
                            if info['emails']:
                                stat['mail'] += 1
                            STATE['result_count'] = len(all_rows)
                            # 实时明细：前端表格每秒轮询 STATE['rows']，边搜边显示入库内容
                            with STATE_LOCK:
                                STATE['rows'].append({
                                    'n': len(all_rows),
                                    'title': item['title'],
                                    'url': item['url'],
                                    'emails': info['emails'],
                                    'phones': info['phones'],
                                    'contact_url': info['contact_url'],
                                    'score': s,
                                    'rating': rating(s),
                                    'industry': industry,
                                    'country': cname,
                                })
                            log(f'   + [{len(all_rows)}/{target_count}] {item["title"][:38]} '
                                f'邮箱{len(info["emails"])} 电话{len(info["phones"])} 评分{s} {rating(s)}')
                            if len(all_rows) >= target_count:
                                reached_target = True
                                log(f'🎯 已达到本次目标 {target_count} 个新增网站，停止继续搜索')
                                break
                        if reached_target:
                            break
                        if not sleep_check(random.uniform(2, 4)):
                            log('已停止')
                            return
                    # 一个查询跑完（含翻页），打印它的账目
                    for k in stat:
                        total_stat[k] += stat[k]
                    if stat['cand'] == 0:
                        total_stat['empty'] += 1
                    for reason, count in stat['china'].items():
                        total_stat['china'][reason] += count
                    reason_text = '；'.join(f'{k} {v}' for k, v in stat['china'].items()) or '无'
                    log(f'📊 [{q_index}/{total}] {cname}·{cname2} → 页面候选 {stat["cand"]} 条 | '
                        f'黑名单过滤 {stat["blocked"]} | 本页重复 {stat["dup"]} | '
                        f'客户库已有 {stat["existing"]} | 新增 {stat["added"]}（其中 {stat["mail"]} 个抓到邮箱） | '
                        f'中国商家过滤：{reason_text}')
                    if reached_target:
                        break
                    if not sleep_check(random.uniform(4, 8)):
                        log('已停止')
                        return
                if reached_target:
                    break
            if reached_target:
                break

        log(f'✅ 搜索完成！本轮新增 {len(all_rows)} 个网站'
            + ('，联系方式已就地抓取并写入客户库' if auto_enrich else '（本次未抓取联系方式）'))
        china_total = '；'.join(f'{k} {v}' for k, v in total_stat['china'].items()) or '无'
        log(f'📈 本轮总账：页面候选 {total_stat["cand"]} 条 | 黑名单过滤 {total_stat["blocked"]} | '
            f'本页重复 {total_stat["dup"]} | 客户库已有 {total_stat["existing"]} | '
            f'新增 {total_stat["added"]}（带邮箱 {total_stat["mail"]}） | 中国商家过滤：{china_total}')
        if not reached_target:
            if total_stat['cand'] == 0:
                log('⚠️ 一条候选都没抓到：多半是搜索结果页没渲染出来（或被谷歌拦截），建议先手动在浏览器里搜一次确认')
            else:
                log(f'⚠️ 未能凑够目标 {target_count} 条新增：候选里大多是库里已有的客户。'
                    f'说明该关键词已被搜尽，建议换关键词、加页数或换国家')
        if not auto_enrich:
            log('（本次未勾选同步抓取联系方式：只收集了网站线索，邮箱电话留空，'
                '可稍后双击「补历史欠账.py」批量补）')
        log('正在写出结果 Excel…')
    except Exception as e:
        search_ok = False
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 落盘放在 finally：中途「停止」在 try 内部是 return，只有这里能保证已抓到的结果不白跑。
        # 浏览器关掉后再写文件，确保客户网站标签页已释放、不会和 Excel 抢资源。
        if all_rows:
            try:
                _save_enrich_excel(all_rows, industry=industry)
            except Exception as e:
                log(f'❌ 结果 Excel 写出失败：{type(e).__name__}: {e}')
        elif search_ok:
            log('本轮没有新增网站，未产出结果文件（客户库未变化）')
        STATE['done'] = True
        STATE['running'] = False


def maps_role_word(cond_keys, lang='en'):
    """地图模式下把「身份词」拼进查询词。

    ⚠️ 这一步不是可选优化，是必需：真机实测搜「nouilles」+ 里昂返回的全是
    「Restaurant chinois」餐馆；加上 grossiste 后才出现「Grossiste alimentaire」
    （食品批发商）和进口杂货商 —— 那才是买家。
    取第一个勾选条件的第一个角色词（如 fr → grossiste）。
    """
    for k in (cond_keys or []):
        roles = COND_ROLES.get(k) or {}
        word = roles.get(lang) or roles.get('en') or ''
        if word:
            return word.split(' OR ')[0].strip().strip('"')
    return ''


def run_maps(products, cond_keys, countries, city='', target_count=10, industry='', auto_enrich=True,
             lang='', china_filters=None):
    """谷歌地图名录采集 + 就地补全：与 run_search 并列的第二条链路，互不干扰。

    地图的独特价值：名录里只有「有实体地址的真实商家」，所以 B2B 名录站、新闻站、
    菜谱站这类非买家根本不会出现；而且电话/地址是结构化字段，不用再从官网里猜。
    代价：单次搜索上限约 120 条，且电话/官网必须逐条点开详情面板才有。
    auto_enrich=False 时只取地图给的字段（电话/地址），不访问官网补邮箱。
    """
    page = None
    maps_tab_id = None
    all_rows = []
    run_ok = True
    china_filters = set(CHINA_FILTER_DEFAULTS if china_filters is None else china_filters)
    try:
        init_customer_db()
        STATE['phase'] = 'search'
        log(f'谷歌地图采集：关键词 {len(products)} 个 × 国家 {len(countries)} 个'
            + (f' · 城市「{city}」' if city else '（未指定城市，只用国家中心视野）'))
        log('⚠️ 地图结果会受出口 IP 所在地影响，比网页搜索更明显；指定城市可显著提高精度')
        page = create_browser_page()
        try:
            maps_tab_id = page.tab_id
        except Exception:
            maps_tab_id = None

        seen = set()
        seen_names = set()
        reached_target = False
        # 整轮汇总统计：让「到底有没有写进客户库」一眼可见
        total_stat = {'cards': 0, 'detail': 0, 'end': 0, 'dup': 0, 'existing': 0,
                      'added': 0, 'mail': 0, 'no_web': 0, 'china': Counter()}

        for code, cname, gl, hl in countries:
            if reached_target or STATE['stop']:
                break
            lang = (lang or '').strip() or hl or 'en'
            role = maps_role_word(cond_keys, lang)
            if role:
                log(f'   （地图查询拼上身份词「{role}」—— 不带身份词只会返回餐馆/零售店）')
            for kw in products:
                if reached_target or STATE['stop']:
                    break
                want = target_count - len(all_rows)
                query = f'{kw} {role}'.strip()
                url = maps_search_url(query, code, gl, hl, city)
                log(f'========== {cname} · 地图搜「{query}」'
                    + (f' + {city}' if city else '') + f'（hl={hl} gl={gl}） ==========')
                log(f'   {url}')
                stat = {'cards': 0, 'detail': 0, 'end': 0, 'dup': 0,
                        'existing': 0, 'added': 0, 'mail': 0, 'no_web': 0, 'china': Counter()}
                if not maps_open(page, url):
                    log('⚠️ 地图页没打开或没结果列表，跳过这个关键词')
                    continue
                try:
                    maps_tab_id = page.tab_id or maps_tab_id
                except Exception:
                    pass
                # 链接一次收够：按目标数 3 倍收（去重/过滤会消耗掉一部分），
                # 上限 120 是谷歌地图单次搜索的硬上限，滚到底就停。
                collect = min(max(want * 3, want + 5), 120)
                hrefs = maps_collect_hrefs(page, collect)
                stat['cards'] = len(hrefs)
                if len(hrefs) < collect:
                    stat['end'] = 1                    # 没滚满 = 已经到列表末尾
                log(f'   列表滚出 {len(hrefs)} 条商家链接'
                    + ('（已到列表末尾）' if stat['end'] else f'（目标还需 {want} 条）'))
                if not hrefs:
                    log('   这个关键词在当前城市没滚出任何商家，换城市或换个词')
                for href in hrefs:
                    if reached_target or STATE['stop']:
                        break
                    key = maps_place_key(href) or url_key(href)
                    if not key or key in seen:
                        stat['dup'] += 1
                        continue
                    seen.add(key)
                    # ① 导航到商家页读详情面板（列表层拿不到电话/官网/地址）
                    det = maps_detail(page, href)
                    if not det:
                        log('     · 商家页没读通，跳过这条')
                        continue
                    stat['detail'] += 1
                    name = det['name'] or '(地图未给名称)'
                    if name and name in seen_names:
                        stat['dup'] += 1
                        continue
                    seen_names.add(name)
                    place_url = det['place_url'] if '/maps/place/' in det['place_url'] else href
                    website = det['website']
                    # 没有官网时用 place 链接占位，靠 normalize_domain 的 maps 分支保持唯一
                    target_url = website or place_url
                    phones = [det['phone']] if det['phone'] else []
                    snippet = ' · '.join(x for x in (det['category'], det['address']) if x) or name
                    formula = f'[谷歌地图] {query}' + (f' @{city}' if city else '')
                    if not website:
                        stat['no_web'] += 1
                    # ② 中国商家过滤（地图没有查询公式，只能走结果/联系方式阶段判据）
                    pre_reasons = china_filter_reasons(
                        name, target_url, snippet, phones=phones, enabled_keys=china_filters)
                    if pre_reasons:
                        stat['china'].update(pre_reasons)
                        log(f'   过滤：{name[:40]}（{"；".join(pre_reasons)}）')
                        continue
                    # ③ 已经在库里的老客户，跳过最贵的那两步（点详情已经花掉，这里省访问官网）
                    if db_has_customer(target_url):
                        stat['existing'] += 1
                        log(f'   ↩ 已存在，跳过重复客户：{name[:45]}')
                        continue
                    # ④ 就地补全：地图已经给了电话，官网只补邮箱
                    info = {'emails': [], 'phones': [], 'contact_url': '', 'china_signal_text': ''}
                    if auto_enrich and website and not STATE['stop']:
                        info = enrich(page, website)
                        _back_to_search(page, maps_tab_id)
                    for p in info['phones']:
                        if p not in phones:
                            phones.append(p)
                    info['phones'] = phones[:3]
                    post_reasons = china_filter_reasons(
                        name, target_url, snippet, emails=info['emails'], phones=info['phones'],
                        html_text=info.get('china_signal_text', ''), enabled_keys=china_filters)
                    if post_reasons:
                        stat['china'].update(post_reasons)
                        log(f'   过滤：{name[:40]}（{"；".join(post_reasons)}）')
                        continue
                    # ⑤ 一次性入库（地图字段 + 官网补到的邮箱），地图来源单独标记
                    s = score_item(name, target_url, info)
                    db_upsert_customer({
                        'company_name': name, 'website': target_url,
                        'email': ' / '.join(info['emails']),
                        'phone': ' / '.join(info['phones']),
                        'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                        'snippet': snippet, 'search_formula': formula,
                        'country': cname, 'industry': industry, 'source': '谷歌地图',
                    })
                    all_rows.append({
                        'title': name, 'url': target_url, 'emails': info['emails'],
                        'phones': info['phones'], 'contact_url': info['contact_url'],
                        'score': s, 'rating': rating(s), 'snippet': snippet,
                        'formula': formula, 'country': cname, 'industry': industry,
                    })
                    stat['added'] += 1
                    if info['emails']:
                        stat['mail'] += 1
                    STATE['result_count'] = len(all_rows)
                    # 实时明细：前端表格每秒轮询 STATE['rows']，边采边显示入库内容
                    with STATE_LOCK:
                        STATE['rows'].append({
                            'n': len(all_rows), 'title': name, 'url': target_url,
                            'emails': info['emails'], 'phones': info['phones'],
                            'contact_url': info['contact_url'], 'score': s,
                            'rating': rating(s), 'industry': industry, 'country': cname,
                        })
                    log(f'   + [{len(all_rows)}/{target_count}] {name[:38]} '
                        f'邮箱{len(info["emails"])} 电话{len(info["phones"])} 评分{s} {rating(s)}')
                    if len(all_rows) >= target_count:
                        reached_target = True
                        log(f'🎯 已达到本次目标 {target_count} 个新增商家，停止继续采集')
                        break
                    if not sleep_check(random.uniform(1.5, 3)):
                        log('已停止')
                        return

                # 一个关键词跑完，打印它的账目
                for k in stat:
                    if k == 'china':
                        for reason, count in stat['china'].items():
                            total_stat['china'][reason] += count
                    else:
                        total_stat[k] += stat[k]
                reason_text = '；'.join(f'{k} {v}' for k, v in stat['china'].items()) or '无'
                log(f'📊 {cname}·地图 {query} → 列表卡片 {stat["cards"]} 条 | '
                    f'详情读通 {stat["detail"]} 条 | 重复 {stat["dup"]} | '
                    f'客户库已有 {stat["existing"]} | 新增 {stat["added"]}'
                    f'（其中 {stat["mail"]} 个抓到邮箱） | 中国商家过滤：{reason_text}')
                if reached_target:
                    break
                if not sleep_check(random.uniform(3, 6)):
                    log('已停止')
                    return
            if reached_target:
                break

        log(f'✅ 地图采集完成！本轮新增 {len(all_rows)} 个商家'
            + ('，联系方式已就地抓取并写入客户库' if auto_enrich else '（本次未抓取联系方式）'))
        china_total = '；'.join(f'{k} {v}' for k, v in total_stat['china'].items()) or '无'
        log(f'📈 本轮总账：列表卡片 {total_stat["cards"]} 条 | 详情读通 {total_stat["detail"]} 条 | '
            f'已滚到底 {total_stat["end"]} 次 | 重复 {total_stat["dup"]} | '
            f'客户库已有 {total_stat["existing"]} | 新增 {total_stat["added"]}'
            f'（带邮箱 {total_stat["mail"]}） | 中国商家过滤：{china_total}')
        if total_stat['no_web']:
            log(f'   （其中 {total_stat["no_web"]} 条商家没登记官网，只拿到电话/地址，'
                f'所以没有邮箱；可后续用电话直接联系）')
        if not reached_target:
            log(f'⚠️ 未凑够目标 {target_count} 条：地图单次搜索的上限约 120 条，'
                f'多数关键词滚到底也就几十条。建议换城市、换关键词，或把目标数调小')
        log('正在写出结果 Excel…')
    except Exception as e:
        run_ok = False
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 落盘放 finally：中途「停止」在 try 内部是 return，只有这里能保证已采到的结果不白跑。
        if all_rows:
            try:
                _save_enrich_excel(all_rows, industry=industry)
            except Exception as e:
                log(f'❌ 结果 Excel 写出失败：{type(e).__name__}: {e}')
        elif run_ok:
            log('本轮没有新增商家，未产出结果文件（客户库未变化）')
        STATE['done'] = True
        STATE['running'] = False


def _enrich_worklist():
    """待补全清单：客户库里「邮箱和电话都为空」的记录。
    搜索现在会就地抓联系方式，所以这里捞出来的基本是历史欠账
    （老版本搜到、但没抓到邮箱电话的记录，或抓空后未再补的站）。
    已有邮箱或电话的不会被选出（跳过重复访问）；平台类黑名单域名也跳过。"""
    init_customer_db()
    with closing(db_connect()) as conn:
        rows = conn.execute('''
            SELECT company_name, website, country, industry, snippet, search_formula
            FROM customers
            WHERE website IS NOT NULL AND website <> ''
              AND COALESCE(email, '') = '' AND COALESCE(phone, '') = ''
            ORDER BY datetime(last_seen_at) DESC
        ''').fetchall()
    items, seen, blocked = [], set(), 0
    for r in rows:
        url = (r['website'] or '').strip()
        if not url.startswith('http'):
            url = 'https://' + url
        key = normalize_domain(url)
        if not key or key in seen:
            continue
        seen.add(key)
        if is_blocked(url):
            blocked += 1
            continue
        items.append({
            'title': r['company_name'] or url, 'url': url,
            'snippet': r['snippet'] or '', 'formula': r['search_formula'] or '',
            'country': r['country'] or '', 'industry': r['industry'] or '',
        })
    if blocked:
        log(f'（已跳过 {blocked} 个平台类/黑名单域名）')
    return items


def _pick_industry(explicit, results):
    """行业：优先用本轮搜索时选的；补全单独跑（没有搜索上下文）时取结果里出现最多的。"""
    if (explicit or '').strip():
        return explicit.strip()
    counter = Counter((r.get('industry') or '').strip()
                      for r in results if (r.get('industry') or '').strip())
    return counter.most_common(1)[0][0] if counter else ''


def _pick_country(results):
    """主国家：结果里条数最多的那个（多国同跑时以它命名，历史欠账混入也能收拢）。"""
    counter = Counter((r.get('country') or '').strip()
                      for r in results if (r.get('country') or '').strip())
    return counter.most_common(1)[0][0] if counter else ''


def _save_enrich_excel(results, industry=''):
    """写出本轮结果。固定 10 列——飞书导出与启动迁移都按下标读取，列名与顺序不可改。
    文件名：行业-日期_时间-主国家.xlsx（如 宠物用品-20260928_0145-加拿大.xlsx），
    统一写到 output/ 子目录，每轮一份便于留档。"""
    global ENRICH_FILE
    out = Workbook()
    ows = out.active
    ows.title = '客户名单'
    ows.append(['公司/页面标题', '网站网址', '邮箱', '电话', '联系页',
                '评分', '评级', '摘要', '搜索公式', '国家'])
    for r in sorted(results, key=lambda x: -x['score']):
        ows.append([r['title'], r['url'], ' / '.join(r['emails']), ' / '.join(r['phones']),
                    r['contact_url'], r['score'], r['rating'], r['snippet'], r['formula'],
                    r.get('country', '')])
    for col, w in zip('ABCDEFGHIJ', (50, 50, 40, 20, 40, 8, 10, 60, 50, 10)):
        ows.column_dimensions[col].width = w
    path = ts_result_path(_pick_industry(industry, results), _pick_country(results))
    try:
        out.save(path)
        ENRICH_FILE = path                      # 后续飞书导出读这份最新结果
        STATE['output'] = f'{OUTPUT_DIRNAME}/{os.path.basename(path)}'
        log(f'💾 结果已保存：{STATE["output"]}')
        return True
    except Exception as e:
        log(f'⚠️ 结果 Excel 保存失败（可能被 Excel 占用）：{type(e).__name__}: {e}')
        return False


def enrich_core(industry=''):
    """批量补全主体：逐个访问客户官网抓邮箱/电话并评分，回写客户库。
    专用于收拾客户库里的历史欠账（搜索过程本身已经就地抓取），入口是命令行脚本「补历史欠账.py」。
    industry 用于结果文件命名；留空时自动从结果推断。
    不负责 STATE['running'] / ['done']，由调用方统一管理。返回本次实际处理条数。"""
    page = None
    results = []
    saved = False
    items = _enrich_worklist()
    if not items:
        log('无需补全：客户库里没有「邮箱和电话都为空」的记录')
        return 0
    eta = max(1, len(items) * 20 // 60)
    log(f'待补全 {len(items)} 个网站（历史欠账），预计约 {eta} 分钟；可随时点「停止」。'
        f'注意：本次仍抓不到邮箱和电话的站点，下次还会再被访问一次')
    try:
        page = create_browser_page()
        for i, item in enumerate(items, 1):
            if STATE['stop']:
                log('已停止补全')
                break
            info = enrich(page, item['url'])
            s = score_item(item['title'], item['url'], info)
            enriched = {**item, **info, 'score': s, 'rating': rating(s)}
            db_upsert_customer({
                'company_name': item['title'], 'website': item['url'],
                'email': ' / '.join(info['emails']), 'phone': ' / '.join(info['phones']),
                'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                'snippet': item['snippet'], 'search_formula': item['formula'],
                'country': item.get('country', ''),
            })
            results.append(enriched)
            STATE['result_count'] = len(results)
            log(f'[{i}/{len(items)}] {item["url"][:55]} 邮箱{len(info["emails"])}个 评分{s}')
            time.sleep(1)
    except Exception as e:
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 中途停止也把已抓到的结果落盘，避免白跑一场
        if results:
            saved = _save_enrich_excel(results, industry=industry)
    if results:
        key_count = sum(1 for r in results if r['score'] >= 70)
        mail_count = sum(1 for r in results if r['emails'])
        tail = (f'已保存 {os.path.basename(ENRICH_FILE)}' if saved
                else '结果 Excel 未写出（客户库已更新，不影响飞书导出以外的用途）')
        log(f'✅ 补全完成！共 {len(results)} 个：{mail_count} 个有邮箱，'
            f'{key_count} 个重点客户(≥70分)。{tail}')
    return len(results)


# ================= 导出到飞书 =================
def build_feishu_records():
    """读取最近一份结果 Excel，生成待导入飞书的记录（评分≥50分）"""
    path = ENRICH_FILE or find_latest_result()
    if not path or not os.path.exists(path):
        log('⚠️ 没找到结果 Excel（形如 行业-日期_时间-国家.xlsx），请先运行「开始搜索」')
        return []
    log(f'读取结果文件：{os.path.basename(path)}')
    wb = load_workbook(path)
    ws = wb.active
    records = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not (r and r[1]):
            continue
        # 列：0标题 1网址 2邮箱 3电话 4联系页 5评分 6评级 7摘要 8公式 9国家
        title, url = r[0], r[1]
        emails = r[2] or ''
        phones = r[3] or ''
        score = r[5]
        rating = r[6] or ''
        formula = r[8] if len(r) > 8 else ''
        country = r[9] if len(r) > 9 and r[9] else ''
        if not isinstance(score, (int, float)) or score < 50:
            continue
        mails = [m.strip() for m in emails.split(' / ') if EMAIL_OK.match(m.strip())]
        note = '脚本评分%d分（%s），待人工核实' % (int(score), rating)
        if len(mails) > 1:
            note += '；其他邮箱：' + ' / '.join(mails[1:])
        rec = {
            '公司名称': title,
            '官网': url,
            '电话': phones,
            '来源渠道': ['谷歌搜索'],
            '使用的搜索公式': formula,
            '跟进状态': ['未联系'],
            '备注': note,
        }
        if country:
            rec['国家/地区'] = [COUNTRY_STANDARD.get(country, country)]
        if mails:
            rec['邮箱'] = mails[0]
        records.append(rec)
    wb.close()
    return records


def run_export_feishu():
    """后台任务：把评分结果导出到飞书多维表格"""
    try:
        STATE['phase'] = 'export'
        log('准备导出到飞书...')
        records = build_feishu_records()
        if not records:
            log('没有可导出的记录（需要评分≥50分的客户，请先运行「开始搜索」完成抓取与评分）')
            return
        log(f'共 {len(records)} 条记录待导出')
        base_dir = os.path.dirname(os.path.abspath(__file__))
        tmp_path = os.path.join(base_dir, IMPORT_JSON)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({'create_records': records}, f, ensure_ascii=False)
        env = os.environ.copy()
        env.pop('HERMES_HOME', None)   # 清除该变量，否则 lark-cli 返回异常
        cmd = [LARK_CLI, 'base', '+record-batch-create',
               '--base-token', BASE_TOKEN, '--table-id', TABLE_ID,
               '--json', '@' + IMPORT_JSON, '--as', 'user']
        log('正在写入飞书...')
        r = subprocess.run(cmd, env=env, capture_output=True, cwd=base_dir)
        out = ''
        for raw in (r.stdout, r.stderr):
            if not raw:
                continue
            for enc in ('utf-8', 'gbk'):
                try:
                    out += raw.decode(enc)
                    break
                except Exception:
                    continue
        ok = False
        try:
            ok = bool(json.loads(r.stdout.decode('utf-8')).get('ok'))
        except Exception:
            pass
        if ok:
            log(f'✅ 导出成功！已写入飞书 {len(records)} 条客户记录。')
        else:
            log(f'❌ 导出失败：{out.strip()[:500]}')
    except Exception as e:
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        STATE['done'] = True
        STATE['running'] = False


# ================= Flask 应用 =================
app = Flask(__name__)


@app.route('/')
def index():
    return PAGE_HTML


@app.route('/api/start', methods=['POST'])
def api_start():
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '任务正在运行'})
    data = request.get_json()
    products = [p.strip() for p in data.get('products', '').splitlines() if p.strip()]
    if not products:
        return jsonify({'ok': False, 'msg': '请填写至少一个产品关键词'})
    cond_keys = data.get('conditions', [])
    countries = [c for c in COUNTRIES if c[0] in data.get('countries', [])]
    if not countries:
        countries = [COUNTRIES[0]]
    pages = int(data.get('pages', 2) or 2)
    try:
        target_count = int(data.get('target_count', 10))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': '目标客户数量必须是 10-100 的整数'})
    if not 10 <= target_count <= 100:
        return jsonify({'ok': False, 'msg': '目标客户数量只能设置为 10-100'})
    with STATE_LOCK:
        STATE.update(running=True, done=False, logs=[], result_count=0, rows=[],
                     output='', stop=False, phase='search')
    exclude = data.get('exclude', EXCLUDE_DEFAULT)
    china_filters = [k for k in data.get('china_filters', CHINA_FILTER_DEFAULTS)
                     if k in CHINA_FILTER_DEFAULTS]
    match = data.get('match', 'or')
    industry = (data.get('industry') or '').strip()
    auto_enrich = bool(data.get('auto_enrich', True))   # 搜索时是否就地抓取联系方式（不勾=只收集网站线索）
    lang = (data.get('lang') or '').strip()             # 条件词的搜索语言，留空由 run_search 按国家 hl 推断
    # 数据源：google=谷歌网页搜索（默认，老链路），maps=谷歌地图名录（新链路）
    source = (data.get('source') or 'google').strip()
    city = (data.get('city') or '').strip()             # 仅地图用：城市/地区名，会拼进查询词
    if source == 'maps':
        t = threading.Thread(target=run_maps,
                             args=(products, cond_keys, countries, city, target_count, industry,
                                   auto_enrich, lang, china_filters),
                             daemon=True)
        t.start()
        return jsonify({'ok': True})
    t = threading.Thread(target=run_search,
                         args=(products, cond_keys, countries, pages, exclude, match, target_count, industry,
                               auto_enrich, lang, china_filters),
                         daemon=True)
    t.start()
    return jsonify({'ok': True})


@app.route('/api/export_feishu', methods=['POST'])
def api_export_feishu():
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '任务正在运行'})
    with STATE_LOCK:
        STATE.update(running=True, done=False, logs=[], result_count=0,
                     output='', stop=False, phase='export')
    threading.Thread(target=run_export_feishu, daemon=True).start()
    return jsonify({'ok': True})


@app.route('/api/open_folder', methods=['POST'])
def api_open_folder():
    try:
        os.startfile(output_dir())   # Windows 下打开文件资源管理器（结果 Excel 所在目录）
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/api/keywords')
def api_keywords():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base_dir, KEYWORD_LIB), 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({})


@app.route('/api/db_stats')
def api_db_stats():
    try:
        return jsonify({'ok': True, **db_stats()})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    STATE['stop'] = True
    return jsonify({'ok': True})


@app.route('/api/status')
def api_status():
    since = int(request.args.get('since', 0))
    with STATE_LOCK:
        logs = STATE['logs']
        new_logs = logs[since:] if since < len(logs) else []
        payload = {
            'running': STATE['running'],
            'phase': STATE['phase'],
            'done': STATE['done'],
            'result_count': STATE['result_count'],
            'output': STATE['output'],
            'rows': list(STATE['rows']),      # 本轮已入库明细，前端每秒刷新用它渲染实时表格
            'logs': new_logs,
            'total_logs': len(logs),
        }
    # 库总数单独查（不持锁、不做迁移导入，避免每秒轮询触发重活）；查不到不影响主流程
    try:
        with closing(db_connect()) as conn:
            payload['db_total'] = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
            payload['db_verified'] = conn.execute(
                'SELECT COUNT(*) FROM customers WHERE score IS NOT NULL').fetchone()[0]
    except Exception:
        payload['db_total'] = None
        payload['db_verified'] = None
    return jsonify(payload)


PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>谷歌客户开发工具</title>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background:#f5f6f8; margin:0; padding:24px; color:#222; }
.wrap { max-width: 1100px; margin: 0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:#888; font-size:13px; margin-bottom:20px; }
.grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
.card { background:#fff; border-radius:10px; padding:18px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
.card h3 { margin:0 0 12px; font-size:15px; }
label.cond { display:flex; align-items:center; gap:8px; padding:6px 0; font-size:14px; cursor:pointer; }
label.cond input { width:16px; height:16px; }
textarea, input[type=text] { width:100%; border:1px solid #ddd; border-radius:6px; padding:10px; font-size:14px; font-family:inherit; }
select { width:100%; border:1px solid #ddd; border-radius:6px; padding:10px; font-size:14px; font-family:inherit; background:#fff; cursor:pointer; }
.btn-row { margin-top:18px; display:flex; gap:12px; align-items:center; }
button { border:none; border-radius:8px; padding:12px 24px; font-size:15px; cursor:pointer; font-weight:600; }
.btn-start { background:#1a73e8; color:#fff; }
.btn-stop { background:#d93025; color:#fff; }
.btn-export { background:#7c3aed; color:#fff; }
.btn-open { background:#e8f0fe; color:#1a73e8; border:1px solid #1a73e8; padding:4px 10px; font-size:13px; font-weight:500; border-radius:6px; }
.kw-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.kw-item { display:flex; align-items:center; gap:8px; padding:8px 10px; background:#f7f9fc; border:1px solid #e8edf2; border-radius:6px; font-size:13px; }
.kw-en { font-family:Consolas,monospace; color:#1a73e8; flex:1; word-break:break-all; }
.kw-cn { color:#666; min-width:140px; }
.kw-copy { background:#1a73e8; color:#fff; border:none; border-radius:4px; padding:3px 10px; font-size:12px; cursor:pointer; font-weight:500; }
.kw-lab { margin:0; }
.kw-lab input { width:14px; height:14px; }
.btn-mini { background:#f1f3f4; color:#333; border:1px solid #ccc; border-radius:6px; padding:8px 14px; font-size:13px; cursor:pointer; font-weight:500; }
button:disabled { background:#ccc; cursor:not-allowed; }
.status { margin-top:12px; font-size:14px; color:#555; }
.log { background:#1e1e1e; color:#d4d4d4; border-radius:10px; padding:16px; font-family:Consolas,monospace; font-size:13px; height:420px; overflow-y:auto; white-space:pre-wrap; line-height:1.7; margin-top:16px; }
.counter { display:inline-block; background:#eef3fe; color:#1a73e8; padding:3px 10px; border-radius:12px; font-size:13px; font-weight:600; }
.note { color:#b58900; font-size:12px; margin-top:8px; }
.cmb-sum { font-size:13px; color:#1a73e8; margin-bottom:4px; }
.cmb-box { max-height:430px; overflow-y:auto; padding-right:4px; }
.cmb-group { margin-bottom:10px; }
.cmb-head { font-size:13px; font-weight:600; color:#188038; margin:8px 0 4px; padding-bottom:3px; border-bottom:1px dashed #d6e4d9; }
.cmb-line { background:#f7f9fc; border:1px solid #e8edf2; border-radius:5px; padding:6px 8px; margin:4px 0;
  font-family:Consolas,monospace; font-size:12.5px; line-height:1.5; color:#1a73e8; word-break:break-all; }
.cmb-excl { color:#aaa; }
.cmb-arg { color:#8c9bab; border-bottom:1px dotted #8c9bab; cursor:help; }
.cmb-empty { color:#b58900; font-size:13px; }
.live-wrap { margin-top:16px; }
.live-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.live-head h3 { margin:0; font-size:15px; }
.live-badge { display:inline-block; background:#eef8ee; color:#188038; padding:3px 10px; border-radius:12px; font-size:13px; font-weight:600; }
.live-scroll { max-height:320px; overflow:auto; border:1px solid #e8edf2; border-radius:8px; }
table.live { width:100%; border-collapse:collapse; font-size:13px; }
table.live th { position:sticky; top:0; background:#f7f9fc; color:#555; font-weight:600; text-align:left;
  padding:8px 10px; border-bottom:1px solid #e3e8ee; white-space:nowrap; }
table.live td { padding:7px 10px; border-bottom:1px solid #f1f4f7; vertical-align:top; }
table.live tr:last-child td { border-bottom:none; }
table.live tr.row-new { animation: rowIn .9s ease-out; }
@keyframes rowIn { from { background:#fff7e6; } to { background:transparent; } }
.live-co { color:#1a73e8; text-decoration:none; font-weight:500; }
.live-co:hover { text-decoration:underline; }
.live-dom { color:#999; font-size:12px; }
.live-mail { color:#188038; font-family:Consolas,monospace; font-size:12px; }
.live-miss { color:#bbb; }
.live-cell { max-width:210px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.live-sc { font-weight:700; }
.live-empty { color:#b58900; font-size:13px; padding:14px; }
.tag-r { display:inline-block; padding:1px 7px; border-radius:9px; font-size:12px; }
.tag-r1 { background:#fdeceb; color:#d93025; }
.tag-r2 { background:#eef3fe; color:#1a73e8; }
.tag-r3 { background:#f1f3f4; color:#777; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🔍 谷歌客户开发工具</h1>
  <div class="sub">本地运行 · 搜到一个网站就立刻抓联系方式 · SQLite 客户库去重 · 导出 Excel / 飞书</div>

  <div class="card" style="margin-bottom:16px;">
    <h3>1. 目标国家（单选，下拉选择）</h3>
    <select id="countries" onchange="onCountry()" style="max-width:420px;"></select>
  </div>

  <div class="card" style="margin-bottom:16px;">
    <h3>📋 产品关键词库（行业 → 细分品类 → 具体产品 → 关键词，分级选择）</h3>
    <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; margin:8px 0 12px;">
      <div><label style="font-size:13px;color:#666;">行业</label><br><select id="kwIndustry" onchange="onIndustry()" style="width:150px;"></select></div>
      <div><label style="font-size:13px;color:#666;">细分品类</label><br><select id="kwCategory" onchange="onCategory()" style="width:170px;"></select></div>
      <div><label style="font-size:13px;color:#666;">具体产品</label><br><select id="kwProduct" onchange="onProduct()" style="width:190px;"></select></div>
      <div><label style="font-size:13px;color:#666;">语言</label><br><select id="kwLang" onchange="onProduct()" style="width:120px;"><option value=""></option><option value="en">英语</option><option value="de">德语</option><option value="fr">法语</option><option value="es">西班牙语</option><option value="ar">阿拉伯语</option><option value="fa">波斯语</option><option value="it">意大利语</option><option value="nl">荷兰语</option><option value="tr">土耳其语</option></select></div>
      <button class="btn-mini" onclick="copyChecked()">复制勾选</button>
    </div>
    <div id="kwList" class="kw-grid"></div>
    <div class="note">关键词数据在同目录「关键词库.json」里，可直接编辑添加，改完刷新本页即可</div>
  </div>

  <div class="grid">
    <div class="card" style="grid-column: span 1;">
      <h3>2. 产品关键词（一行一个）</h3>
      <textarea id="products" rows="4" placeholder="Cat Litter Box Liners&#10;Cat Litter Liners"></textarea>
      <div class="note">每行会自动加英文双引号做精确匹配</div>
      <div style="margin-top:10px; font-size:13px; color:#444; line-height:1.9;">
        多个词怎么组合：
        <label style="margin-right:12px;"><input type="radio" name="match" value="or" checked> OR（任一命中，同义词用）</label>
        <label style="margin-right:12px;"><input type="radio" name="match" value="and"> AND（同时命中，最精准）</label>
        <label><input type="radio" name="match" value="each"> 分别搜（各词各搜一遍）</label>
      </div>
    </div>

    <div class="card" id="condCard">
      <h3>3. 搜索条件（勾选要跑的）</h3>
      <div id="conds"></div>
      <div class="note" id="condMapsHint" style="display:none;">地图模式只用「<b>第一个勾选条件</b>」的身份词拼进查询词（如法国用 grossiste）。<br>⚠️ 这一步不能省：实测只搜「nouilles」返回的全是餐馆，加上 grossiste 才出现食品批发商。其余条件不参与。</div>
    </div>

    <div class="card">
      <h3>4. 参数</h3>
        <div style="margin:0 0 4px; font-size:14px;">数据源：</div>
        <label class="cond" style="display:block;"><input type="radio" name="source" value="google" checked onchange="onSource()"> 谷歌网页搜索（按关键词找公司官网）</label>
        <label class="cond" style="display:block;"><input type="radio" name="source" value="maps" onchange="onSource()"> 谷歌地图名录（找有实体地址的本地商家，带电话）</label>
        <div id="mapsNote" class="note" style="display:none;">地图名录里只有「有实体地址的真实商家」，所以 B2B 名录站/新闻站/菜谱站不会混进来；电话和地址是地图直接给的，官方有官网的再访问官网补邮箱。<br>⚠️ 单次搜索上限约 120 条；结果受出口 IP 所在地影响，指定城市能明显提高精度。仅用于少量内部研究。</div>
        <div id="mapsCityWrap" style="display:none; margin:8px 0;">
          <label style="font-size:14px;">城市 / 地区：</label>
          <input type="text" id="mapsCity" placeholder="如 Lyon / 里昂，留空只用国家" style="width:180px; margin:6px 0;">
          <div class="note">城市名会拼进地图搜索词（谷歌官方推荐的位置限定方式），比只选国家精准得多</div>
        </div>
        <div id="pagesWrap">
          <label style="font-size:14px;">每条公式抓几页：</label>
          <input type="number" id="pages" value="2" min="1" max="5" style="width:80px; margin:6px 0;">
        </div>
        <br><label style="font-size:14px;">本次任务采集数量：</label>
        <input type="number" id="targetCount" value="10" min="10" max="100" step="1" style="width:80px; margin:6px 0;">
        <div class="note">本轮最多新增多少个新客户（10-100）；按新增个数计，不按是否抓到联系方式计。SQLite 客户库总量不设上限</div>
        <div style="margin:12px 0 4px; font-size:14px;">搜索方式：</div>
        <label class="cond"><input type="checkbox" id="autoEnrich" checked> 搜到一个就顺手抓它的联系方式（推荐）</label>
        <div class="note">勾选：每搜到一个新客户，立刻访问它抓邮箱/电话并评分，抓完（或确认抓不到）再搜下一个，凑够数量即停。每条会多花几秒，但不用等全部搜完；结果文件在整轮结束时一次写出。<br>不勾：只收集网站线索，邮箱电话留空，速度快，适合先铺量，稍后再双击「补历史欠账.py」批量补。<br>（地图模式下：地图本来就给电话和地址，不勾就是不再访问官网补邮箱。）</div>
      <div id="excludesWrap">
        <div style="margin:12px 0 4px; font-size:14px;">排除条件（勾选要排除的，默认全排除）</div>
      <div id="excludes"></div>
      </div>
      <div style="margin:12px 0 4px; font-size:14px;">中国商家过滤（默认全部勾选，可逐项关闭）</div>
      <div style="display:flex; gap:8px; margin-bottom:6px;">
        <button type="button" class="btn-mini" onclick="toggleChinaFilters(true)">全部勾选</button>
        <button type="button" class="btn-mini" onclick="toggleChinaFilters(false)">全部取消</button>
      </div>
      <div id="chinaMapsHint" class="note" style="display:none;">地图模式没有查询公式，所以「排除 China manufacturer」这类查询词选项不生效；但「中文地址 / +86 电话 / 平台域名」这些在结果上判断的项照常生效</div>
      <div id="chinaFilters"></div>
      <div class="note">⚠️ 搜索中会弹出 Chrome 窗口，遇到谷歌验证码请在浏览器里手动通过</div>
    </div>

    <div class="card">
      <h3>5. 关键词组合预览（实时）</h3>
      <div class="cmb-sum" id="comboSummary">…</div>
      <div class="cmb-box" id="comboList"></div>
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
        <button class="btn-mini" onclick="copyCombos()">复制全部组合</button>
        <span class="note" id="comboHint" style="margin:0;">浅灰＝排除词；末尾的 <code>&amp;gl=..&amp;hl=..</code> 是国家筛选参数（加在搜索 URL 上，不在搜索词里）</span>
      </div>
    </div>
  </div>

  <div class="btn-row">
    <button class="btn-start" id="btnStart" onclick="start()">▶ 开始搜索</button>
    <button class="btn-export" id="btnExport" onclick="exportFeishu()">导出到飞书</button>
    <button class="btn-stop" id="btnStop" onclick="stop()" disabled>■ 停止</button>
      <span class="counter" id="counter">本轮新增 0 个网站</span>
      <span class="counter" id="dbCounter" style="background:#eef8ee;color:#188038;">客户库加载中...</span>
  </div>
  <div class="status" id="status"></div>

  <div class="card live-wrap">
    <div class="live-head">
      <h3>📥 本轮已入库明细（实时）</h3>
      <span class="live-badge" id="liveCount">0 条</span>
      <span class="note" style="margin:0;">每搜到一个网站就立刻抓取联系方式并写入 SQLite，写入即在这里出现</span>
    </div>
    <div class="live-scroll">
      <table class="live">
        <thead>
          <tr>
            <th style="width:44px;">#</th>
            <th>公司名称 / 官网</th>
            <th style="width:190px;">邮箱</th>
            <th style="width:140px;">电话</th>
            <th style="width:60px;">评分</th>
            <th style="width:84px;">评级</th>
          </tr>
        </thead>
        <tbody id="liveBody"></tbody>
      </table>
      <div class="live-empty" id="liveEmpty">等待任务开始…点击「开始搜索」后，每入库一条客户就会实时出现在这里。</div>
    </div>
  </div>

  <div class="log" id="log"></div>
</div>

<script>
let since = 0, polling = null, renderedRows = 0;
let RUN_SOURCE = 'google';   // 本轮数据源：google / maps（由 start() 写入，poll() 用来切换文案）

function logBox(msg){
  const b = document.getElementById('log');
  b.textContent += msg + '\\n';
  b.scrollTop = b.scrollHeight;
}

function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function domainOf(url){
  try { return new URL(url).hostname.replace(/^www\\./, ''); } catch(e){ return url || ''; }
}

function ratingCls(r){
  return r === '重点客户' ? 'tag-r1' : r === '普通客户' ? 'tag-r2' : 'tag-r3';
}

// 实时渲染本轮已入库明细。只追加新增行（增量），避免每秒整体重绘导致滚动位置和 hover 状态丢失。
function renderRows(rows){
  const tb = document.getElementById('liveBody');
  const empty = document.getElementById('liveEmpty');
  const badge = document.getElementById('liveCount');
  if (!Array.isArray(rows)) return;
  if (rows.length < renderedRows){ tb.innerHTML = ''; renderedRows = 0; }   // 新一轮任务，清空重来
  for (let i = renderedRows; i < rows.length; i++){
    const r = rows[i] || {};
    const dom = domainOf(r.url);
    const mails = (r.emails && r.emails.length) ? r.emails.join(' / ') : '';
    const phones = (r.phones && r.phones.length) ? r.phones.join(' / ') : '';
    const tr = document.createElement('tr');
    tr.className = 'row-new';
    tr.innerHTML =
      '<td>' + (r.n || (i + 1)) + '</td>' +
      '<td><a class="live-co" href="' + esc(r.url) + '" target="_blank" rel="noopener" title="' + esc(r.title) + '">' +
        esc(r.title) + '</a><br><span class="live-dom">' + esc(dom) + '</span></td>' +
      '<td class="live-cell" title="' + esc(mails) + '">' +
        (mails ? '<span class="live-mail">' + esc(mails) + '</span>' : '<span class="live-miss">未抓到</span>') + '</td>' +
      '<td class="live-cell" title="' + esc(phones) + '">' +
        (phones ? esc(phones) : '<span class="live-miss">未抓到</span>') + '</td>' +
      '<td class="live-sc">' + (r.score == null ? '' : r.score) + '</td>' +
      '<td><span class="tag-r ' + ratingCls(r.rating) + '">' + esc(r.rating) + '</span></td>';
    tb.appendChild(tr);
  }
  renderedRows = rows.length;
  badge.textContent = rows.length + ' 条';
  if (empty) empty.style.display = rows.length ? 'none' : 'block';
  const sc = tb.closest('.live-scroll');
  if (sc) sc.scrollTop = sc.scrollHeight;   // 有新行时自动滚到底部
}

async function poll(){
  const r = await fetch('/api/status?since=' + since);
  const d = await r.json();
  if (d.logs && d.logs.length){
    for (const l of d.logs) logBox(l);
    since = d.total_logs;
  }
  document.getElementById('counter').textContent =
    '本轮新增 ' + d.result_count + (RUN_SOURCE === 'maps' ? ' 个商家' : ' 个网站');
  renderRows(d.rows);
  if (d.db_total != null){
    document.getElementById('dbCounter').textContent = 'SQLite 已存 ' + d.db_total + ' 条（已评分 ' +
      (d.db_verified == null ? '-' : d.db_verified) + '）';
  }
  if (!d.running && d.done && polling){
    clearInterval(polling); polling = null;
    setButtons(false);
    const s = document.getElementById('status');
    s.innerHTML = '✅ 完成，结果文件：' + (d.output || '') +
      ' <button class="btn-open" onclick="openFolder()">📂 打开结果文件夹</button>';
  } else if (d.running){
    setButtons(true);
    const s = document.getElementById('status');
    s.textContent = d.phase === 'export' ? '导出到飞书…'
                  : RUN_SOURCE === 'maps'
                    ? '地图采集 + 就地抓联系方式中（每条要点开详情面板，较慢）…'
                    : d.phase === 'search' ? '搜索中（每搜到一个网站就同步抓联系方式）…'
                  : '运行中…';
  }
}

async function loadDbStats(){
  try{
    const d = await (await fetch('/api/db_stats')).json();
    if(d.ok) document.getElementById('dbCounter').textContent = 'SQLite 已存 ' + d.total + ' 条（已评分 ' + d.verified + '）';
  }catch(e){}
}
loadDbStats();

function setButtons(running){
  document.getElementById('btnStart').disabled = running;
  document.getElementById('btnExport').disabled = running;
  document.getElementById('btnStop').disabled = !running;
}

async function start(){
  const products = document.getElementById('products').value;
  const conditions = [...document.querySelectorAll('#conds input:checked')].map(i=>i.value);
    const countries = [document.getElementById('countries').value];
    const pages = document.getElementById('pages').value;
    const targetCount = parseInt(document.getElementById('targetCount').value || '10');
    const exclude = [...document.querySelectorAll('#excludes input:checked')].map(i=>i.value).join(' ');
    const chinaFilters = [...document.querySelectorAll('#chinaFilters .china-filter:checked')]
      .map(i => i.dataset.key);
  const match = (document.querySelector('input[name="match"]:checked') || {}).value || 'or';
    const industry = document.getElementById('kwIndustry').value || '';   // 行业标签，取自关键词库的行业选择
    const autoEnrich = document.getElementById('autoEnrich').checked;      // 搜索时是否就地抓联系方式
    const lang = curLang();                                                // 条件词语言（随后国家自动联动）
    const source = curSource();                                            // google=网页搜索 / maps=谷歌地图
    const city = curCity();                                                // 仅地图用
    if (!products.trim()){ alert('请填写产品关键词'); return; }
    if (source !== 'maps' && !conditions.length){ alert('请至少勾选一个搜索条件'); return; }
    if (!Number.isInteger(targetCount) || targetCount < 10 || targetCount > 100){
      alert('本次任务采集数量只能设置为 10-100 的整数'); return;
    }
    const r = await fetch('/api/start', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({products, conditions, countries, pages, target_count: targetCount, exclude,
        china_filters: chinaFilters, match, industry, auto_enrich: autoEnrich, lang, source, city}) });
  const d = await r.json();
  if (!d.ok){ alert(d.msg); return; }
  RUN_SOURCE = source;
  logBox(source === 'maps' ? '====== 开始谷歌地图采集 ======' : '====== 开始搜索 ======');
  since = 0;
  renderedRows = 0;                                     // 清空上一轮的实时明细，等后端 rows 到达后重建
  document.getElementById('liveBody').innerHTML = '';
  document.getElementById('liveCount').textContent = '0 条';
  document.getElementById('liveEmpty').style.display = 'block';
  document.getElementById('status').textContent = '运行中...';
  setButtons(true);
  polling = setInterval(poll, 1000);
}

async function exportFeishu(){
  const r = await fetch('/api/export_feishu', { method:'POST' });
  const d = await r.json();
  if (!d.ok){ alert(d.msg); return; }
  logBox('====== 开始导出到飞书 ======');
  since = 0;
  document.getElementById('status').textContent = '导出中...';
  setButtons(true);
  polling = setInterval(poll, 1000);
}

async function stop(){
  await fetch('/api/stop', { method:'POST' });
  logBox('已请求停止...');
}

async function openFolder(){
  await fetch('/api/open_folder', { method:'POST' });
}

// 渲染条件和国家
const CONDS = CONDS_PLACEHOLDER;
const condBox = document.getElementById('conds');
CONDS.forEach(c => {
  condBox.insertAdjacentHTML('beforeend',
    `<label class="cond"><input type="checkbox" value="${c[0]}" ${c[2]?'checked':''}> ${c[1]}</label>`);
});
const COUNTS = COUNTS_PLACEHOLDER;
const countryBox = document.getElementById('countries');
const COUNTRY_LANG = {};
const COUNTRY_GL = {};
COUNTS.forEach(c => {
  COUNTRY_LANG[c[0]] = c[3] || '';
  COUNTRY_GL[c[0]] = c[4] || c[0];
  countryBox.insertAdjacentHTML('beforeend',
    `<option value="${c[0]}" ${c[2]?'selected':''}>${c[1]}</option>`);
});
const MAPS_CENTERS = MAPS_CENTERS_PLACEHOLDER;   // 国家代码 → [纬度, 经度]，与后端 COUNTRY_CENTERS 同源
const MAPS_ROLES = MAPS_ROLES_PLACEHOLDER;       // 条件 → {语言: 身份词}，与后端 COND_ROLES 同源

// ==================== 数据源切换（谷歌网页搜索 / 谷歌地图） ====================
function curSource(){
  return (document.querySelector('input[name="source"]:checked') || {}).value || 'google';
}
function curCity(){
  const el = document.getElementById('mapsCity');
  return el ? (el.value || '').trim() : '';
}
// 地图查询要拼的身份词：取第一个勾选条件的角色词（与后端 maps_role_word 一致）
// ⚠️ 不带身份词时地图只会返回餐馆/零售店，不是买家
function mapsRoleWord(){
  const first = document.querySelector('#conds input:checked');
  if (!first) return '';
  const r = MAPS_ROLES[first.value] || {};
  return r[curLang()] || r.en || '';
}
function onSource(){
  const maps = curSource() === 'maps';
  document.getElementById('mapsCityWrap').style.display  = maps ? 'block' : 'none';
  document.getElementById('mapsNote').style.display      = maps ? 'block' : 'none';
  document.getElementById('pagesWrap').style.display     = maps ? 'none'  : 'block';
  document.getElementById('excludesWrap').style.display  = maps ? 'none'  : 'block';
  document.getElementById('condMapsHint').style.display  = maps ? 'block' : 'none';
  document.getElementById('chinaMapsHint').style.display = maps ? 'block' : 'none';
  renderCombos();
}
// 地图搜索 URL：与后端 maps_search_url() 保持完全一致
// ① 城市名拼进查询词（谷歌官方推荐的位置限定方式）② @lat,lng 锁视野 ③ hl/gl 挂查询串
function mapsUrlPreview(query, code, city, hl, gl){
  const c  = MAPS_CENTERS[code] || MAPS_CENTERS.us || [39.83, -98.58];
  const q  = [query, city].filter(Boolean).join(' ').trim();
  const qs = [];
  if (hl) qs.push('hl=' + hl);
  if (gl) qs.push('gl=' + gl);
  return 'https://www.google.com/maps/search/' + encodeURIComponent(q)
       + '/@' + c[0] + ',' + c[1] + ',11z' + (qs.length ? '?' + qs.join('&') : '');
}
// 国家 → 语言联动：该国语言在语言下拉里有选项就自动选中；下拉里没有该语言 → 留空（完全空白，由用户自选）
function applyCountryLang(){
  const sel = document.getElementById('kwLang');
  const want = COUNTRY_LANG[countryBox.value] || '';
  const exists = [...sel.options].some(o => o.value === want);
  sel.value = exists ? want : '';
}
function onCountry(){
  applyCountryLang();
  onProduct();
  renderCombos();          // 摘要里会显示目标国家，跟着刷新
}
const EXCLS = EXCLS_PLACEHOLDER;
const exclBox = document.getElementById('excludes');
EXCLS.forEach(e => {
  exclBox.insertAdjacentHTML('beforeend',
    `<label class="cond"><input type="checkbox" value="${e[1]}" checked> <b>${e[1]}</b> <span style="color:#888">${e[2]}</span></label>`);
});
const CHINA_FILTERS = CHINA_FILTERS_PLACEHOLDER;
const chinaBox = document.getElementById('chinaFilters');
CHINA_FILTERS.forEach(e => {
  chinaBox.insertAdjacentHTML('beforeend',
    `<label class="cond"><input type="checkbox" class="china-filter" data-key="${e[0]}" value="${e[1]}" checked> <b>${e[2]}</b> <span style="color:#888">${e[3]}</span></label>`);
});
function toggleChinaFilters(on){
  document.querySelectorAll('#chinaFilters .china-filter').forEach(x => x.checked = on);
  renderCombos();
}
let KW_DATA = {};
async function loadKeywords(){
  try{ KW_DATA = await (await fetch('/api/keywords')).json(); }
  catch(e){ KW_DATA = {}; }
  const ind = document.getElementById('kwIndustry');
  const inds = Object.keys(KW_DATA);
  if(!inds.length){
    ind.innerHTML = '<option value="">（暂无数据，请编辑 关键词库.json）</option>';
    document.getElementById('kwCategory').innerHTML = '';
    document.getElementById('kwProduct').innerHTML = '';
    renderKwList([]);
    return;
  }
  ind.innerHTML = inds.map(n => `<option value="${n}">${n}</option>`).join('');
  onIndustry();
}
// 行业 → 细分品类
function onIndustry(){
  applyCountryLang();
  const box = document.getElementById('kwCategory');
  const cats = KW_DATA[document.getElementById('kwIndustry').value] || {};
  const names = Object.keys(cats);
  box.innerHTML = '<option value="">全部细分品类</option>' + names.map(n => `<option value="${n}">${n}</option>`).join('');
  onCategory();
}
// 细分品类 → 具体产品
function onCategory(){
  const i = document.getElementById('kwIndustry').value;
  const c = document.getElementById('kwCategory').value;
  const box = document.getElementById('kwProduct');
  const subs = (KW_DATA[i] || {})[c] || {};
  const names = Object.keys(subs);
  box.innerHTML = '<option value="">全部具体产品</option>' + names.map(n => `<option value="${n}">${n}</option>`).join('');
  onProduct();
}
// 三级取词：行业 / 细分品类 / 具体产品
function onProduct(){
  const i = document.getElementById('kwIndustry').value;
  const c = document.getElementById('kwCategory').value;
  const p = document.getElementById('kwProduct').value;
  const cats = KW_DATA[i] || {};
  let list = [];
  if (!c){
    list = Object.values(cats).flatMap(subs => Object.values(subs).flat());
  } else if (!p){
    list = Object.values(cats[c] || {}).flat();
  } else {
    list = (cats[c] || {})[p] || [];
  }
  renderKwList(list);
  renderCombos();          // 「语言」直接决定条件词用哪种语言，改了就刷新预览
}
function renderKwList(list){
  const box = document.getElementById('kwList');
  const lang = document.getElementById('kwLang').value;
  box.innerHTML = '';
  list.forEach(k => {
    const term = k[lang] || k.en;
    box.insertAdjacentHTML('beforeend',
      `<div class="kw-item"><label class="kw-lab"><input type="checkbox" class="kw-chk" value="${term}"></label><span class="kw-en">${term}</span><span class="kw-cn">${k.cn}</span><button class="kw-copy" onclick="copyKw(this)">复制</button></div>`);
  });
}
function copyKw(btn){
  const text = btn.parentElement.querySelector('.kw-en').textContent;
  navigator.clipboard.writeText(text).then(()=>{
    btn.textContent = '已复制';
    setTimeout(()=>{ btn.textContent = '复制'; }, 1200);
  });
}
function copyChecked(){
  const picks = [...document.querySelectorAll('#kwList .kw-chk:checked')].map(c => c.value);
  if(!picks.length){ alert('请先勾选要复制的关键词'); return; }
  navigator.clipboard.writeText(picks.join('\\n')).then(()=>{
    alert('已复制 ' + picks.length + ' 个关键词');
  });
}

// ==================== 关键词组合预览 ====================
// COND_TMPL[key] = {语言: 公式模板}；条件词按搜索语言本地化，缺失该语言回落英文
const COND_TMPL = {};
CONDS.forEach(c => COND_TMPL[c[0]] = c[3] || {en: '{p}'});
const LANG_CN = {en:'英语', fr:'法语', de:'德语', es:'西班牙语', it:'意大利语',
                 nl:'荷兰语', tr:'土耳其语', ar:'阿拉伯语', fa:'波斯语'};
let COMBO_CACHE = [];       // 当前预览里的完整公式纯文本，供「复制全部组合」使用

// 当前搜索语言：优先用「语言」下拉（它已随国家自动联动），没选则取该国的界面语言，最后回落英语。
// 必须与后端 run_search 取语言的方式一致。
function curLang(){
  const kw = document.getElementById('kwLang').value;
  if (kw) return kw;
  const gl = COUNTRY_LANG[document.getElementById('countries').value];
  return gl || 'en';
}
// 当前国家筛选参数（写在 URL 上，不在搜索词里）：&gl=fr&hl=fr
function countryParams(){
  const code = document.getElementById('countries').value;
  const gl = COUNTRY_GL[code] || code;
  const hl = COUNTRY_LANG[code] || gl;
  return '&gl=' + gl + '&hl=' + hl;
}

function esc(s){
  return String(s).replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}
// 产品词 → 查询片段。组合规则与后端 run_search 完全一致：
// OR → 所有词用 OR 连接；AND → 空格连接；分别搜 → 每词一条
function productQueries(){
  const raw = document.getElementById('products').value
    .split('\\n').map(s => s.trim()).filter(Boolean);
  if (!raw.length) return [];
  const pwords = raw.map(p => '"' + p.replace(/^"+|"+$/g, '') + '"');
  const match = (document.querySelector('input[name="match"]:checked') || {}).value || 'or';
  if (match === 'and')  return [pwords.join(' ')];
  if (match === 'each') return pwords;
  return [pwords.join(' OR ')];
}
function renderCombos(){
  const box = document.getElementById('comboList');
  const sum = document.getElementById('comboSummary');
  const pqs   = productQueries();
  const conds = [...document.querySelectorAll('#conds input:checked')];
  const excl  = [...document.querySelectorAll('#excludes input:checked, #chinaFilters input:checked')]
    .map(i => i.value).filter(Boolean).join(' ');
  const csel  = document.getElementById('countries');
  const cname = (csel.selectedOptions[0] || {}).textContent || '未选择';
  const lang  = curLang();
  const args  = countryParams();
  box.innerHTML = '';
  COMBO_CACHE = [];
  if (curSource() === 'maps'){
    const co    = document.getElementById('countries');
    const code  = co.value;
    const cname = (co.selectedOptions[0] || {}).textContent || '未选择';
    const city  = curCity();
    const hl    = curLang() || COUNTRY_LANG[code] || 'en';
    const gl    = COUNTRY_GL[code] || code;
    if (!pqs.length){
      sum.textContent = '请先填写「2. 产品关键词」';
      box.innerHTML = '<div class="cmb-empty">暂无可预览的地图查询</div>';
      return;
    }
    const role  = mapsRoleWord();
    const urls  = pqs.map(pq => mapsUrlPreview(
      [pq.replace(/^"+|"+$/g, ''), role].filter(Boolean).join(' '), code, city, hl, gl));
    COMBO_CACHE.push(...urls);
    sum.innerHTML = '<b>' + urls.length + '</b> 条地图查询 · 目标国家：' + esc(cname)
                  + (city ? ' · 城市：' + esc(city) : ' · 未指定城市（只用国家中心视野，精度较低）')
                  + (role ? ' · 身份词：' + esc(role) : ' · ⚠️ 没勾搜索条件，没有身份词，结果会以餐馆/零售店为主');
    box.insertAdjacentHTML('beforeend',
      '<div class="cmb-group"><div class="cmb-head">谷歌地图搜索（点链接可直接打开验证）</div>'
      + urls.map(u => '<div class="cmb-line"><a href="' + esc(u) + '" target="_blank" rel="noopener">'
          + esc(u) + '</a></div>').join('')
      + '</div>');
    return;
  }
  if (!pqs.length || !conds.length){
    sum.textContent = '请先填写「2. 产品关键词」，并至少勾选一个「3. 搜索条件」';
    box.innerHTML = '<div class="cmb-empty">暂无可预览的组合</div>';
    return;
  }
  sum.innerHTML = '<b>' + pqs.length + '</b> 个产品组合 × <b>' + conds.length + '</b> 个条件 = <b>'
                + (pqs.length * conds.length) + '</b> 条查询 · 目标国家：' + esc(cname)
                + ' · 条件词语言：' + esc(LANG_CN[lang] || lang);
  conds.forEach(c => {
    const label = c.parentElement.textContent.trim();
    const tmplMap = COND_TMPL[c.value] || {};
    const tmpl  = tmplMap[lang] || tmplMap.en || '{p}';
    const lines = pqs.map(pq => {
      const core = tmpl.replace('{p}', pq);
      return { core: core, full: (core + (excl ? ' ' + excl : '')).trim() };
    });
    COMBO_CACHE.push(...lines.map(l => l.full));
    box.insertAdjacentHTML('beforeend',
      '<div class="cmb-group"><div class="cmb-head">' + esc(label) + '</div>'
      + lines.map(l => '<div class="cmb-line">' + esc(l.core)
          + (excl ? ' <span class="cmb-excl">' + esc(excl) + '</span>' : '')
          + ' <span class="cmb-arg" title="这两个参数加在搜索 URL 上，决定谷歌按哪个国家/语言给结果，不写进搜索词">'
          + esc(args) + '</span></div>').join('')
      + '</div>');
  });
}
function copyCombos(){
  if (!COMBO_CACHE.length){ alert('暂无可复制的组合'); return; }
  navigator.clipboard.writeText(COMBO_CACHE.join('\\n')).then(()=>{
    alert('已复制 ' + COMBO_CACHE.length + ' 条完整公式');
  });
}
// 任何影响组合的输入都实时刷新预览
document.getElementById('products').addEventListener('input', renderCombos);
document.getElementById('mapsCity').addEventListener('input', renderCombos);
document.querySelectorAll('input[name="match"]').forEach(r => r.addEventListener('change', renderCombos));
document.addEventListener('change', e => {
  if (e.target.closest && e.target.closest('#conds, #excludes, #chinaFilters')) renderCombos();
});
onSource();   // 初始化：按默认数据源摆好界面，并渲染一次预览

loadKeywords();
</script>
</body>
</html>
"""

# 填充页面里的条件和国家（用 Python 注入，避免 JS 里写中文 JSON 出问题）
def _build_page():
    # (key, 名称, 是否默认勾选, {语言: 公式模板}) —— 模板给前端做「关键词组合预览」，
    # 按当前选择的搜索语言取，保证预览与实际查询（run_search 里 cond_template）一致
    tmpl_map = {k: {lg: cond_template(k, lg) for lg in COND_LANGS} for k, _ in CONDITIONS}
    default_on = ('wholesale', 'importer')
    conds_js = [(k, name, k in default_on, tmpl_map.get(k, {'en': '{p}'}))
                for k, name in CONDITIONS]
    # 默认勾选美国；(代码, 名称, 是否默认勾选, 该国语言 hl, gl) —— hl/gl 用于「国家→语言」联动
    # 和预览里显示国家筛选参数（gl=fr&hl=fr）
    counts_js = [(k, name, k == 'us', hl, gl) for k, name, gl, hl in COUNTRIES]
    excls_js = [(k, v, d) for k, v, d in EXCLUDE_OPTIONS]
    china_js = [(k, q, label, desc) for k, q, label, desc in CHINA_FILTER_OPTIONS]
    # 国家代码 → [纬度, 经度]：给前端拼地图搜索 URL 用，与后端 COUNTRY_CENTERS 同源
    centers_js = {k: [lat, lng] for k, (lat, lng) in COUNTRY_CENTERS.items()}
    # 条件 → {语言: 该条件角色词的第一个词}：地图模式要把它拼进查询词，前端预览必须与后端一致
    roles_js = {k: {lg: (v.get(lg) or v.get('en') or '').split(' OR ')[0].strip().strip('"')
                    for lg in COND_LANGS}
                for k, v in COND_ROLES.items()}
    import json as _json
    html = PAGE_HTML.replace('CONDS_PLACEHOLDER', _json.dumps(conds_js, ensure_ascii=False))
    html = html.replace('COUNTS_PLACEHOLDER', _json.dumps(counts_js, ensure_ascii=False))
    html = html.replace('EXCLS_PLACEHOLDER', _json.dumps(excls_js, ensure_ascii=False))
    html = html.replace('CHINA_FILTERS_PLACEHOLDER', _json.dumps(china_js, ensure_ascii=False))
    html = html.replace('MAPS_CENTERS_PLACEHOLDER', _json.dumps(centers_js))
    html = html.replace('MAPS_ROLES_PLACEHOLDER', _json.dumps(roles_js, ensure_ascii=False))
    return html


PAGE_HTML = _build_page()


# 启动端口候选：优先保持原来的 5000，被系统保留/占用就往后面顺延
PREFERRED_PORTS = (5000, 8000, 8080, 8765, 9000, 7000, 6500, 5800, 5555)


def pick_port(host='127.0.0.1', preferred=PREFERRED_PORTS):
    """挑一个**真正能绑上**的端口，返回 (端口, 换端口的说明)。说明为空 = 首选端口可用。

    ⚠️ 不能把端口写死：Windows 会把**成片**的 TCP 端口保留给 Hyper-V / WinNAT
    （用 `netsh interface ipv4 show excludedportrange protocol=tcp` 可以看到），
    落在保留段里的端口一 bind 就抛 `WSAEACCES(10013)` —— 中文提示是
    「以一种访问权限不允许的方式做了一个访问套接字的尝试。」，而 `netstat` 里
    **看不到任何进程占用**，极易被误判成「端口被别的程序抢了」。
    更要命的是保留段每次开机由 winnat 重新生成、会漂移，所以固定换一个端口只是治标，
    正确做法就是启动时实测一遍。
    """
    reason = ''
    for p in preferred:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((host, p))
            return p, reason
        except OSError as e:
            if not reason:                      # 只记第一个失败的原因，通常就是 5000
                reason = f'{e.strerror}（WinError {e.errno}）'
        finally:
            s.close()
    # 候选全试不通：让系统分配一个空闲端口，记下号再释放（交给 app.run 重新绑）
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, 0))
        return s.getsockname()[1], reason or '候选端口全部不可用'
    finally:
        s.close()


if __name__ == '__main__':
    init_customer_db()
    HOST = '127.0.0.1'
    PORT, PORT_REASON = pick_port(HOST)
    if PORT_REASON:
        print(f'⚠️ 首选端口 {PREFERRED_PORTS[0]} 不能用：{PORT_REASON}')
        print(f'   已自动改用端口 {PORT}。'
              f'（Windows 把成片端口保留给 Hyper-V/WinNAT，属正常现象，不影响使用）')
    url = f'http://{HOST}:{PORT}/'
    print(f'启动本地网页服务：{url}')
    print('请在浏览器中打开（若未自动打开请手动访问）')
    webbrowser.open(url)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
