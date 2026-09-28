# -*- coding: utf-8 -*-
"""
把 SQLite 客户库同步到飞书多维表格（外贸客户管理表）。

特点：
  1. 以「官网域名」和「公司名称」双重去重，飞书已有的客户不会重复创建；
  2. 空字段自动跳过，不覆盖飞书里已填的内容（本脚本只做「新增缺失记录」）；
  3. 国家/地区 选项名自动映射（沙特 -> 沙特阿拉伯）。

用法：
  python 同步数据库到飞书.py                # 正式同步（全量缺失记录）
  python 同步数据库到飞书.py --dry-run      # 只预演，打印将要写入的记录，不实际调用飞书
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
BASE_TOKEN = 'ZhSSb18BMajKR7sacxTcCFY0njf'   # 外贸客户管理表
TABLE_ID = 'tblY38YnVIQ5AYYA'                # 客户信息
LARK_CLI = r'C:\Users\admin\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe'
IMPORT_JSON = 'import_records_sync.json'     # 同步时生成的临时 JSON

DB_DIR = 'DB'
DB_FILE = '客户库.sqlite3'

# 本地国家简称 -> 飞书「国家/地区」选项名
COUNTRY_STANDARD = {'沙特': '沙特阿拉伯'}
# 飞书「来源渠道」「跟进状态」默认选项
SOURCE_DEFAULT = '谷歌搜索'
STATUS_DEFAULT = '未联系'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMAIL_OK = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$')


def db_path():
    return os.path.join(BASE_DIR, DB_DIR, DB_FILE)


def log(msg):
    print(msg, flush=True)


def run_lark(args):
    """调用 lark-cli，返回 (ok, 解析后的dict, 原始输出)"""
    env = os.environ.copy()
    env.pop('HERMES_HOME', None)   # 不清除该变量 lark-cli 会返回异常
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
    """统一提取域名作为去重键（兼容飞书里 markdown 链接写法）"""
    raw = (url or '').strip().lower()
    if not raw:
        return ''
    m = re.search(r'href="([^"]+)"', raw)
    if m:
        raw = m.group(1)
    raw = raw.strip('[]()')
    try:
        netloc = urlparse(raw if '://' in raw else 'https://' + raw).netloc
        return netloc.split(':', 1)[0].removeprefix('www.')
    except Exception:
        return ''


def fetch_feishu_keys():
    """拉取飞书已有记录（自动翻页，单页上限 200），返回 (域名集合, 公司名集合, 总数)"""
    domains, names = set(), set()
    offset, total = 0, 0
    while True:
        ok, data, out = run_lark(['base', '+record-list', '--base-token', BASE_TOKEN,
                                  '--table-id', TABLE_ID, '--limit', '200',
                                  '--offset', str(offset),
                                  '--format', 'json', '--as', 'user'])
        if not ok:
            raise RuntimeError('读取飞书已有记录失败：' + out[:500])
        d = data.get('data', {})
        cols = d.get('fields', [])
        rows = d.get('data', [])
        i_url = cols.index('官网')
        i_name = cols.index('公司名称')
        for r in rows:
            k = norm_domain(r[i_url])
            if k:
                domains.add(k)
            if r[i_name]:
                names.add(str(r[i_name]).strip())
        total += len(rows)
        if not d.get('has_more') or not rows:
            break
        offset += len(rows)
    return domains, names, total


def load_db_rows():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute('SELECT * FROM customers ORDER BY id')]
    conn.close()
    return rows


def build_record(row):
    """数据库一行 -> 飞书记录；空字段一律不带，避免覆盖飞书已有内容"""
    rec = {'公司名称': row.get('company_name') or '', '官网': row.get('website') or ''}
    if row.get('phone'):
        rec['电话'] = row['phone']
    emails = [m.strip() for m in (row.get('email') or '').split(' / ') if EMAIL_OK.match(m.strip())]
    if emails:
        rec['邮箱'] = emails[0]   # 飞书「邮箱」字段只接受单个邮箱，其余写入备注
    if row.get('search_formula'):
        rec['使用的搜索公式'] = row['search_formula']
    if row.get('country'):
        rec['国家/地区'] = [COUNTRY_STANDARD.get(row['country'], row['country'])]
    if row.get('industry'):
        rec['行业'] = [row['industry']]   # 单选字段：值用数组
    rec['来源渠道'] = [row.get('source') or SOURCE_DEFAULT]
    rec['跟进状态'] = [row.get('status') or STATUS_DEFAULT]

    # 备注：带评分信息，未评分记录也标注来源，方便人工核实优先级
    if isinstance(row.get('score'), int):
        note = '脚本评分%d分（%s），待人工核实' % (row['score'], row.get('rating') or '未评级')
        if len(emails) > 1:
            note += '；其他邮箱：' + ' / '.join(emails[1:])
    else:
        note = '未评分（来自谷歌搜索），待人工核实'
    if row.get('notes'):
        note += '；' + row['notes']
    rec['备注'] = note
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只预演，不实际写入飞书')
    args = ap.parse_args()

    log('读取飞书已有记录...')
    domains, names, total = fetch_feishu_keys()
    log('飞书现有 %d 条记录（域名 %d 个）' % (total, len(domains)))

    rows = load_db_rows()
    log('数据库现有 %d 条客户' % len(rows))

    to_add, skipped = [], 0
    for row in rows:
        k = norm_domain(row.get('website'))
        name = (row.get('company_name') or '').strip()
        if (k and k in domains) or (name and name in names):
            skipped += 1
            continue
        to_add.append(build_record(row))

    log('去重后：跳过已有 %d 条，待新增 %d 条' % (skipped, len(to_add)))
    if not to_add:
        log('没有需要同步的新记录，结束。')
        return

    if args.dry_run:
        log('\n[dry-run] 将写入以下 %d 条（仅显示前 10 条）：' % len(to_add))
        for r in to_add[:10]:
            log('  ' + json.dumps(r, ensure_ascii=False))
        return

    tmp = os.path.join(BASE_DIR, IMPORT_JSON)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'create_records': to_add}, f, ensure_ascii=False)

    log('正在写入飞书...')
    ok, data, out = run_lark(['base', '+record-batch-create', '--base-token', BASE_TOKEN,
                              '--table-id', TABLE_ID, '--json', '@' + IMPORT_JSON,
                              '--as', 'user'])
    if ok:
        created = data.get('data', {}).get('records', [])
        log('✅ 同步成功：已写入飞书 %d 条客户记录。' % (len(created) or len(to_add)))
    else:
        log('❌ 同步失败：' + out[:800])
        sys.exit(1)


if __name__ == '__main__':
    main()
