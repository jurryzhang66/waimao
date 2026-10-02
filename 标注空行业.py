# -*- coding: utf-8 -*-
"""把「行业没标注」的客户批量写成指定行业（**默认只报告**）。

背景：`industry` 为空的记录在「客户库查询页 /db」里会落到「未标注」那一档，勾出来核对完、
      确认它们都属于同一行业后，用本脚本一次性补上，省得一条条改。
      只填空值，**不动任何已有行业**（要改旧口径请用 `重标行业.py`，要重新判定请用 `回填行业.py --overwrite`）。

用法：
    python 标注空行业.py                      # 默认 dry-run：只打印将要改什么，不写库
    python 标注空行业.py --apply              # 真正写库（写前用 sqlite backup API 做一致性备份）
    python 标注空行业.py --industry 食品       # 想标成别的行业名就换这个参数（默认 食品）
    python 标注空行业.py --apply --exclude-id 255,259   # 先把不想标的 id 排除掉

⚠️ 口径说明：本脚本判定「空」用的是 `IFNULL(TRIM(industry),'')=''`（连纯空白也算空），
   而查询页的「未标注」分面用的是 `IFNULL(industry,'')=''` —— 两者只在「行业列是一串空格」
   这种脏数据上会有差异，本脚本会把这个差异单独报出来，不闷着。

为什么备份用 sqlite3 的 backup() 而不是 copyfile：客户库是 **WAL 模式**，
直接复制 .sqlite3 文件可能拿不到 -wal 里尚未 checkpoint 的数据，备份会缺最新写入。
（同 重标行业.py / 补历史欠账.py 的做法）
"""
import argparse
import os
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3')

EMPTY_WHERE = "IFNULL(TRIM(industry),'')=''"
# 与查询页「未标注」分面同口径（不 TRIM），只用来报差异
PAGE_EMPTY_WHERE = "IFNULL(industry,'')=''"

MAX_SHOW = 30          # dry-run 里最多列这么多条，多了只看条数


def connect_ro():
    conn = sqlite3.connect('file:%s?mode=ro' % DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def stats(conn):
    """行业 → 条数分布。
    ⚠️ 刻意用**下标**取值而不是 `r['industry']` —— 本函数会被两种连接调用：
       只读连接（`connect_ro()`，设了 row_factory）和写库连接（裸 `sqlite3.connect`）。
       依赖 row_factory 的话，写库那条路会在**改完数据之后**抛 TypeError，
       让脚本看起来「失败」，其实数据已经写进去了（实测踩过）。"""
    return {r[0] or '': r[1] for r in conn.execute(
        "SELECT industry, COUNT(*) AS n FROM customers GROUP BY industry")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='真正写库（默认只报告）。写前自动做一致性备份。')
    ap.add_argument('--industry', default='食品',
                    help='要写进去的行业名（默认 食品）')
    ap.add_argument('--exclude-id', default='',
                    help='不想被标到的 id，逗号分隔（例如 255,259）')
    args = ap.parse_args()

    target = (args.industry or '').strip()
    if not target:
        print('❌ --industry 不能是空字符串')
        return 1

    exclude = set()
    for part in (args.exclude_id or '').replace('，', ',').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            exclude.add(int(part))
        except ValueError:
            print('❌ --exclude-id 里有不是数字的项：%r' % part)
            return 1

    if not os.path.exists(DB_PATH):
        print('找不到客户库：', DB_PATH)
        return 1

    conn = connect_ro()
    before = stats(conn)

    rows = [dict(r) for r in conn.execute(
        'SELECT id, website, IFNULL(company_name,\'\') AS cn, IFNULL(source,\'\') AS src'
        ' FROM customers WHERE %s ORDER BY id' % EMPTY_WHERE)]
    page_blank = conn.execute(
        'SELECT COUNT(*) FROM customers WHERE %s' % PAGE_EMPTY_WHERE).fetchone()[0]
    conn.close()

    todo = [r for r in rows if r['id'] not in exclude]
    skipped = [r for r in rows if r['id'] in exclude]

    print('=== 当前 industry 分布 ===')
    for k, v in sorted(before.items(), key=lambda x: -x[1]):
        print('  %-12s %d' % (k or '(空)', v))
    print()
    print('=== 待标注（行业为空 → %s）===' % target)
    for r in todo[:MAX_SHOW]:
        print('  id=%-4s %-42s %-28s %s' % (
            r['id'], (r['website'] or '(无网址)')[:42], r['cn'][:28], r['src']))
    if len(todo) > MAX_SHOW:
        print('  …（还有 %d 条，完整清单见客户库或 /db 页）' % (len(todo) - MAX_SHOW))
    print('  合计 %d 条' % len(todo))
    if skipped:
        print('  已按 --exclude-id 跳过 %d 条：%s'
              % (len(skipped), ', '.join(str(r['id']) for r in skipped)))
    if page_blank != len(rows):
        print('  ⚠️ 口径差异：查询页「未标注」分面数是 %d，本脚本按 TRIM 判定是 %d'
              '（差的那些是行业列只填了空格的脏数据）' % (page_blank, len(rows)))

    if not args.apply:
        print('\n--dry-run 结束（未写库）。确认无误后加 --apply 执行。')
        return 0

    if not todo:
        print('\n没有需要标注的记录，未写库。')
        return 0

    # ---- 一致性备份（WAL 安全）----
    ts = time.strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3.bak_标注空行业_%s' % ts)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(bak)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    print('\n已备份:', bak, os.path.getsize(bak), '字节')

    # ---- 写库：只改「行业为空」的那些 id，逐条按主键更新 ----
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executemany('UPDATE customers SET industry=? WHERE id=? AND %s' % EMPTY_WHERE,
                         [(target, r['id']) for r in todo])
        conn.commit()
        after = stats(conn)
    finally:
        conn.close()

    print('\n=== 改后 industry 分布 ===')
    for k, v in sorted(after.items(), key=lambda x: -x[1]):
        print('  %-12s %d' % (k or '(空)', v))
    print('\n✅ 已标注 %d 条为「%s」。' % (len(todo), target))
    print('⚠️ 飞书「客户信息」表的「行业」选项需人工确认已包含「%s」。' % target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
