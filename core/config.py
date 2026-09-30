# -*- coding: utf-8 -*-
"""可配置常量（原 `客户开发工具.py` 第 34–260 行整段搬入）。

只放纯数据 + 一个不依赖任何其它模块的函数 `cond_template()`，所以本文件零 import，
永远处在依赖图最底层，不会和 paths / state / db / ui 形成环。
"""
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
