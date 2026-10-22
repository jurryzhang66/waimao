# -*- coding: utf-8 -*-
"""按域名后缀修正客户库的「国家/地区」字段，并删除 .org 记录（**默认只报告**）。

背景：`country` 的真实来源是「**搜索时选的目标国家**」，不是客户实际所在国 ——
      按国家搜一轮，整轮都标同一个国家。实测错得很整齐：
        .uk 17 条里 16 条标「加拿大」、.fr 37 条里 19 条标「加拿大」+7 条「墨西哥」、
        .au 9 条里 8 条「加拿大」、.de 3 条全「加拿大」、
        .mu 31 条里 21 条写成「毛里球斯」（错别字）+10 条「美国」。
      所以本脚本改按**域名后缀**推断国家（.uk → 英国、.fr → 法国 …）。

口径（用户 2026-10-22 拍板）：
    ① 所有国家级 ccTLD 都按域名改（不只 .cn/.ca）；
    ② 歧义后缀 .co/.re/.gov/.edu/.eu **一律不动**（.co 常被当 .com 替身，库里 6 条没一条是哥伦比亚；
       .re 是留尼汪、.edu/.eu 不是国家）；
    ③ 「毛里球斯 → 毛里求斯」错别字一并改正（含 5 条在 .com 上的，只改字面不改国家）；
    ④ `.org` 整条删除（用户原话「xxx.org 删除掉」），可用 --keep-id 保留个别条。

用法：
    python 修正国家.py                      # 默认 dry-run：只打印将要改/删什么，不写库
    python 修正国家.py --apply              # 真正写库（写前用 sqlite backup API 做一致性备份）
    python 修正国家.py --no-delete          # 只改国家，不删 .org
    python 修正国家.py --only-delete        # 只删 .org，不改国家
    python 修正国家.py --apply --keep-id 1155   # 保留某条 .org 不删（逗号分隔）
    python 修正国家.py --verbose            # 逐条列出歧义后缀那 28 条

⛔ 三条判定不能省（每条都有具体的血案）：
   1. TLD 取 `website_key` 的**末段**，不取 `website` —— website 常带路径与查询串
      （`https://buykorea.org/ec/prd/selectSvcDetail.do?goodsSn=3767020` 取最后一段会得到
      `…do?goodssn=3767020`）。website_key 是 normalize_domain() 归一后的值，去重与删除都以它为准。
   2. `.org` 用「末段**等于** org」判定，绝不用 `LIKE '%.org%'` —— 库里 `comceoccte.org.mx`、
      `ssfn.org.sa` 两条真实机构会被误删（末段是 mx / sa，该归墨西哥 / 沙特）。
   3. 每行用 normalize_domain(website) 复核 website_key；不一致的行**既不改也不删**，
      单列提示（先跑 db_fix_website_keys）。

为什么备份用 sqlite3 的 backup() 而不是 copyfile：客户库是 **WAL 模式**，
直接复制 .sqlite3 文件可能拿不到 -wal 里尚未 checkpoint 的数据，备份会缺最新写入。
（同 重标行业.py / 标注空行业.py / core/db.py::backup_db_before_delete 的做法）

⚠️ 用项目解释器跑（要 import core.db 的 normalize_domain，与主程序同一口径）：
   D:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe 修正国家.py
"""
import argparse
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3')
BACKUP_DIR = os.path.join(BASE_DIR, 'DB', 'backups')

try:
    from core.db import normalize_domain
except Exception as e:                                  # openpyxl 缺失 / 解释器不对
    print('❌ 无法导入 core.db（%s: %s）' % (type(e).__name__, e))
    print('   请用项目解释器运行：')
    print('   D:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python313\\python.exe 修正国家.py')
    sys.exit(1)

# ccTLD → 规范中文名（只收「含义明确」的国家级后缀；通用后缀一律不在此表）
TLD_COUNTRY = {
    'ca': '加拿大', 'cn': '中国', 'fr': '法国', 'mx': '墨西哥', 'mu': '毛里求斯',
    'sa': '沙特', 'uk': '英国', 'sg': '新加坡', 'us': '美国', 'au': '澳大利亚',
    'be': '比利时', 'ch': '瑞士', 'hk': '中国香港', 'in': '印度', 'de': '德国',
    'nz': '新西兰', 'br': '巴西', 'my': '马来西亚', 'it': '意大利', 'za': '南非',
    'ie': '爱尔兰', 'cz': '捷克', 'lv': '拉脱维亚', 'nl': '荷兰', 'vn': '越南',
}

# 歧义后缀：只在报告里计数，绝不改
AMBIGUOUS_TLDS = ('co', 're', 'gov', 'edu', 'eu')

# 错别字：只改字面，不推断国家（.com 等通用后缀只走这一条）
TYPOS = {'毛里球斯': '毛里求斯'}

ORG_TLD = 'org'

# dry-run 里对这些 id 额外打警示（删除是不可逆的，用户需要知情）
DELETE_HINTS = {
    1155: '⚠️ Who Gives A Crap 是真实品牌（环保卫生纸），只是用了 .org',
    80: '⚠️ 韩国政府贸易门户（KOTRA），不是买家',
}

MAX_GROUP_SHOW = 200   # 单个分组最多列多少条（145 条全列也没问题，这里只是保险）


def connect_ro():
    conn = sqlite3.connect('file:%s?mode=ro' % DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def tld_of(key):
    """取归一化域名的末段；没有点或 maps: 合成键返回 ''。"""
    key = (key or '').strip().lower()
    if not key or key.startswith('maps:') or '.' not in key:
        return ''
    return key.rsplit('.', 1)[-1]


def scan(conn, keep_ids):
    """扫描全库，返回所有待办。**只读**，不写库。

    返回 dict：
      total      总条数
      before     改前 country 分布（TRIM 后，空串记 ''）
      changes    { (tld, old, new): [ (id, key, company), ... ] }
      typo_only  [ (id, key, company, old, new), ... ]   .com 等通用后缀的错别字
      dels       [ (id, key, company, country), ... ]     末段是 .org 且不在 keep
      kept       [ ... ]                                  被 --keep-id 保住的 .org
      ambiguous  [ ... ]                                  歧义后缀（只计数/verbose 列）
      dirty      [ (id, key, real), ... ]                  website_key 与 website 不一致
    """
    out = {'total': 0, 'before': Counter(), 'changes': defaultdict(list),
           'typo_only': [], 'dels': [], 'kept': [], 'ambiguous': [], 'dirty': []}

    rows = conn.execute(
        "SELECT id, IFNULL(website,'') AS website, IFNULL(website_key,'') AS wk,"
        "       IFNULL(country,'') AS country, IFNULL(company_name,'') AS cn"
        " FROM customers ORDER BY id")
    for r in rows:
        out['total'] += 1
        rid, website, wk, country, cn = (r['id'], r['website'], r['wk'],
                                         (r['country'] or '').strip(), r['cn'])
        out['before'][country] += 1

        # ---- 判定 3：键与网址必须一致，否则跳过（不改不删）----
        real = normalize_domain(website)
        if wk and real and wk != real:
            out['dirty'].append((rid, wk, real))
            continue

        tld = tld_of(wk)
        if not tld:
            continue

        # ---- 判定 2：末段等于 org 才删 ----
        if tld == ORG_TLD:
            if rid in keep_ids:
                out['kept'].append((rid, wk, cn, country))
            else:
                out['dels'].append((rid, wk, cn, country))
            continue

        if tld in AMBIGUOUS_TLDS:
            out['ambiguous'].append((rid, wk, cn, country))
            continue

        want = TLD_COUNTRY.get(tld)
        if want:
            if country != want:
                out['changes'][(tld, country, want)].append((rid, wk, cn))
            continue

        # 通用后缀（.com/.net/.org 之外的新 gTLD…）：只修错别字，不推断国家
        fixed = TYPOS.get(country)
        if fixed:
            out['typo_only'].append((rid, wk, cn, country, fixed))

    return out


def print_report(plan, args, keep_ids):
    chg_n = sum(len(v) for v in plan['changes'].values())
    typo_n = len(plan['typo_only'])
    del_n = len(plan['dels'])

    print('=== 客户库国家字段整理（%s）===' % ('APPLY' if args.apply else 'dry-run，未写库'))
    print('库：%s' % DB_PATH)
    print('总数 %d 条' % plan['total'])
    print()

    print('=== 改前 country 分布 ===')
    for k, v in sorted(plan['before'].items(), key=lambda x: -x[1]):
        print('  %-10s %d' % (k or '(空)', v))
    print()

    if not args.only_delete:
        print('=== ① 待改国家：%d 条（按「后缀 · 旧 → 新」分组）===' % chg_n)
        for (tld, old, new), rows in sorted(
                plan['changes'].items(), key=lambda x: (-len(x[1]), x[0][0])):
            print('  ── .%-4s %s → %s（%d 条）' % (tld, old or '(空)', new, len(rows)))
            for rid, wk, cn in rows[:MAX_GROUP_SHOW]:
                print('     id=%-5s %-34s %s' % (rid, wk[:34], cn[:26]))
            if len(rows) > MAX_GROUP_SHOW:
                print('     …（还有 %d 条）' % (len(rows) - MAX_GROUP_SHOW))
        print('  小计 %d 条' % chg_n)
        print()

        print('=== ② 错别字（通用后缀，只改字面、不改国家）：%d 条 ===' % typo_n)
        for rid, wk, cn, old, new in plan['typo_only']:
            print('  id=%-5s %-34s %s → %s   %s' % (rid, wk[:34], old, new, cn[:20]))
        if not typo_n:
            print('  （无）')
        print()

    if not args.no_delete:
        print('=== ③ 待删 .org：%d 条 ===' % del_n)
        for rid, wk, cn, country in plan['dels']:
            hint = DELETE_HINTS.get(rid, '')
            print('  id=%-5s %-34s %-6s %s %s' % (rid, wk[:34], country or '(空)', cn[:22], hint))
        if not del_n:
            print('  （无）')
        if plan['kept']:
            print('  已按 --keep-id 保留 %d 条：%s'
                  % (len(plan['kept']), ', '.join(str(r[0]) for r in plan['kept'])))
        print()

    if plan['dirty']:
        print('=== ⚠️ 跳过：website_key 与 website 不一致 %d 条（先跑 db_fix_website_keys）==='
              % len(plan['dirty']))
        for rid, wk, real in plan['dirty'][:20]:
            print('  id=%-5s key=%-28s 网址归一=%-28s' % (rid, wk, real))
        print()

    print('=== 不动：歧义后缀 %d 条（.%s）==='
          % (len(plan['ambiguous']), '/.'.join(AMBIGUOUS_TLDS)))
    if args.verbose:
        for rid, wk, cn, country in plan['ambiguous']:
            print('  id=%-5s %-34s %-6s %s' % (rid, wk[:34], country or '(空)', cn[:22]))
    else:
        by_tld = Counter(tld_of(r[1]) for r in plan['ambiguous'])
        print('  ' + '  '.join('.%s:%d' % (t, by_tld[t]) for t in AMBIGUOUS_TLDS if by_tld[t])
              + '   （加 --verbose 看清单）')
    print()

    after_total = plan['total'] - (0 if args.no_delete else del_n)
    print('合计：改 %d 条（含错别字 %d）、删 %d 条，库将从 %d → %d 条'
          % (0 if args.only_delete else chg_n + typo_n, typo_n,
             0 if args.no_delete else del_n, plan['total'], after_total))
    if not args.apply:
        print('\n--dry-run 结束（未写库）。确认无误后加 --apply 执行。')
        if any(r[0] in DELETE_HINTS for r in plan['dels']):
            print('提示：想保留某条 .org 就加 --keep-id <id>，例如 --keep-id %s'
                  % ','.join(str(r[0]) for r in plan['dels'] if r[0] in DELETE_HINTS))


def do_backup():
    """一致性备份到 DB/backups/客户库_修正国家前_<时间戳>.sqlite3，返回路径。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    bak = os.path.join(BACKUP_DIR, '客户库_修正国家前_%s.sqlite3'
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
    """备份 → 一个事务里「先删后改」→ 复查。返回退出码。"""
    del_ids = [] if args.no_delete else [r[0] for r in plan['dels']]
    updates = []
    if not args.only_delete:
        for (tld, old, new), rows in plan['changes'].items():
            updates.extend((new, rid, new) for rid, _wk, _cn in rows)
        updates.extend((new, rid, new) for rid, _wk, _cn, _old, new in plan['typo_only'])

    # 安全门：id 必须是正整数。空列表绝不能走到 DELETE（防「清库」）。
    del_ids = [i for i in del_ids if isinstance(i, int) and i > 0]

    if not del_ids and not updates:
        print('\n没有需要处理的内容，未写库、未备份。')
        return 0

    bak = do_backup()
    print('\n已备份：%s（%d 字节）' % (bak, os.path.getsize(bak)))

    conn = sqlite3.connect(DB_PATH)
    try:
        before_cnt = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        with conn:                      # 单个事务：删与改一起提交，失败一起回滚
            if del_ids:
                conn.executemany('DELETE FROM customers WHERE id=?', [(i,) for i in del_ids])
            if updates:
                # 条件 UPDATE → 天然幂等：已经是目标值的行不会被再写一次
                conn.executemany(
                    "UPDATE customers SET country=? WHERE id=? AND IFNULL(country,'')<>?",
                    updates)
        after_cnt = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
    finally:
        conn.close()

    print('已删除 %d 条、已改 %d 条；库 %d → %d 条'
          % (before_cnt - after_cnt, len(updates), before_cnt, after_cnt))
    return 0


def verify(args, keep_ids):
    """写库后复查：待办必须归零、.org 只剩 keep、键一致性仍为 0。"""
    conn = connect_ro()
    try:
        plan = scan(conn, keep_ids)
        chg_n = sum(len(v) for v in plan['changes'].values())
        typo_n = len(plan['typo_only'])
        del_n = len(plan['dels'])
        print('\n=== 复查 ===')
        print('  剩余待改国家 %d 条 / 剩余错别字 %d 条 / 剩余待删 .org %d 条 / 键不一致 %d 条'
              % (chg_n, typo_n, del_n, len(plan['dirty'])))
        print('  当前国家分布：')
        for k, v in sorted(plan['before'].items(), key=lambda x: -x[1]):
            print('    %-10s %d' % (k or '(空)', v))
        ok = True
        if not args.only_delete and (chg_n or typo_n):
            print('  ⚠️ 还有待改项，说明没改干净')
            ok = False
        if not args.no_delete and del_n:
            print('  ⚠️ 还有待删 .org，说明没删干净')
            ok = False
        if plan['dirty']:
            print('  ⚠️ 键/网址不一致 %d 条，请跑 db_fix_website_keys' % len(plan['dirty']))
        print('  ✅ 复查通过' if ok else '  ❌ 复查未通过')
        return 0 if ok else 1
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description='按域名后缀修正客户库国家 + 删除 .org（默认只报告）')
    ap.add_argument('--apply', action='store_true',
                    help='真正写库（默认只报告）。写前自动做一致性备份。')
    ap.add_argument('--no-delete', action='store_true', help='只改国家，不删 .org')
    ap.add_argument('--only-delete', action='store_true', help='只删 .org，不改国家')
    ap.add_argument('--keep-id', default='',
                    help='保留这些 .org 不删，逗号分隔（例如 1155,80）')
    ap.add_argument('--verbose', action='store_true', help='逐条列出歧义后缀那些记录')
    args = ap.parse_args()

    if args.no_delete and args.only_delete:
        print('❌ --no-delete 与 --only-delete 不能同时用')
        return 1

    keep_ids = set()
    for part in (args.keep_id or '').replace('，', ',').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            keep_ids.add(int(part))
        except ValueError:
            print('❌ --keep-id 里有不是数字的项：%r' % part)
            return 1

    if not os.path.exists(DB_PATH):
        print('找不到客户库：', DB_PATH)
        return 1

    conn = connect_ro()
    try:
        plan = scan(conn, keep_ids)
    finally:
        conn.close()

    print_report(plan, args, keep_ids)

    if not args.apply:
        return 0

    rc = apply_plan(plan, args)
    if rc:
        return rc
    return verify(args, keep_ids)


if __name__ == '__main__':
    sys.exit(main())
