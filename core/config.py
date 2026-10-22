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

# 仅用于第 5 项预览的用途说明，不改变搜索条件本身。
COND_CATEGORY = {
    'wholesale': '客户发现',
    'importer': '客户发现',
    'buyer': '客户发现',
    'oem': '客户发现',
    'retailer': '客户发现',
    'project': '客户发现',
    'contact': '辅助线索',
    'exhibitor': '辅助线索',
    'linkedin': '辅助线索',
}

# 公式骨架：{p} = 产品词，{role} = 本地化角色词（见 COND_ROLES）
COND_TEMPLATE = {
    'wholesale': '{p} ({role})',
    'importer':  '{p} ({role})',
    'buyer':     '{p} ({role})',
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

# 国家限定（可选，默认关）：仅「谷歌网页搜索 · 标准模式」能叠加的一层强限定。
# ⚠️ 与 COUNTRY_CENTERS 同理做成**独立字典**，绝不并进 COUNTRIES（4 元组，改长度会连带炸两处）。
# 值 = (cr 值, site 后缀)：
#   · cr   → 拼进搜索 URL（&cr=countryXX，与 gl/hl 并列）。按**主机托管国**过滤结果，
#            属**硬限制**。必须是 ISO 3166-1 alpha-2 **大写**；空串 = 该国不被支持 → 等同不加。
#   · site → 拼进搜索词（形如 site:.fr，**必须带前导点**）。限域名，够硬。空串 = 不加。
# ⚠️ 2026-09-28 真机实测（法国）：现状 &gl/hl 出 10 条、.fr 占 50%；加 cr 反而只剩 7 条、
#    .fr 占 29% —— 因为该国 B2B 大量用 .com，cr 会把真客户挤掉。所以默认 'none'，用前想清楚。
COUNTRY_LIMITS = {
    'us':    ('countryUS', ''),            # 美国：不加 site:（该国以 .com 为主、.us 极少）
    'ca':    ('countryCA', 'site:.ca'),
    'uk':    ('countryGB', 'site:.uk'),    # ⚠️ UK 的 cr 码待实测（ISO 是 GB，谷歌页面也见 UK）；
    'de':    ('countryDE', 'site:.de'),    #    site:.uk 可覆盖 .co.uk（".co.uk".endswith(".uk")）
    'fr':    ('countryFR', 'site:.fr'),
    'it':    ('countryIT', 'site:.it'),
    'es':    ('countryES', 'site:.es'),
    'nl':    ('countryNL', 'site:.nl'),
    'be':    ('countryBE', 'site:.be'),
    'ch':    ('countryCH', 'site:.ch'),
    'ma':    ('countryMA', 'site:.ma'),
    'dz':    ('countryDZ', 'site:.dz'),
    'tn':    ('countryTN', 'site:.tn'),
    'sn':    ('countrySN', 'site:.sn'),
    'ca_fr': ('countryCA', 'site:.ca'),    # 非 ISO 的内部代码 → 映射到加拿大（法裔商家大量用 .ca）
    'ae':    ('countryAE', 'site:.ae'),
    'sa':    ('countrySA', 'site:.sa'),
    'qa':    ('countryQA', 'site:.qa'),
    'kw':    ('countryKW', 'site:.kw'),
    'om':    ('countryOM', 'site:.om'),
    'bh':    ('countryBH', 'site:.bh'),
    'eg':    ('countryEG', 'site:.eg'),
    'ir':    ('',          'site:.ir'),    # ⚠️ 伊朗不在谷歌 cr 支持列表 → cr 留空，只剩 site:
    'af':    ('countryAF', 'site:.af'),
    'tr':    ('countryTR', 'site:.tr'),
}
# 四选一（与前端 radio 的 value 必须一字不差）
COUNTRY_LIMIT_MODES = ('none', 'cr', 'site', 'both')
COUNTRY_LIMIT_DEFAULT = 'none'             # 默认「不改」→ 旧路径逐字不变

# 排除条件（网页上可勾选，每项带说明）：(key, 排除词, 说明)
EXCLUDE_OPTIONS = [
    ('amazon', '-amazon', '亚马逊（电商平台）'),
    ('ebay', '-ebay', 'eBay（电商平台）'),
    ('etsy', '-etsy', 'Etsy（电商平台）'),
    ('wikipedia', '-wikipedia', '维基百科（百科）'),
    # 2026-10-19 追加：视频 / 社交平台（用户点名）。这两站在 BLOCK_DOMAINS 里本来就硬挡，
    # 但那边只有 `.com` 主域 —— youtu.be / fb.com / fb.watch 这些变体会漏进来；
    # 而自定义模式又完全不拼搜索词，只能靠 DOMAIN_FAMILY 在本地按域名段挡。
    ('youtube', '-youtube', 'YouTube（视频平台）'),
    ('facebook', '-facebook', 'Facebook（社交平台）'),
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
    # Temu（拼多多海外版）：与淘宝/1688 同类，属「域名过滤」里的中国电商平台；
    # query 有值 → 标准模式拼进搜索词；DOMAIN_FAMILY 里也挂了 'temu'，自定义模式按域名挡。
    ('temu', '-temu', '排除 Temu', '中国电商平台'),
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

# 主页 UI 分组：这 4 项单独成「联系方式过滤」卡，其余 13 项留在第 5 卡「域名过滤」。
# ⚠️ 这只是**界面分组**，后端仍按 china_filters 的 key 全量判断（17 项语义一字不变）。
# ⚠️ 这 4 项的 query 必须为空 —— 它们只在结果 / 联系方式上判断，不进搜索词。
#    （core/ui.py 把它当第 5 个字段塞进 CHINA_FILTERS_PLACEHOLDER 的 JSON，前端按它分流。）
CONTACT_FILTER_KEYS = ('phone_86', 'wechat', 'qq', 'email_cn')

# ---- 自定义搜索词模式「第一步：抓取前排除平台域名」用的域名族（M24，2026-10-19）----
# 背景：自定义模式按用户要求「搜索词一字符不加」，所以没法靠 `-alibaba` 让谷歌别给 ——
#   只能拿到结果后**在本地按域名判定**，命中就 continue（连详情页都不开、不抓联系方式）。
# key 与 EXCLUDE_OPTIONS / CHINA_FILTER_OPTIONS 同名 —— 用户在「域名过滤」里勾哪个就挡哪个。
#
# 值是**品牌标签**：host 任意一段完全相等才算命中
#   amazon.de / www.amazon.co.uk / sellercentral.amazon.com  → 全中
# ⛔ 绝不用子串：否则 amazonas.com（亚马逊州）、my-ebay-shop.com 会被误杀。
# ⛔ 这个字典**只**给自定义模式用 —— 标准模式与地图模式仍走 is_blocked() + china_filter_reasons()，
#    那边一个字符都不改（用户 2026-10-19 拍板：只给自定义模式）。
DOMAIN_FAMILY = {
    'amazon': ('amazon',),
    'ebay': ('ebay',),
    'etsy': ('etsy',),
    'wikipedia': ('wikipedia',),
    'alibaba': ('alibaba',),
    'made-in-china': ('made-in-china',),
    'globalsources': ('globalsources',),
    '1688': ('1688',),
    'taobao': ('taobao', 'tmall'),
    # YouTube / Facebook：主域已在 BLOCK_DOMAINS，这里补的是**变体**——
    #   youtu.be（短链，搜索视频结果里最常见）、youtube-nocookie.com（嵌入域名）
    #   fb.com / fb.me / fb.watch（Facebook 自有短域）
    # ⛔ 仍是段相等：'youtu' 只匹配 host 段，不会误杀 youtube-downloader.com 之外的正常站；
    #    'fb' 段极短，但真正等于 `fb` 的域只有 Facebook 自己那几个。
    'youtube': ('youtube', 'youtu', 'youtube-nocookie'),
    'facebook': ('facebook', 'fb'),
    # Temu（拼多多海外版）：与 taobao / 1688 同类，属「域名过滤」里的中国电商平台
    #（key 来自 CHINA_FILTER_OPTIONS 的 temu）；主域 temu.com、区域域 temu.eu 等，段相等即可覆盖。
    'temu': ('temu',),
}
# 后缀判定（不是品牌族）：host 以该后缀结尾即命中。对应「排除 .cn 域名」那一项。
DOMAIN_SUFFIX_RULES = {'cn': '.cn'}
# 能参与「抓取前域名拦截」的全部 key。run_search 用它把勾选项过滤一遍 ——
# 用户勾的 supplier_words / wechat 之类不是域名判据，混进来会被静默忽略，先在这里对掉。
DOMAIN_RULE_KEYS = frozenset(DOMAIN_FAMILY) | frozenset(DOMAIN_SUFFIX_RULES)

# 「只标记不删除」时显示给用户的短标签：china_filter_reasons() 的 reason 串 → 徽章文字。
# ⚠️ 映射不到就**原样显示**（文案改了不会崩，只是徽章变长）—— 刻意不做 KeyError / 断言。
# ⚠️ 与 china_filter_reasons() 里那 4 条联系方式判据的**文字**绑定：那里改文案，这里要跟。
MARK_LABELS = {
    '联系方式含 +86 中国电话': '+86 电话',
    '页面含微信/WeChat': '微信',
    '页面含 QQ': 'QQ',
    '邮箱域名为 .cn': '.cn 邮箱',
}

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

# ================= 谷歌反爬：节奏 / 退避（2026-10-21）=================
# 背景（用户反馈「太容易弹验证码」）：不是提交频率高（默认参数只发 4~6 次搜索），
#   而是 ① 每次任务全新空白 profile（无 cookie）② 认不出外语拦截页 → 被当「没渲染」→ 15s 内重发 3 次
#   ③ 撞码后不减速、无熔断。这里只管 ②③ 的节奏部分，① 见 paths.chrome_profile_dir()。
#
# 单位：秒。语义是「两次 SERP 请求之间」的等待，不含请求本身耗时。
SERP_PAGE_MIN, SERP_PAGE_MAX = 6.0, 14.0          # 翻页 / 重试之后
SERP_QUERY_MIN, SERP_QUERY_MAX = 20.0, 50.0       # 一条查询（含翻页）跑完
SERP_LONG_REST_EVERY = 8                          # 每 N 次 SERP 请求插一次长休息
SERP_LONG_REST_MIN, SERP_LONG_REST_MAX = 60.0, 120.0
SERP_SKEW = 2.2        # 偏态强度：random()**2.2 让等待堆在区间下沿、偶尔冲到上沿。
                       # ⛔ 别退回 random.uniform(a, b) —— 规整的固定区间最容易被统计出「这是脚本」。
CAPTCHA_BACKOFF = (60, 180)   # 撞码退避窗口：第 1 轮等 60s，第 2 轮等 180s
CAPTCHA_POLL = 5              # 窗口内每 5s 复查一次（用户手动解了验证就能立刻继续）

# ================= 单个网页的加载预算（M30，2026-10-21）=================
# 背景（用户反馈「按停止要等好久」）：慢的不是停止请求，是**正在执行的导航**。
#   DrissionPage 出厂默认 page_load=30s + retry_times=3 → 一个网址最坏 126 秒，
#   而这整段时间里代码是**阻塞**的、读不到 STATE['stop']。enrich() 一次要开 3 个页面
#   （首页 + 2 个联系页），最坏能压住停止键 7 分钟。
#
# NAV_BUDGET 是「一个网址愿意等多久」的总预算（用户拍板 30 秒）。
# ⛔ 它**不等于**停止延迟：nav() 只让 CDP 的 Page.navigate 等 NAV_FIRE 秒（点火，不等加载），
#    之后自己按 NAV_POLL 的粒度轮询，所以停止延迟 ≈ NAV_POLL 级（≈0.3~0.6s），与预算无关。
NAV_BUDGET = 30.0     # 单个网址的总等待预算（超时不算失败：带着已加载的内容继续）
NAV_POLL = 0.3        # 轮询粒度：检查 STATE['stop'] 与 states.is_loading / ready_state
NAV_FIRE = 1.0        # Page.navigate 这条 CDP 命令最多等多久（⛔ 只是「命令返回」，不掐加载）
NAV_SOFT = 3.0        # 软预算：还没等到 load 事件就先返回，剩下的让页面在后台继续加载

# ================= 联系方式抓取：等多久（M31，2026-10-21）=================
# 背景（用户反馈「改了之后联系方式成功率掉下来」）：根因不是频率，而是**只读了一次 DOM**。
#   实测 `https://www.shopping-bags.net/` 的邮箱在第 2.4 秒才渲染出来，
#   `https://ecohound.co.uk/` 要到第 8 秒（1 秒时 HTML 186KB 无邮箱，8 秒时 358KB 有邮箱）。
#   ⛔ 更糟的是 M30 的 `page.get(timeout=1)`：DrissionPage 的 _wait_loaded() 一超时就
#      `Page.stopLoading()` —— 等于第 1 秒就把正在渲染的页面掐死，邮箱永远出不来。
# 所以改成：点火后**边等边看 DOM**，一抓到邮箱就走，最多等 ENRICH_WAIT 秒。
ENRICH_WAIT = 10.0         # 首页最多等这么久（实测有站点第 8 秒才把邮箱渲染出来）
ENRICH_CONTACT_WAIT = 6.0  # 联系页同样逻辑，预算小一点（已经有 2 个页面试过）
ENRICH_POLL = 0.4          # 复查 DOM 的间隔（同时是这段逻辑的停止延迟粒度）
ENRICH_GRACE = 2.0         # 页面**已经加载完**却仍没邮箱 → 再等这么久就收手，转联系页
