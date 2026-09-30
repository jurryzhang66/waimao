# -*- coding: utf-8 -*-
"""
行业回填工具：按公司名/官网关键词判断所属行业，回填到
  1) 本地 SQLite 客户库的 industry 列
  2) 飞书「客户信息」表的「行业」单选字段
识别不出的记录保持空白，留待人工标注。

用法：
  python 回填行业.py                 # 回填本地库 + 飞书
  python 回填行业.py --db-only       # 只回填本地库
  python 回填行业.py --feishu-only   # 只回填飞书
  python 回填行业.py --dry-run       # 只预演，不写入
  python 回填行业.py --overwrite     # 覆盖已有行业值（默认只在空值时写入）
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlparse

# ================= 飞书配置 =================
BASE_TOKEN = 'ZhSSb18BMajKR7sacxTcCFY0njf'
TABLE_ID = 'tblY38YnVIQ5AYYA'
LARK_CLI = r'C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe'
TMP_JSON = 'DB/_industry_update.json'

DB_DIR = 'DB'
DB_FILE = '客户库.sqlite3'
FIELD = '行业'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 行业判定规则 =================
# 自上而下匹配，先命中先算；匹配对象 = 公司名 + 官网域名。
#
# ⚠️ 行业名必须与「关键词库.json」的顶层键**逐字一致**（现在 8 个）：
#      宠物用品 / LED照明 / 家具 / 服装 / 机械零部件 / 户外用品 / 食品 / 塑料包装袋
#    否则客户库 industry 列、飞书「行业」单选字段、关键词库三处对不上，筛选会静默漏数据。
#    历史遗留：本文件曾用「家具家居」「汽配」，本次已统一为「家具」「机械零部件」。
#
# ⚠️ 关键词的两种写法（见 _compile_kw）——这是本次唯一的匹配语义变更：
#    · 普通写法  = **裸子串**。能吃域名的连写与中缀：'litter' 命中 catlitter、
#                  'furniture' 命中 wholesalefurniture、'pet' 命中 chongjiapet。
#    · '^' 开头  = **整词**（左边界 + 右边界，右边允许 s/es 复数），只用在「误判代价高、
#                  且几乎不会出现在域名词尾」的词上：'^engine' 不命中 engineering、
#                  '^pe bag' 不命中 type bags、'^vest bag' 不命中 harvest bags、
#                  '^busta' 不命中 robusta、'^bin liner' 不命中 cabin liner。
# ⚠️ 为什么 'pet' / 'bed' / 'chair' 仍用裸子串：产品词经常就落在域名词尾
#    （chongjiapet.com / dreambed.com / diningchair.com），收紧成整词会把**真客户漏掉**。
#    代价是 carpet / petroleum / embedded / chairman 会被误判 —— 这是**已知取舍**，不是疏忽。
# ⚠️ 但 'cat' 恰恰不能裸用：裸 'cat' 会命中 catalog / category，以及 URL 里的 `/cat/` 路径段
#    （电商站几乎必有 /category/），后果严重。故改用更具体的 'cat litter' + 'catlitter'。
INDUSTRY_RULES = [
    ('宠物用品', ['litter', 'cat litter', 'catlitter', 'kitten', 'meow', 'paw', 'pet',
                  'litiere', 'katze', 'katzentoilette', 'arenero', 'петл', '宠物']),
    ('家具', ['sofa', 'furniture', 'dining table', 'mattress', 'bed', 'chair', 'zuomod',
              'interior', 'home decor', 'linens', 'wholesale interiors', 'jnmfurniture',
              'pfcind', 'novafurniture', 'knoxbeds', 'furnituredistributors', 'sheesham']),
    ('机械零部件', ['auto part', 'autopart', 'automotive', 'auto body', 'ignition', '^engine',
                    'vehicle', 'car part', 'truck', 'durango', 'dodge', 'chindernetz',
                    'bearing', 'cnc', 'machining', 'machined', 'mechanical part',
                    'spare part', 'mechanical component']),
    # ⚠️ 塑料包装袋必须放**末位**：guess_industry 自上而下先命中先算，放末位可保证
    #    「宠物用品 / 家具 / 机械零部件」的既有判定一条都不变，只影响原本判空的记录。
    # 多词短语一律给两个写法：带空格的（命中公司名）+ 连写的（命中域名）。
    ('塑料包装袋', ['trash bag', 'trashbag', 'garbage bag', 'garbagebag',
                    'waste bag', 'wastebag', 'refuse sack', 'refusesack',
                    'rubbish bag', 'rubbishbag', '^bin liner', 'binliner',
                    '^bin bag', 'binbag', 'carrier bag', 'carrierbag',
                    'shopping bag', 'shoppingbag', 'plastic bag', 'plasticbag',
                    'poly bag', 'polybag', 'polythene bag', 'hdpe bag', 'ldpe bag', '^pe bag',
                    '^t shirt bag', 'tshirtbag', '^vest bag', 'vestbag',
                    'die cut bag', 'diecutbag', 'handle bag', 'handlebag',
                    'wicket bag', 'wicketbag', 'ziplock', '^zip lock',
                    'zipper bag', 'zipperbag', 'slider bag', 'sliderbag',
                    'resealable bag', 'self seal bag', 'selfsealbag',
                    'drawstring bag', 'drawstringbag', 'c fold bag', 'cfoldbag',
                    'compostable bag', 'compostablebag', 'biodegradable bag', 'biodegradablebag',
                    'compost bag', 'compostbag', 'pallet cover', 'palletcover',
                    'dust cover bag', 'dustcoverbag', 'litter bag', 'litterbag',
                    'poop bag', 'poopbag',
                    '塑料袋', '垃圾袋', '包装袋',
                    'müllbeutel', 'müllsack', '^beutel', 'folienbeutel', 'tragetasche',
                    'sac poubelle', 'sac plastique', 'sac de courses',
                    'bolsa de basura', 'bolsa de plástico', 'bolsa camiseta',
                    'sacchetto', '^busta', '^shopper',
                    'vuilniszak', 'plastic zak',
                    'poşet', 'çöp poşeti', 'naylon poşet',
                    'أكياس القمامة', 'كيس', 'کیسه', 'نایلون']),
]

# 归一化：小写 + 非字母数字一律转空格（连字符/点/斜杠/下划线都变空格，
# 于是 'c-fold'→'c fold'、'wholesale-interiors'→'wholesale interiors'）。
# 保留带音标的拉丁字母 / 西里尔 / 阿拉伯 / CJK，否则 'müllbeutel'、'петл'、'垃圾袋' 会被打散。
_NORM = re.compile(r'[^0-9a-z\u00c0-\u024f\u0400-\u04ff\u0590-\u06ff\u4e00-\u9fff]+')


def _compile_kw(kw):
    """'^' 开头 = 整词匹配（含 s/es 复数）；否则裸子串匹配。"""
    if kw.startswith('^'):
        return re.compile(r'(?<![0-9a-z])' + re.escape(kw[1:]) + r'(?:s|es)?(?![0-9a-z])')
    return re.compile(re.escape(kw))


_KW_PATTERNS = [(name, [_compile_kw(kw) for kw in kws]) for name, kws in INDUSTRY_RULES]


def guess_industry(*texts):
    """按关键词判断行业；判断不出返回空字符串。

    ⚠️ '^' 开头的关键词走整词匹配，普通关键词走裸子串（见 _compile_kw 的说明）——
    不能一律用裸子串：'pet' 会命中 carpet/petroleum、'bed' 会命中 embedded，
    把无关公司**静默**标错行业且不报错。
    """
    txt = _NORM.sub(' ', ' '.join(t for t in texts if t).lower())
    for name, pats in _KW_PATTERNS:
        if any(p.search(txt) for p in pats):
            return name
    return ''


def db_path():
    return os.path.join(BASE_DIR, DB_DIR, DB_FILE)


def run_lark(args):
    env = os.environ.copy()
    env.pop('HERMES_HOME', None)
    r = subprocess.run([LARK_CLI] + args, env=env, capture_output=True, cwd=BASE_DIR)
    out = ''
    for raw in (r.stdout, r.stderr):
        if raw:
            for enc in ('utf-8', 'gbk'):
                try:
                    out += raw.decode(enc)
                    break
                except Exception:
                    continue
    try:
        data = json.loads(r.stdout.decode('utf-8'))
        return bool(data.get('ok')), data, out
    except Exception:
        return False, {}, out


def norm_domain(url):
    raw = (url or '').strip().lower()
    if not raw:
        return ''
    m = re.search(r'href="([^"]+)"', raw)
    if m:
        raw = m.group(1)
    raw = raw.strip('[]()')
    try:
        return urlparse(raw if '://' in raw else 'https://' + raw).netloc.split(':', 1)[0].removeprefix('www.')
    except Exception:
        return ''


def backfill_db(dry_run=False, overwrite=False):
    """给本地库补 industry 列并回填"""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    cols = [d[1] for d in conn.execute('PRAGMA table_info(customers)')]
    has_col = 'industry' in cols
    if not has_col:
        if dry_run:
            print('[dry-run] 将新增列: industry')
        else:
            conn.execute("ALTER TABLE customers ADD COLUMN industry TEXT DEFAULT ''")
            conn.commit()
            has_col = True
            print('已新增 customers.industry 列')

    sel = 'SELECT id, company_name, website, industry FROM customers' if has_col \
        else 'SELECT id, company_name, website, \'\' AS industry FROM customers'
    rows = [dict(r) for r in conn.execute(sel)]
    updated, blank = 0, 0
    for r in rows:
        if not overwrite and (r['industry'] or '').strip():
            continue
        ind = guess_industry(r['company_name'], r['website'])
        if not ind:
            blank += 1
            continue
        if dry_run:
            updated += 1
            continue
        conn.execute('UPDATE customers SET industry=? WHERE id=?', (ind, r['id']))
        updated += 1
    if not dry_run:
        conn.commit()
    conn.close()
    print('【本地库】共 %d 条，写入行业 %d 条，无法识别留空 %d 条' % (len(rows), updated, blank))


def fetch_feishu_records():
    """返回 [(record_id, 公司名称, 官网, 现有行业), ...]"""
    out_rows, offset = [], 0
    while True:
        ok, data, out = run_lark(['base', '+record-list', '--base-token', BASE_TOKEN,
                                  '--table-id', TABLE_ID, '--limit', '200',
                                  '--offset', str(offset), '--format', 'json', '--as', 'user'])
        if not ok:
            raise RuntimeError('读取飞书记录失败：' + out[:400])
        d = data.get('data', {})
        cols = d.get('fields', [])
        rows = d.get('data', [])
        ids = d.get('record_id_list', [])
        i_name, i_url = cols.index('公司名称'), cols.index('官网')
        i_ind = cols.index(FIELD) if FIELD in cols else -1
        for i, r in enumerate(rows):
            cur = ''
            if i_ind >= 0 and r[i_ind]:
                v = r[i_ind]
                cur = v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else '')
            out_rows.append((ids[i], r[i_name], r[i_url], cur))
        if not d.get('has_more') or not rows:
            break
        offset += len(rows)
    return out_rows


def backfill_feishu(dry_run=False, overwrite=False):
    records = fetch_feishu_records()
    updates, blank = {}, 0
    for rid, name, url, cur in records:
        if not overwrite and cur:
            continue
        ind = guess_industry(name, url)
        if not ind:
            blank += 1
            continue
        updates[rid] = {FIELD: [ind]}
    print('【飞书】共 %d 条，待写入行业 %d 条，无法识别留空 %d 条' % (len(records), len(updates), blank))
    if not updates:
        return
    if dry_run:
        print('[dry-run] 示例:', json.dumps(dict(list(updates.items())[:3]), ensure_ascii=False))
        return

    ids = list(updates)
    total_ok = 0
    for i in range(0, len(ids), 200):          # 单次上限 200 条
        chunk = {rid: updates[rid] for rid in ids[i:i + 200]}
        tmp = os.path.join(BASE_DIR, TMP_JSON)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'update_records': chunk}, f, ensure_ascii=False)
        ok, data, out = run_lark(['base', '+record-batch-update', '--base-token', BASE_TOKEN,
                                  '--table-id', TABLE_ID, '--json', '@' + TMP_JSON, '--as', 'user'])
        if ok:
            total_ok += len(chunk)
            print('  已更新 %d 条' % len(chunk))
        else:
            print('  ❌ 本批失败：' + out[:400])
    print('【飞书】共成功写入 %d 条' % total_ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--db-only', action='store_true')
    ap.add_argument('--feishu-only', action='store_true')
    ap.add_argument('--overwrite', action='store_true', help='覆盖已有行业值')
    args = ap.parse_args()

    if not args.feishu_only:
        backfill_db(args.dry_run, args.overwrite)
    if not args.db_only:
        backfill_feishu(args.dry_run, args.overwrite)


if __name__ == '__main__':
    main()
