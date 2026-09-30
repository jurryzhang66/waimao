# -*- coding: utf-8 -*-
"""SQLite 客户库：连接、建表、去重键、upsert、统计（原 `客户开发工具.py` 第 375–530 行整段搬入）。

依赖：`core.paths`（路径与去重正则）+ `core.state`（log）。
`log` 之所以必须来自 `core.state` 而不是入口：`init_customer_db()` 要调它，
若 log 留在入口，这里就得反过来 import 入口 → 循环导入。
"""
import os
import sqlite3
import time
from contextlib import closing
from urllib.parse import urlparse

from openpyxl import load_workbook

from core import paths
from core.paths import DB_DIR, DB_FILE, MAPS_PLACE_ID_RE, _app_dir
from core.state import log


# ================= SQLite 客户库 =================
def db_path():
    base_dir = _app_dir()          # 程序根（不是「本文件所在目录」，见 core/paths.py 的 _app_dir 注释）
    db_dir = os.path.join(base_dir, DB_DIR)
    os.makedirs(db_dir, exist_ok=True)   # DB 文件夹不存在时自动创建
    return os.path.join(db_dir, DB_FILE)


def maps_place_key(url):
    """从谷歌地图 place 链接里提取稳定去重键（结尾的 0x...:0x... 十六进制段）。
    比商家名可靠（同名商家多），也比 place_id 好取（place_id 还得额外解析一次）。
    取不到返回空串。"""
    m = MAPS_PLACE_ID_RE.search(url or '')
    return ('maps:' + m.group(1).lower()) if m else ''


def normalize_domain(url):
    """把网址规整为稳定的公司去重键。"""
    try:
        raw = (url or '').strip().lower()
        if '@' in raw and '://' not in raw:
            return ''
        # 谷歌地图 place 链接：没官网的商家会落到这里。必须给个稳定键，
        # 否则 netloc 全是 google.com —— 既被搜索引擎黑名单拦掉，又互相覆盖成一条。
        mk = maps_place_key(raw)
        if mk:
            return mk
        netloc = urlparse(raw if '://' in raw else 'https://' + raw).netloc
        netloc = netloc.split(':', 1)[0].removeprefix('www.')
        return netloc
    except Exception:
        return ''


def normalize_email(email):
    return (email or '').strip().lower()


def db_connect():
    conn = sqlite3.connect(db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_customer_db():
    """初始化客户库，并把已有评分 Excel 导入一次。"""
    with closing(db_connect()) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL DEFAULT '',
            website TEXT NOT NULL DEFAULT '',
            website_key TEXT UNIQUE,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            contact_url TEXT DEFAULT '',
            country TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            score INTEGER,
            rating TEXT DEFAULT '',
            snippet TEXT DEFAULT '',
            search_formula TEXT DEFAULT '',
            source TEXT DEFAULT '谷歌搜索',
            status TEXT DEFAULT '未联系',
            next_follow_up TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            verified_at TEXT DEFAULT ''
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email)')
        # 老库升级：补齐后加的列（已有 DB 不会因缺列报错）
        cols = [r[1] for r in conn.execute('PRAGMA table_info(customers)')]
        if 'industry' not in cols:
            conn.execute("ALTER TABLE customers ADD COLUMN industry TEXT DEFAULT ''")
        conn.commit()
    # 只在库为空时迁移旧结果，保证重复运行不会重复导入。
    with closing(db_connect()) as conn:
        empty = conn.execute('SELECT 1 FROM customers LIMIT 1').fetchone() is None
    if empty and os.path.exists(paths.ENRICH_FILE):     # ⚠️ 须按属性读，才是最新值
        try:
            wb = load_workbook(paths.ENRICH_FILE, read_only=True)
            ws = wb.active
            for r in ws.iter_rows(min_row=2, values_only=True):
                if r and len(r) > 1 and r[1]:
                    db_upsert_customer({
                        'company_name': r[0], 'website': r[1],
                        'email': r[2] or '', 'phone': r[3] or '',
                        'contact_url': r[4] or '', 'score': r[5],
                        'rating': r[6] or '', 'snippet': r[7] or '',
                        'search_formula': r[8] or '',
                        'country': r[9] if len(r) > 9 else '',
                    })
            wb.close()
            log('✅ 已将现有评分 Excel 导入 SQLite 客户库')
        except Exception as ex:
            log(f'⚠️ 旧 Excel 导入客户库失败：{type(ex).__name__}: {ex}')


def db_upsert_customer(data):
    """新增或合并客户；空值不会覆盖数据库里已有的有效值。"""
    website = (data.get('website') or '').strip()
    website_key = normalize_domain(website)
    email = normalize_email(data.get('email', ''))
    if not website_key and not email:
        return False
    fields = {
        'company_name': data.get('company_name', ''), 'website': website,
        'email': email, 'phone': data.get('phone', ''),
        'contact_url': data.get('contact_url', ''), 'country': data.get('country', ''),
        'industry': data.get('industry', ''),
        'score': data.get('score'), 'rating': data.get('rating', ''),
        'snippet': data.get('snippet', ''), 'search_formula': data.get('search_formula', ''),
        'source': data.get('source', '谷歌搜索'), 'notes': data.get('notes', ''),
    }
    with closing(db_connect()) as conn:
        row = None
        if website_key:
            row = conn.execute('SELECT * FROM customers WHERE website_key=?', (website_key,)).fetchone()
        if row is None and email:
            row = conn.execute('SELECT * FROM customers WHERE lower(email)=?', (email,)).fetchone()
        if row is None:
            conn.execute('''INSERT INTO customers
                (company_name,website,website_key,email,phone,contact_url,country,industry,score,rating,
                 snippet,search_formula,source,notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (fields['company_name'], fields['website'], website_key, fields['email'],
                 fields['phone'], fields['contact_url'], fields['country'], fields['industry'],
                 fields['score'], fields['rating'], fields['snippet'], fields['search_formula'],
                 fields['source'], fields['notes']))
            conn.commit()
            return True
        updates = []
        values = []
        for key, value in fields.items():
            if value not in ('', None) and (key != 'score' or isinstance(value, (int, float))):
                updates.append(f'{key}=?')
                values.append(value)
        if website_key and not row['website_key']:
            updates.append('website_key=?')
            values.append(website_key)
        updates.append("last_seen_at=datetime('now','localtime')")
        values.append(row['id'])
        conn.execute(f"UPDATE customers SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()
        return False


def db_stats():
    init_customer_db()
    with closing(db_connect()) as conn:
        total = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM customers WHERE score IS NOT NULL").fetchone()[0]
    return {'total': total, 'verified': verified, 'file': DB_DIR + '/' + DB_FILE}


# ================= 删除客户（含删除前自动备份）=================
# 「本轮采集明细」每行一个 ✕：把不想要的条目从本轮清单里拿掉，同时把库里那条也删掉。
# 这是**不可逆**操作，所以删之前先做一份 WAL 安全的一致性备份。
_DELETE_BACKUP_MIN_INTERVAL = 300   # 秒。连点删多行时只留一份，免得把 DB/backups 撑爆
_last_delete_backup_at = 0.0


def _backups_dir():
    """备份目录 = 库文件同级的 backups/。
    刻意由 db_path() 推导：回归脚本只要打桩了 core.db.db_path，备份就自动落进临时目录，
    护栏不必再为备份目录单独补一处打桩（漏打就会往真实 DB/backups/ 里塞测试垃圾）。"""
    return os.path.join(os.path.dirname(db_path()), 'backups')


def backup_db_before_delete():
    """删除客户前做一次一致性备份，返回备份文件绝对路径；被节流或失败返回 ''。
    ⚠️ 必须用 sqlite3 的在线 backup()，**禁止 shutil.copy2** —— 库是 WAL 模式，裸拷贝会漏掉
       -wal 里尚未 checkpoint 的写入，备出来的可能缺最新数据（同 重标行业.py 的做法）。
    ⚠️ 备份失败**不阻断**删除（用户按的按钮是「删除」，不是「备份」），只记日志、返回 ''。"""
    global _last_delete_backup_at
    now = time.time()
    if now - _last_delete_backup_at < _DELETE_BACKUP_MIN_INTERVAL:
        return ''
    try:
        d = _backups_dir()
        os.makedirs(d, exist_ok=True)
        dst_path = os.path.join(d, '客户库_删除前_' + time.strftime('%Y%m%d_%H%M%S') + '.sqlite3')
        src = sqlite3.connect(db_path())
        dst = sqlite3.connect(dst_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        _last_delete_backup_at = now
        log('🗄️ 删除前已备份客户库：' + dst_path)
        return dst_path
    except Exception as ex:
        log(f'⚠️ 删除前备份客户库失败（继续删除）：{type(ex).__name__}: {ex}')
        return ''


def db_delete_customer(website=''):
    """按 website_key 删掉一条客户，返回删除行数（0 或 1）。
    ⚠️ key 为空时**直接返回 0** —— normalize_domain 对坏 url 会返回 ''，
       少了这道门就会退化成 `DELETE FROM customers`（清库）。SQL 全参数化。
    ⚠️ 刻意不做 lower(email) 兜底：db_upsert_customer 会用 email 把新站**合并到别人那条**上，
       若这里再按 email 删，删掉的是另一家公司的记录。key 没命中就如实返回 0。"""
    key = normalize_domain(website)
    if not key:
        return 0
    with closing(db_connect()) as conn:
        row = conn.execute('SELECT id FROM customers WHERE website_key=? LIMIT 1',
                           (key,)).fetchone()
        if row is None:
            return 0
        cur = conn.execute('DELETE FROM customers WHERE id=?', (row['id'],))
        conn.commit()
        return cur.rowcount
