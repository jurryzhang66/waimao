# -*- coding: utf-8 -*-
"""真实客户库的不变量体检：去重键必须和网址一致。

守的这条不变量：
    customers.website_key == normalize_domain(customers.website)

为什么它值得单独一个回归项（2026-09-30 的实测事故）：
  · `db_has_customer()`（判断「这条要不要跳过」）**只**按 website_key 查；
  · `db_upsert_customer()`（写入）是「先按键查、查不到再按 email 兜底合并」——
    两条口径本来就不完全一致；
  · 于是一旦某行的键和网址错位（典型成因：两家站共用邮箱，合并后网址被改成新站、
    键却留在旧站域名上），那个网址就被**永久**判成「新客户」：每采一次就往结果 Excel
    多写一行，而库里始终只有一条。
  · 实测：`megazone.mx` 一份表里出现 3 次、另一份出现 2 次，库里只有 1 条
    （id=267 键是 megafood.mx、网址是 megazone.mx）。

⚠️ 这是**唯一**一个刻意不把 db_path 打进临时目录的回归项 —— 它检的就是真实库的存量数据。
   所以它全程 apply=False（纯只读），只诊断不修。真发现问题时人工跑一次：
       python -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('kf',r'D:\\waimao\\dp\\客户开发工具.py'); m=importlib.util.module_from_spec(s); sys.modules['kf']=m; s.loader.exec_module(m); print(m.db_fix_website_keys(apply=True))"

用法：python .workbuddy\\_check_db_keys.py
"""
import importlib.util
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SRC = r'D:\waimao\dp\客户开发工具.py'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

fails = []


def check(cond, desc, extra=''):
    if cond:
        print(f'  ✓ {desc}')
    else:
        fails.append(desc)
        print(f'  ✗ {desc}' + (f'   ← {extra}' if extra else ''))


# ---------- A. 先确认这次真的连在真实库上（别把打桩的临时库当成真实库检） ----------
# 这个脚本不设任何打桩，所以 db_path() 必须落在项目的 DB/ 下、且不在系统临时目录里。
db = m.db_path()
print('A. 目标库')
print('   ', db)
check(os.path.exists(db), '客户库文件存在', db)
check(os.path.basename(os.path.dirname(db)) == 'DB',
      'db_path() 指向项目 DB/ 目录（没被临时目录打桩）', db)
check(os.path.realpath(db) == os.path.realpath(r'D:\waimao\dp\DB\客户库.sqlite3'),
      '指向的就是那个真实客户库', db)

# ---------- B. 去重键规范化本身的样例（函数写坏了这条不变量也守不住） ----------
print('\nB. normalize_domain 样例')
nd = m.normalize_domain
cases = [
    ('https://www.Example.COM/a/b?x=1', 'example.com', '去 www、降大小写、丢路径与查询串'),
    ('HTTP://Shop.Foo.CN:8080/p', 'shop.foo.cn', '丢端口'),
    ('example.com', 'example.com', '裸域名补 https 后取主机名'),
    ('https://maps.google.com/maps/place/X/data=!3m1!4b1!4m5!3m4!1s0x1:0x2', 'maps:0x1:0x2',
     '谷歌地图 place → 合成键（netloc 全是 google.com，必须另起键）'),
    ('someone@example.com', '', '纯邮箱不给键（否则会和真站点撞车）'),
    ('', '', '空串给空键'),
]
for raw, want, why in cases:
    got = nd(raw)
    check(got == want, f'{why}', f'{raw!r} → {got!r}（期望 {want!r}）')

# ---------- C. 核心不变量：全库没有一条键错位 ----------
print('\nC. 全库 website_key == normalize_domain(website)')
fixed, conflict = m.db_fix_website_keys(apply=False)
for i, old, new, site in fixed:
    print(f'   ✗ 可自动修正：id={i} 键={old!r} → 应为 {new!r}（网址 {site}）')
for i, old, new, other in conflict:
    print(f'   ✗ 键冲突：id={i} 键={old!r} → 想改成 {new!r} 但已被 id={other} 占用')
check(not fixed, f'没有「键与网址对不上」的行（发现 {len(fixed)} 条）', str(fixed))
check(not conflict, f'没有「目标键已被别的行占用」的行（发现 {len(conflict)} 条）', str(conflict))

# ---------- D. 上下文：条数分布（顺带让人看见库有没有被测试数据污染） ----------
print('\nD. 库概览')
st = m.db_stats()
print(f'   总条数 {st["total"]}，其中有评分 {st["verified"]}')
c = m.db_connect()
try:
    dist = list(c.execute('SELECT source, COUNT(*) n FROM customers GROUP BY source ORDER BY n DESC'))
    tot = 0
    for src, n in dist:
        tot += n
        print(f'   {src or "(空)":<12} {n:>5}')
    check(tot == st['total'], '按来源分组求和 = 总条数', f'{tot} vs {st["total"]}')
finally:
    c.close()

# ---------- E. 汇总 ----------
print('\n' + '=' * 62)
if fails:
    print(f'❌ 未通过 {len(fails)} 项：')
    for d in fails:
        print('   ·', d)
    print('\n修复办法：跑一次 db_fix_website_keys(apply=True)（先备份），然后重跑本项。')
    sys.exit(1)
print('✅ 真实库去重键一致性检查全部通过')
