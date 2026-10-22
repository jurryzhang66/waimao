# -*- coding: utf-8 -*-
"""清理客户库里的「非采购方」噪音站点（**默认只报告**）。

背景（2026-10-22，M34）：客户库 1209 条里混进了大量根本不可能向中国供应商下单的站点 ——
综合电商平台（amazon.fr / ebay.fr / carrefour.fr）、比价聚合（idealo.fr / picclick.fr）、
B2B 目录（kompass / made-in-china / globalsources / thomasnet / go4worldbusiness）、
社交与搜索（facebook.com / google.com.hk / yelp.com）、政府与高校（*.gov / *.edu / *.ac.th）、
内容站（新闻 / 杂志 / 旅游 / 餐厅目录 / 影院 / 博彩 / 景点）、B2C 品牌官网（catsan.fr / hillspet.fr）。
它们占着名额、拉低评分均值，还让「按国家筛选」的结果全是平台页。

分两档（口径不同，别混）：
    A 组 **规则判定**（可持续）——域名段/后缀命中就删。以后新采进同类站点照样清得掉。
        · 平台/比价/大卖场  · 社交/搜索/点评  · 黄页/B2B 目录  · 政府/高校/军队
    B 组 **显式清单**（人工逐条核过）——内容站 / 本地生活 / B2C 零售与品牌官网。
        这一档**必须**硬编码 website_key：靠关键词（restaurant / news / hotel …）判定会误杀
        真实客户（库里有 `unileverfoodsolutions.com.mx`「La Comida más vendida en los
        restaurantes…」、`proveedoradiez.com`「Insumos para Restaurante」、`tomandsawyer.com`
        「为您的毛茸茸家人准备的真正美食」—— 全是正经 B2B 供应商/品牌，一个都不能删）。

⛔ 判定必须用「域名段**相等**」，绝不能用子串（M24 血案）：
   `amazon.de` 命中、`amazonas.com` 不命中；`fb.com` 不能靠 `'.com'` 蒙。
⛔ 免费建站子域（`*.wixsite.com` / `*.wordpress.com` / `*.myshopify.com`）**故意不在规则里** ——
   库里 `taishen808.wixsite.com`（拉面制造商）、`pawlinecatlitter.wordpress.com`（猫砂工厂）
   都是真实小公司，用免费域名不等于噪音，删了就是丢客户。
⛔ 单店商户（`ptitpere.fr`、`jackdolly-lyon.fr`、`omarjee.mu` 这类实体零售）**不删** ——
   它们不是平台，仍可能经批发商采购，属于「低价值但有效」的线索。

用法：
    python 清理噪音.py                     # 默认 dry-run：只打印待删清单，不写库
    python 清理噪音.py --apply             # 真正写库（写前用 sqlite backup API 做一致性备份）
    python 清理噪音.py --group A           # 只看/只清规则档
    python 清理噪音.py --group B --apply   # 只看/只清显式清单档
    python 清理噪音.py --keep-key amazon.fr,yelp.com   # 个别保留（逗号分隔）
    python 清理噪音.py --verbose           # 额外列出「边界保留」的站点

为什么备份用 sqlite3 的 backup() 而不是 copyfile：客户库是 **WAL 模式**，
直接复制 .sqlite3 可能拿不到 -wal 里未 checkpoint 的数据。
（同 修正国家.py / 重标行业.py / core/db.py::backup_db_before_delete）

⚠️ 用项目解释器跑（要 import core.db 的 normalize_domain，与主程序同一口径）：
   D:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe 清理噪音.py
"""
import argparse
import os
import sqlite3
import sys
import time
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3')
BACKUP_DIR = os.path.join(BASE_DIR, 'DB', 'backups')

try:
    from core.db import normalize_domain
except Exception as e:                                  # openpyxl 缺失 / 解释器不对
    print('❌ 无法导入 core.db（%s: %s）' % (type(e).__name__, e))
    print('   请用项目解释器运行：')
    print('   D:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe 清理噪音.py')
    sys.exit(1)

# ---------------------------------------------------------------- A 组：规则表
# ⛔ 一律按「域名段相等」比对。往表里加词之前先想清楚它会不会是某家真公司的名字。
PLATFORM = {                       # 综合电商 / 比价 / 大卖场：B2C 渠道，不是采购方
    'amazon', 'ebay', 'aliexpress', 'alibaba', 'walmart', 'carrefour', 'auchan',
    'veepee', 'kaufland', 'leroymerlin', 'idealo', 'leboncoin', 'zooplus', 'medpets',
    'fruugo', 'picclick', 'cdiscount', 'fnac', 'darty', 'boulanger', 'manomano',
    'rakuten', 'otto', 'allegro', 'bol', 'coolblue', 'temu', 'shein', 'wish',
    'etsy', 'shopee', 'lazada', 'mercadolibre', 'falabella', 'liverpool',
}
SOCIAL = {                         # 社交 / 搜索 / 点评 / 抓取工具 / 内容平台：永远不是客户
    'facebook', 'youtube', 'linkedin', 'instagram', 'twitter', 'tiktok', 'pinterest',
    'reddit', 'wikipedia', 'google', 'yelp', 'tripadvisor', 'bing', 'yahoo', 'snovio',
    'medium', 'substack', 'quora', 'tumblr',
}
# ⛔ `wordpress` / `wixsite` / `blogspot` / `myshopify` 绝不能进这张表：
#    它们是免费建站**子域**（xxx.wordpress.com），按段判定会命中所有真实小公司官网。
DIRECTORY = {                      # 黄页 / B2B 目录与撮合平台：同行与中间商
    'yellowpages', 'pagesjaunes', 'annuaire', 'cylex', 'kompass', 'europages',
    'b2bmap', 'made-in-china', 'globalsources', 'indiamart', 'thomasnet',
    'eworldtrade', 'go4worldbusiness', 'tradeindia', 'exporthub', 'hotfrog', 'directory',
}
ORG_TLD = {'edu', 'gov', 'mil'}    # 高校 / 政府 / 军队
# 政府段：各国写法不同，都只在「末段是两位国家码」时才认
#   gov.us / govt.nz / gob.mx / gouv.fr / gc.ca / go.jp / gv.at
# ⛔ 必须带 `len(p[-1]) == 2` 这一条：否则 `go.com`、`gc.com` 这类商业域名会被误判。
GOV_SEG = {'gov', 'govt', 'gob', 'gouv', 'gc', 'go', 'gv'}

REASON_A = {}
for _seg in PLATFORM:
    REASON_A[_seg] = '平台'
for _seg in SOCIAL:
    REASON_A[_seg] = '社交工具'
for _seg in DIRECTORY:
    REASON_A[_seg] = '目录平台'

# ------------------------------------------------------- B 组：显式清单（人工核）
# 格式：website_key → 删除理由（理由会打进报告，方便日后复核）
EXPLICIT = {
    # —— 内容站 / 媒体 / 学术 / 研究报告 ——
    'sgfneighborhoodnews.com': '内容站·地方新闻',
    'laroussecocina.mx': '内容站·美食媒体',
    'foodies.mu': '内容站·美食博客',
    'fresh.mu': '内容站·健康科普',
    'ionnews.mu': '内容站·新闻门户',
    'sciencedirect.com': '内容站·学术期刊库',
    'globenewswire.com': '内容站·新闻稿分发',
    'whole-dog-journal.com': '内容站·宠物杂志测评',
    'dataintelo.com': '内容站·市场研究报告',
    'growthmarketreports.com': '内容站·市场研究报告',
    'datahorizzonresearch.com': '内容站·市场研究报告',
    'verifiedmarketresearch.com': '内容站·市场研究报告',
    'techsciresearch.com': '内容站·市场研究报告',
    'market.us': '内容站·市场研究报告',
    # —— 机构（用了通用后缀，规则抓不到）——
    'cityofkingsville.com': '机构·市政府办公室',
    'cuadernoscatedras.unam.mx': '机构·墨西哥国立自治大学',
    # —— 本地生活：旅游 / 酒店 / 餐厅目录 / 影院 / 景点 / 博彩 / 订座 ——
    'smarttraveller.mu': '本地生活·旅游资讯',
    'heritageresorts.mu': '本地生活·酒店度假村',
    'sortir.mu': '本地生活·出行指南',
    'restaurants.mu': '本地生活·餐厅目录',
    'bookatable.mu': '本地生活·订座平台',
    'deals.mu': '本地生活·团购比价',
    'mcine.mu': '本地生活·影院',
    'chamarelterrede7couleurs.mu': '本地生活·旅游景点',
    'supertote.mu': '本地生活·赛马博彩',
    'saudia.com': '本地生活·航空公司',
    'rsmmu.mu': '本地生活·会计师事务所',      # 专业服务方，不是采购方
    # —— B2C 多品牌零售 / 品牌官网 ——
    'brekz.fr': 'B2C零售·宠物用品电商',
    'animelis.fr': 'B2C零售·宠物用品电商',
    'hillspet.fr': 'B2C零售·希尔思品牌官网',
    'catsan.fr': 'B2C零售·玛氏Catsan品牌官网',
}

# 边界保留（只是让报告能说清「为什么这几条没删」，不参与任何判定）
BOUNDARY_KEPT = {
    'ptitpere.fr': '单店宠物店，仍可能经批发商采购',
    'jacketdolly-lyon.fr': '单店宠物店，仍可能经批发商采购',
    'omarjee.mu': '毛里求斯零售连锁，集团层面可能采购',
    'furniture.mu': '家具电商，行业标错但站点本身是商家',
    'smartshop.mu': '自动售货机运营商，可能采购包装',
    'ordermanzer.mu': '餐饮广场/点餐系统，落地商户待查',
    'theafricanmarketplace.mu': '电商平台，规模小待查',
    'taishen808.wixsite.com': '免费域名但是真实拉面制造商（客户）',
    'pawlinecatlitter.wordpress.com': '免费域名但是猫砂制造商（可能同行）',
    'purrnwoofsg.wordpress.com': '免费域名但是真实宠物用品商家',
    'unileverfoodsolutions.com.mx': 'B2B 餐饮供应（巨头）',
    'proveedoradiez.com': 'B2B 餐饮用品供应，可能是客户',
    'inmeza.com': 'B2B 餐饮设备供应，可能是客户',
    'tomandsawyer.com': '加拿大宠物鲜食品牌，可能是客户',
    'gastronomeanimal.com': '加拿大宠物食品商家',
    'plasticbagpc.com': '塑料包装公司官网（标题带 News 而已）',
    'busy-bee.ca': '加拿大西部卫生用品分销商（关键词含「部」误伤）',
}

MAX_GROUP_SHOW = 300


def connect_ro():
    conn = sqlite3.connect('file:%s?mode=ro' % DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def judge(key):
    """返回 (group, reason)；不是噪音返回 ('', '')。**只看域名段相等**。"""
    p = [x for x in (key or '').lower().split('.') if x]
    if len(p) < 2:
        return '', ''
    # 显式清单优先（键是完整 website_key，天然无歧义）
    if key in EXPLICIT:
        return 'B', EXPLICIT[key]
    # 机构后缀
    if p[-1] in ORG_TLD:
        return 'A', '机构·.' + p[-1]
    if len(p) >= 3 and len(p[-1]) == 2:
        if p[-2] in GOV_SEG:
            return 'A', '机构·%s.%s' % (p[-2], p[-1])
        if p[-2] in ('ac', 'edu'):
            return 'A', '机构·%s.%s' % (p[-2], p[-1])
    if 'mil' in p[-3:]:
        return 'A', '机构·mil'
    # 平台/社交/目录：扫除末段（TLD）以外的每一段
    for seg in p[:-1]:
        r = REASON_A.get(seg)
        if r:
            return 'A', r + '·' + seg
    return '', ''


def scan(conn, keep_keys):
    out = {'total': 0, 'before': Counter(), 'A': [], 'B': [], 'dirty': []}
    for r in conn.execute(
            "SELECT id, IFNULL(website,'') AS website, IFNULL(website_key,'') AS wk,"
            "       IFNULL(country,'') AS country, IFNULL(industry,'') AS industry,"
            "       IFNULL(company_name,'') AS cn FROM customers ORDER BY id"):
        out['total'] += 1
        rid, website = r['id'], r['website']
        wk = (r['wk'] or '').strip().lower()
        out['before'][(r['country'] or '').strip()] += 1

        if not wk:
            continue
        # 键与网址必须一致，否则跳过（不改不删），先跑 db_fix_website_keys
        real = normalize_domain(website)
        if real and wk != real:
            out['dirty'].append((rid, wk, real))
            continue
        if wk in keep_keys:
            continue
        g, why = judge(wk)
        if g:
            out[g].append((rid, wk, r['country'] or '', r['industry'] or '', r['cn'] or '', why))
    return out


def print_report(plan, args):
    na, nb = len(plan['A']), len(plan['B'])
    show = []
    if args.group in ('', 'A'):
        show.append(('A', na))
    if args.group in ('', 'B'):
        show.append(('B', nb))
    want = na if args.group == 'A' else nb if args.group == 'B' else na + nb

    print('=== 客户库噪音清理（%s）===' % ('APPLY' if args.apply else 'dry-run，未写库'))
    print('库：%s' % DB_PATH)
    print('总数 %d 条' % plan['total'])
    print()

    titles = {
        'A': 'A 组 · 规则档（平台/社交/目录/机构）',
        'B': 'B 组 · 显式清单档（内容站/本地生活/B2C 零售）',
    }
    for g, n in show:
        rows = plan[g]
        print('=== 待删 %s：%d 条 ===' % (titles[g], n))
        if not rows:
            print('  （无）')
        # 按理由分组，同理由排一起，便于一眼扫过去
        by_why = {}
        for row in rows:
            by_why.setdefault(row[5], []).append(row)
        for why, group in sorted(by_why.items(), key=lambda x: (-len(x[1]), x[0])):
            print('  ── %s（%d 条）' % (why, len(group)))
            for rid, wk, country, industry, cn, _ in group[:MAX_GROUP_SHOW]:
                print('     id=%-5s %-32s %-8s %-10s %s'
                      % (rid, wk[:32], country or '(空)', industry[:10], cn[:30]))
            if len(group) > MAX_GROUP_SHOW:
                print('     …（还有 %d 条）' % (len(group) - MAX_GROUP_SHOW))
        print()

    if args.verbose:
        print('=== 边界保留：不删，仅说明理由（%d 条在库）===' % len(BOUNDARY_KEPT))
        have = {}
        conn = connect_ro()
        try:
            for r in conn.execute('SELECT id, website_key FROM customers'):
                if r['website_key'] in BOUNDARY_KEPT:
                    have[r['website_key']] = (r['id'], BOUNDARY_KEPT[r['website_key']])
        finally:
            conn.close()
        for wk, (rid, why) in sorted(have.items()):
            print('  id=%-5s %-32s %s' % (rid, wk, why))
        print()

    if plan['dirty']:
        print('=== ⚠️ 跳过：website_key 与 website 不一致 %d 条（先跑 db_fix_website_keys）==='
              % len(plan['dirty']))
        for rid, wk, real in plan['dirty'][:20]:
            print('  id=%-5s key=%-28s 网址归一=%-28s' % (rid, wk, real))
        print()

    print('合计：删 %d 条（A %d + B %d）%s'
          % (want, na if args.group in ('', 'A') else 0,
             nb if args.group in ('', 'B') else 0,
             '' if args.group == '' else '（--group %s）' % args.group))
    print('库将从 %d → %d 条' % (plan['total'], plan['total'] - want))
    if not args.apply:
        print('\n--dry-run 结束（未写库）。确认无误后加 --apply 执行。')


def do_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    bak = os.path.join(BACKUP_DIR, '客户库_清理噪音前_%s.sqlite3'
                       % time.strftime('%Y%m%d_%H%M%S'))
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(bak)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    return bak


def apply_plan(plan, args):
    ids = []
    if args.group in ('', 'A'):
        ids += [r[0] for r in plan['A']]
    if args.group in ('', 'B'):
        ids += [r[0] for r in plan['B']]
    # 安全门：id 必须是正整数。空列表绝不能走到 DELETE（防清库）。
    ids = sorted({i for i in ids if isinstance(i, int) and i > 0})
    if not ids:
        print('\n没有需要删除的内容，未写库、未备份。')
        return 0

    bak = do_backup()
    print('\n已备份：%s（%d 字节）' % (bak, os.path.getsize(bak)))

    conn = sqlite3.connect(DB_PATH)
    try:
        before = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        with conn:                    # 单事务：要么全删，要么全不删
            conn.executemany('DELETE FROM customers WHERE id=?', [(i,) for i in ids])
        after = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
    finally:
        conn.close()

    print('已删除 %d 条（计划 %d 条，差集正常说明有重复 id）；库 %d → %d 条'
          % (before - after, len(ids), before, after))
    return 0


def verify(args, keep_keys):
    conn = connect_ro()
    try:
        plan = scan(conn, keep_keys)
        na, nb = len(plan['A']), len(plan['B'])
        print('\n=== 复查 ===')
        print('  剩余待删：A %d 条 / B %d 条 / 键不一致 %d 条' % (na, nb, len(plan['dirty'])))
        print('  当前国家分布：')
        for k, v in sorted(plan['before'].items(), key=lambda x: -x[1]):
            print('    %-10s %d' % (k or '(空)', v))
        ok = True
        if args.group in ('', 'A') and na:
            print('  ⚠️ A 组还有 %d 条没删干净' % na)
            ok = False
        if args.group in ('', 'B') and nb:
            print('  ⚠️ B 组还有 %d 条没删干净' % nb)
            ok = False
        print('  ✅ 复查通过' if ok else '  ❌ 复查未通过')
        return 0 if ok else 1
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description='清理客户库里的非采购方噪音站点（默认只报告）')
    ap.add_argument('--apply', action='store_true',
                    help='真正写库（默认只报告）。写前自动做一致性备份。')
    ap.add_argument('--group', default='', choices=['', 'A', 'B'],
                    help='只处理 A 组（规则）或 B 组（显式清单），默认两组都处理')
    ap.add_argument('--keep-key', default='',
                    help='保留这些 website_key 不删，逗号分隔（例如 amazon.fr,yelp.com）')
    ap.add_argument('--verbose', action='store_true', help='额外列出边界保留的站点与理由')
    args = ap.parse_args()

    keep_keys = {x.strip().lower() for x in
                 (args.keep_key or '').replace('，', ',').split(',') if x.strip()}

    if not os.path.exists(DB_PATH):
        print('找不到客户库：', DB_PATH)
        return 1

    conn = connect_ro()
    try:
        plan = scan(conn, keep_keys)
    finally:
        conn.close()

    print_report(plan, args)

    if not args.apply:
        return 0
    rc = apply_plan(plan, args)
    if rc:
        return rc
    return verify(args, keep_keys)


if __name__ == '__main__':
    sys.exit(main())
