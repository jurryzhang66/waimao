# -*- coding: utf-8 -*-
"""打桩冒烟：`标注空行业.py`（把「行业为空」的客户批量写成指定行业）。

为什么单独给它写测试：它**默认 dry-run 但不代表写库那条路没被跑过** —— 2026-10-02 首次
在真实库上 `--apply` 时，写库后的统计 `stats()` 用了裸 `sqlite3.connect`（没设 row_factory）
却在按列名取值 → 抛 TypeError。**数据其实已经写进去了**，但脚本对外表现成「失败」，
非常容易让人以为没生效、或者反过来以为要重跑一次。
→ 本脚本就是钉住这条：`--apply` 必须走完、退出码 0、分布重新打印、备份落临时目录。

覆盖：
  ① 打桩护栏（库与备份都被关进临时目录，绝不碰真实 DB/客户库.sqlite3）
  ② 默认 dry-run：只报告、不写库、退出码 0
  ③ `--apply`：空行业 → 指定行业；已有行业的记录**一个都不许动**
  ④ 备份：落临时目录、非空、用 sqlite 在线 backup（WAL 安全）
  ⑤ `--industry` 换目标行业名
  ⑥ `--exclude-id` 挑掉几条 / 非法值要报错退出
  ⑦ 口径：纯空白的行业列（`'   '`）也算「空」，会被标注
  ⑧ 幂等：再跑一次 `--apply` 无事可做，退出码 0 且不产生新备份

用法：python .workbuddy\\_smoke_annotate.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'D:\waimao\dp'
SCANNER = os.path.join(ROOT, '标注空行业.py')

# 先把 core 拉起来（只为了用 core.db 建一个**结构一致**的临时库，避免手抄 schema 漂移）
sys.path.insert(0, ROOT)
import core.db as db                                          # noqa: E402

TMP = tempfile.mkdtemp(prefix='smoke_annotate_')
TMP_DB_DIR = os.path.join(TMP, 'DB')
os.makedirs(TMP_DB_DIR, exist_ok=True)
TMP_DB = os.path.join(TMP_DB_DIR, '客户库.sqlite3')

db.db_path = lambda: TMP_DB
db.paths.ENRICH_FILE = os.path.join(TMP, '__no_such_enrich__.xlsx')

_ok, _fail = 0, []


def check(cond, desc, extra=''):
    global _ok
    if cond:
        _ok += 1
        print(f'  ✅ {desc}')
    else:
        _fail.append(desc)
        print(f'  ❌ {desc}' + (f'   ← {extra}' if extra else ''))


def section(title):
    print(f'\n================ {title} ================')


def _under_tmp(p):
    return os.path.commonpath([os.path.realpath(p),
                               os.path.realpath(TMP)]) == os.path.realpath(TMP)


def blank_count():
    conn = sqlite3.connect(TMP_DB)
    n = conn.execute("SELECT COUNT(*) FROM customers WHERE IFNULL(TRIM(industry),'')=''").fetchone()[0]
    conn.close()
    return n


def industry_of(cid):
    conn = sqlite3.connect(TMP_DB)
    v = conn.execute('SELECT industry FROM customers WHERE id=?', (cid,)).fetchone()
    conn.close()
    return None if v is None else v[0]


SAMPLES = [
    dict(company_name='Blank A', website='https://blank-a.com', email='', phone='',
         contact_url='', country='墨西哥', industry='', score=10, rating='', source='手动采集'),
    dict(company_name='Blank B', website='https://blank-b.com', email='', phone='',
         contact_url='', country='墨西哥', industry='   ', score=10, rating='', source='手动采集'),
    dict(company_name='Has Industry', website='https://has-ind.com', email='', phone='',
         contact_url='', country='德国', industry='宠物用品', score=80, rating='重点客户',
         source='谷歌搜索'),
    dict(company_name='Furniture Old', website='https://furn-old.mx', email='', phone='',
         contact_url='', country='墨西哥', industry='家具家居', score=20, rating='观察',
         source='谷歌搜索'),
]


def seed():
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)
    for sfx in ('-wal', '-shm'):
        if os.path.exists(TMP_DB + sfx):
            os.remove(TMP_DB + sfx)
    db.init_customer_db()
    for s in SAMPLES:
        db.db_upsert_customer(s)
    ids = {}
    conn = sqlite3.connect(TMP_DB)
    for cid, name in conn.execute('SELECT id, company_name FROM customers'):
        ids[name] = cid
    conn.close()
    return ids


def load_scanner():
    """每次都重新加载：脚本模块里的 BASE_DIR / DB_PATH 是模块级常量，必须改成临时目录，
    否则 `--apply` 会**直接写真实客户库**、备份也落真实 DB/。"""
    spec = importlib.util.spec_from_file_location('annotate_scanner', SCANNER)
    s = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s)
    s.BASE_DIR = TMP
    s.DB_PATH = TMP_DB
    return s


def run(argv):
    s = load_scanner()
    old_argv = sys.argv
    sys.argv = ['标注空行业.py'] + argv
    try:
        return s.main()
    finally:
        sys.argv = old_argv


section('① 打桩护栏')
check(_under_tmp(TMP_DB), '临时库在临时目录里')
ids = seed()
check(blank_count() == 2, f'播种 4 条（2 条行业为空、1 条宠物用品、1 条家具家居）：空={blank_count()}')
s0 = load_scanner()
check(_under_tmp(s0.DB_PATH) and _under_tmp(s0.BASE_DIR),
      '标注空行业.py 的 DB_PATH / BASE_DIR 都已指向临时目录（否则会写真实库）')
check(os.path.exists(os.path.join(ROOT, 'DB', '客户库.sqlite3')),
      '真实客户库仍在原位（本测试没动它）')

section('② 默认 dry-run：只报告，不写库')
baks_before = set(os.listdir(TMP_DB_DIR))
rc = run([])
check(rc == 0, f'dry-run 退出码 0（实际 {rc}）')
check(blank_count() == 2, 'dry-run 一行都没改')
check(industry_of(ids['Blank A']) == '', 'dry-run 后 Blank A 的行业仍是空')
check(set(os.listdir(TMP_DB_DIR)) == baks_before, 'dry-run 不产生备份文件')

section('③ --apply（这就是那个「写完之后才抛 TypeError」的回归）')
rc = run(['--apply'])
check(rc == 0, f'--apply 退出码 0 —— 写库后的统计不再因 row_factory 崩（实际 {rc}）')
check(blank_count() == 0, f'行业为空清零（实际 {blank_count()}）')
check(industry_of(ids['Blank A']) == '食品', 'Blank A → 食品')
check(industry_of(ids['Blank B']) == '食品', 'Blank B（行业列是纯空白）→ 食品（TRIM 口径生效）')
check(industry_of(ids['Has Industry']) == '宠物用品',
      '已有行业「宠物用品」没被改（只填空值）')
check(industry_of(ids['Furniture Old']) == '家具家居',
      '历史行业名「家具家居」没被改（改名是 重标行业.py 的事）')

section('④ 备份')
baks = [f for f in os.listdir(TMP_DB_DIR) if f not in baks_before]
check(len(baks) == 1, f'--apply 恰好产生 1 份备份：{baks}')
check(all(f.startswith('客户库.sqlite3.bak_标注空行业_') for f in baks), '备份命名带脚本标识与时间戳')
_bp = os.path.join(TMP_DB_DIR, baks[0]) if baks else ''
check(_bp and os.path.getsize(_bp) > 0, f'备份非空：{os.path.getsize(_bp) if _bp else "-"} 字节')
check(_under_tmp(_bp), '备份落在临时目录（没往真实 DB/ 塞垃圾）')
_bc = sqlite3.connect(_bp) if _bp else None
if _bc:
    _n = _bc.execute("SELECT COUNT(*) FROM customers WHERE IFNULL(TRIM(industry),'')=''").fetchone()[0]
    _bc.close()
    check(_n == 2, f'备份是「改之前」的快照（里面仍有 2 条行业为空，实际 {_n}）')

section('⑤ --industry 换目标行业名')
seed()
rc = run(['--apply', '--industry', '机械零部件'])
check(rc == 0 and industry_of(ids['Blank A']) == '机械零部件',
      f'--industry 机械零部件 生效（rc={rc}，值={industry_of(ids["Blank A"])!r}）')
check(industry_of(ids['Blank B']) == '机械零部件', '纯空白那条也跟着标')

section('⑥ --exclude-id')
seed()
rc = run(['--apply', '--exclude-id', '%d, %d' % (ids['Blank A'], ids['Blank B'])])
check(rc == 0, f'--exclude-id 正常返回 0（实际 {rc}）')
check(blank_count() == 2, '两条都被挑掉，什么都没标')
rc2 = run(['--apply', '--exclude-id', 'abc'])
check(rc2 == 1, f'--exclude-id 里有非数字 → 退出码 1（实际 {rc2}）')
check(blank_count() == 2, '参数报错时不动数据')
rc3 = run(['--apply', '--industry', '   '])
check(rc3 == 1, f'--industry 是空串 → 退出码 1（实际 {rc3}）')
check(blank_count() == 2, '目标行业为空时不动数据')

section('⑦ 只挑一部分')
seed()
rc = run(['--apply', '--exclude-id', str(ids['Blank B'])])
check(rc == 0 and industry_of(ids['Blank A']) == '食品',
      f'没被排除的那条标上了（A={industry_of(ids["Blank A"])!r}）')
check((industry_of(ids['Blank B']) or '').strip() == '',
      f'被排除的那条**原样没动**（B={industry_of(ids["Blank B"])!r} —— 连那串空格都留着）')

section('⑧ 幂等：没有可标的了就无事可做')
seed()
run(['--apply'])                                   # 先真的标干净（两条都是空行业）
check(blank_count() == 0, '前置：这一次已把空行业标完')
for f in os.listdir(TMP_DB_DIR):                   # 清掉已有备份，否则同名（秒级时间戳）会撞车
    if f.startswith('客户库.sqlite3.bak_'):
        os.remove(os.path.join(TMP_DB_DIR, f))
rc = run(['--apply'])
check(rc == 0, f'再跑一次退出码 0（实际 {rc}）')
check(blank_count() == 0, '仍然没有「行业为空」的记录')
check(not [f for f in os.listdir(TMP_DB_DIR) if f.startswith('客户库.sqlite3.bak_')],
      '无事可做时不产生新备份（不会白写库、也不会白备份）')

print('\n' + '=' * 62)
print(f'通过 {_ok} 项' + (f'，失败 {len(_fail)} 项：' if _fail else '，全部通过 ✅'))
for d in _fail:
    print('   ❌', d)
print('临时目录：', TMP)
sys.exit(1 if _fail else 0)
