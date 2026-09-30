# -*- coding: utf-8 -*-
"""行业判定规则回归：真假阳性用例 + 与「改前规则快照」的逐条 diff（只读）。

为什么需要逐条 diff：`回填行业.py --dry-run` 只打印条数（「写入行业 N 条」），
规则误伤时条数可能仍然对得上，看不出是哪几家被改了行业。本脚本把 221 条客户
逐条跑一遍新规则，与 `.workbuddy/_industry_pred_before.json`（改前快照）比对。

用法：
    D:\\waimao\\dp\\.venv\\Scripts\\python.exe .workbuddy\\_check_industry_rules.py
"""
import importlib.util
import io
import json
import os
import sqlite3
import sys

ROOT = r'D:\waimao\dp'
DB = os.path.join(ROOT, 'DB', '客户库.sqlite3')
BEFORE = os.path.join(ROOT, '.workbuddy', '_industry_pred_before.json')
CUR = os.path.join(ROOT, '回填行业.py')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


m = load('bfcur', CUR)
g = m.guess_industry

fails = []

# ========== A. 必须被挡住（这些误判代价高，必须整词匹配） ==========
MUST_BLOCK = [
    # '^engine' —— engineering 是巨量误判源
    ('Engineering Consultancy Group', '机械零部件'),
    ('engineering-services.com', '机械零部件'),
    # 裸 'cat' 会命中 catalog / category 和 URL 里的 /cat/ 路径段（电商站几乎必有）
    ('catalog printing co', '宠物用品'),
    ('category management ltd', '宠物用品'),
    ('hubblewholesale.direct/cat/sports-outdoors/', '宠物用品'),
    ('Cats Eye Sunglasses', '宠物用品'),          # elle.com 的墨镜页，改前被裸 'cats' 误判过
    # 塑料包装袋侧的短词歧义
    ('Baggage Handling Co', '塑料包装袋'),
    ('Rucksack Trekking Gear', '塑料包装袋'),
    ('Airline Liner Services', '塑料包装袋'),
    ('Polyester Fabrics Ltd', '塑料包装袋'),
    ('bagel-shop.com', '塑料包装袋'),
    ('robusta-coffee.com', '塑料包装袋'),          # 会被裸 'busta' 命中
    ('harvest bags ltd', '塑料包装袋'),            # 会被裸 'vest bag' 命中
    ('type bags wholesale', '塑料包装袋'),         # 会被裸 'pe bag' 命中
    ('Dust Filter Systems Inc', '塑料包装袋'),     # 除尘滤袋，用户明确要避开
]
print('=== A. 必须被挡住（改前裸子串会误判）===')
for t, forbidden in MUST_BLOCK:
    r = g(t, '')
    ok = r != forbidden
    if not ok:
        fails.append(f'A 误判：{t} → {r}（不该判成 {forbidden}）')
    print('  %-40s → %-6s %s' % (t, r or '(空)', '✅' if ok else f'❌ 不该是 {forbidden}'))

# ========== A2. 已知取舍（**不判失败**，只记录，行为变了要人工复查） ==========
# 这些词收紧成整词会把真客户漏掉（产品词常落在域名词尾：chongjiapet.com / dreambed.com），
# 所以刻意保留裸子串，代价就是下面这些罕见解会被误判。属于有意为之，不是疏忽。
ACCEPTED_FP = ['Carpet World Trading', 'carpetworld.com', 'Petroleum Logistics Ltd',
               'mycompetitor.com', 'Embedded Systems Inc', 'bedrock-solutions.com',
               'Chairman Office Supplies']
print('\n=== A2. 已知取舍（接受误判，换取不漏真客户；仅记录）===')
for t in ACCEPTED_FP:
    print('  %-40s → %s' % (t, g(t, '') or '(空)'))

# ========== B. 既有行为回归 ==========
print('\n=== B. 既有行业必须仍能命中 ===')
POS = [
    ('Pet Supplies Direct', '宠物用品'), ('catlitter.com', '宠物用品'),
    ('Katzentoilette Shop', '宠物用品'), ('petshop24.de', '宠物用品'),
    ('Sofa Warehouse', '家具'), ('Modern Furniture Ltd', '家具'),
    ('jnmfurniture.com', '家具'), ('zuomod.com', '家具'),
    ('Auto Parts Depot', '机械零部件'), ('durango-parts.com', '机械零部件'),
    ('CNC Machining Co', '机械零部件'), ('autoparts-wholesale.com', '机械零部件'),
]
for t, exp in POS:
    r = g(t, '')
    ok = r == exp
    if not ok:
        fails.append(f'B 漏判：{t} → {r or "(空)"}，期望 {exp}')
    print('  %-34s → %-6s %s' % (t, r or '(空)', '✅' if ok else '❌ 期望 ' + exp))

# ========== C. 新增：塑料包装袋（公司名 + 域名连写 + 多语言） ==========
print('\n=== C. 新增「塑料包装袋」===')
BAGS = ['Trash Bag Wholesale', 'trashbags.com', 'garbagebags.com', 'Garbage Bag Importer',
        'drawstringbag.com', 'Zip Lock Bags Ltd', 'ziplock-pouch.com', 'Compostable Bag Supplier',
        'compostablebags.eu', 'Bin Liner UK Ltd', 'binliners.co.uk', 'Poop Bag Direct',
        '深圳垃圾袋厂', '塑料包装袋贸易', 'Müllbeutel Handel GmbH', 'sac poubelle gros',
        'bolsa de basura mayorista', 'Shopper Bag Italia', 'vuilniszak groothandel',
        'çöp poşeti toptan', 'polybagfactory.com', 'wicketbags.co.uk']
for t in BAGS:
    r = g(t, '')
    ok = r == '塑料包装袋'
    if not ok:
        fails.append(f'C 漏判：{t} → {r or "(空)"}，期望 塑料包装袋')
    print('  %-34s → %-6s %s' % (t, r or '(空)', '✅' if ok else '❌ 期望 塑料包装袋'))

# ========== D. 与改前快照逐条 diff ==========
print('\n=== D. 221 条客户逐条 diff（改前 vs 改后）===')
if not os.path.exists(BEFORE):
    print('  ⚠️ 缺少改前快照，跳过（不静默放过）')
    fails.append('缺少 _industry_pred_before.json')
else:
    before = {x['id']: x for x in json.loads(io.open(BEFORE, 'rb').read().decode('utf-8'))}
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('SELECT id, company_name, website, industry FROM customers')]
    conn.close()
    changed = []
    for r in rows:
        b = before.get(r['id'], {}).get('guess_before', '')
        a = g(r['company_name'], r['website'])
        if a != b:
            changed.append((r['id'], r['company_name'], r['website'], b, a))
    print('  改前 guess 分布:', dict(sorted(
        __import__('collections').Counter(x['guess_before'] or '(空)' for x in before.values()).items())))
    print('  改后 guess 分布:', dict(sorted(__import__('collections').Counter(
        g(r['company_name'], r['website']) or '(空)' for r in rows).items())))
    print('  预测结果发生变化的条数:', len(changed))
    for cid, name, web, b, a in changed:
        print('    id=%-4s %-34s %-30s %s → %s' % (cid, (name or '')[:34], (web or '')[:30],
                                                   b or '(空)', a or '(空)'))
    # 允许的变化：只是 3 个行业改名 + 原空白记录补上「塑料包装袋」+ 裸子串误判被修掉
    ALLOWED_RENAME = {('家具家居', '家具'), ('汽配', '机械零部件')}
    unexpected = [c for c in changed
                  if (c[3], c[4]) not in ALLOWED_RENAME
                  and not (c[3] == '' and c[4] == '塑料包装袋')
                  and not (c[3] == '' and c[4] == '')
                  and c[4] != '']
    hard = [c for c in changed if c[4] == '' and c[3] != '']
    if hard:
        print('\n  ⚠️ 有记录从「有行业」变成「判不出」—— 通常是裸子串改整词造成的漏判：')
        for c in hard:
            print('    ', c)
    if unexpected:
        print('\n  ⚠️ 预期之外的变化（可能误伤，请人工确认）：')
        for c in unexpected:
            print('    ', c)
    else:
        print('\n  ✅ 变化全部落在预期内（改名 / 原空白补上塑料包装袋）')

print()
if fails:
    print('❌ 用例失败 %d 条：' % len(fails))
    for f in fails:
        print('   -', f)
    sys.exit(1)
print('✅ 行业判定规则用例全部通过')
