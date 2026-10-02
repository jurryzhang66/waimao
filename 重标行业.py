# -*- coding: utf-8 -*-
"""历史行业值重标：把旧口径改成与「关键词库.json」一致的规范名（**默认只报告**）。

背景：`industry` 列存在两套历史口径 ——
    · 关键词库选中的行业（规范 8 值：宠物用品 / LED照明 / 家具 / 服装 / 机械零部件 / 户外用品 / 食品 / 塑料包装袋）
    · `回填行业.py` 早期规则写入的（家具家居 / 汽配）
    家具家居 → 家具        （18 条）
    汽配     → 机械零部件   （5 条）
本脚本只做**纯改名**，不重新猜测；`回填行业.py --overwrite` 才会重新判定。

用法：
    python 重标行业.py              # 默认 dry-run：只打印将要改什么，不写库
    python 重标行业.py --apply      # 真正写库（写前用 sqlite backup API 做一致性备份）

为什么备份用 sqlite3 的 backup() 而不是 copyfile：客户库是 **WAL 模式**，
直接复制 .sqlite3 文件可能拿不到 -wal 里尚未 checkpoint 的数据，备份会缺最新写入。
"""
import argparse
import os
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3')

# 旧值 → 规范值（只做改名，不做重新判定）
RENAME = {
    '家具家居': '家具',
    '汽配': '机械零部件',
}


def connect_ro():
    conn = sqlite3.connect('file:%s?mode=ro' % DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def stats(conn):
    """行业 → 条数分布。
    ⚠️ 刻意用**下标**取值而不是 `r['industry']` —— 本函数会被两种连接调用：
       只读连接（`connect_ro()`，设了 row_factory）和写库连接（裸 `sqlite3.connect`）。
       依赖 row_factory 的话，写库那条路会在**改完数据之后**抛 TypeError，
       让脚本看起来「失败」，其实数据已经写进去了（2026-10-02 在 标注空行业.py 上实测踩到，同源。）"""
    return {r[0] or '': r[1] for r in conn.execute(
        "SELECT industry, COUNT(*) AS n FROM customers GROUP BY industry")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true',
                    help='真正写库（默认只报告）。写前自动做一致性备份。')
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print('找不到客户库：', DB_PATH)
        return 1

    conn = connect_ro()
    before = stats(conn)
    plan = []          # [(old, new, [ids...])]
    for old, new in RENAME.items():
        ids = [r['id'] for r in conn.execute(
            'SELECT id FROM customers WHERE industry = ?', (old,))]
        if ids:
            plan.append((old, new, ids))
    total = sum(len(ids) for _, _, ids in plan)

    print('=== 当前 industry 分布 ===')
    for k, v in sorted(before.items(), key=lambda x: -x[1]):
        print('  %-10s %d' % (k or '(空)', v))
    print()
    print('=== 计划改名（纯改名，不重新判定）===')
    if not plan:
        print('  没有需要改名的记录。')
    for old, new, ids in plan:
        print('  %-6s → %-6s  %d 条   id: %s%s' % (
            old, new, len(ids),
            ', '.join(str(i) for i in ids[:12]),
            ' …' if len(ids) > 12 else ''))
    print('  合计 %d 条' % total)

    if not args.apply:
        print('\n--dry-run 结束（未写库）。确认无误后加 --apply 执行。')
        conn.close()
        return 0

    if not total:
        conn.close()
        return 0

    # ---- 一致性备份（WAL 安全）----
    ts = time.strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(BASE_DIR, 'DB', '客户库.sqlite3.bak_%s' % ts)
    conn.close()
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(bak)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    print('\n已备份:', bak, os.path.getsize(bak), '字节')

    # ---- 写库 ----
    conn = sqlite3.connect(DB_PATH)
    for old, new, ids in plan:
        conn.executemany('UPDATE customers SET industry = ? WHERE id = ?',
                         [(new, i) for i in ids])
    conn.commit()
    after = stats(conn)
    conn.close()

    print('\n=== 改后 industry 分布 ===')
    for k, v in sorted(after.items(), key=lambda x: -x[1]):
        print('  %-10s %d' % (k or '(空)', v))
    print('\n✅ 已重标 %d 条。' % total)
    print('⚠️ 飞书「行业」字段的选项需人工同步（代码里没有选项映射表）：')
    print('   新增「塑料包装袋」、把「家具家居」改为「家具」、「汽配」改为「机械零部件」。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
