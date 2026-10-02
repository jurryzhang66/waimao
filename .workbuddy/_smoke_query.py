# -*- coding: utf-8 -*-
"""打桩冒烟：客户库查询页 /db —— 筛选各维度、排序白名单、分页、导出 Excel。

对应用户需求：「做一个数据库查询页面，筛选国家/行业等条件，查完能导出 Excel」。
本脚本把库与 output 都指向临时目录，让真实的 db_query_customers / db_facet_counts /
/api/db/* 路由跑起来，全程不碰真实客户库，也不往真实 output/查询导出/ 里丢文件。

覆盖 10 组：
  ① 打桩护栏 + 播种 8 条覆盖各分支的样本（含无行业/无国家/无邮箱/无电话/无评分/历史行业名）
  ② 分面统计：只报库里**真实存在**的取值 + 条数 + 各自的「未填写」条数
  ③ 各维度筛选：关键词 / 行业（含历史行业名、含「未标注」）/ 国家 / 来源 / 评级 /
     评分区间 / 联系方式九态 / 采集时间范围
  ④ 排序白名单（评分升降、时间新旧、公司名）+ 非法排序键静默回落
  ⑤ 分页自洽（页间不重叠、并集完整）+ limit 上下限钳制
  ⑥ 非法输入被拒（评分非整数、日期格式不对）
  ⑦ 导出 Excel：14 列、行数、内容、文件名、落盘位置
  ⑧ 导出**绝不**污染 paths.ENRICH_FILE / STATE['output']，也绝不劫持 find_latest_result
  ⑨ HTTP 路由层：/db 是成品页面（样式已注入）、facets/query/export 的 JSON 契约、下载与路径穿越
  ⑩ 空结果导出被拒；命中数超过单次上限时明确拒绝（否则会把内存撑爆）

用法：python .workbuddy\\_smoke_query.py
"""
import importlib.util
import os
import sys
import tempfile

from openpyxl import load_workbook

SRC = r'D:\waimao\dp\客户开发工具.py'
spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

sys.stdout.reconfigure(encoding='utf-8')

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


TMP = tempfile.mkdtemp(prefix='smoke_query_')
OUT = os.path.join(TMP, 'output')
os.makedirs(OUT, exist_ok=True)

# ---- 护栏：库与输出全部关进临时目录 ----
m.db_path = lambda: os.path.join(TMP, 'test.sqlite3')
m.db.db_path = m.db_path
m.paths.output_dir = lambda: OUT
# ⚠️⚠️ 这一条是本脚本最容易被漏掉的打桩：临时库是空的，init_customer_db() 会在「库为空」
#    时从 paths.ENRICH_FILE 指向的那份**真实最新结果 Excel** 把客户导进来 ——
#    不把它指到临时目录，整份测试其实跑在真实数据上（看起来还是绿的）。
m.paths.ENRICH_FILE = os.path.join(OUT, '__no_such_enrich__.xlsx')


def _under_tmp(p):
    return os.path.commonpath([os.path.realpath(p),
                               os.path.realpath(TMP)]) == os.path.realpath(TMP)


section('① 打桩护栏 + 播种样本')
check(_under_tmp(m.db.db_path()), 'core.db.db_path 已指向临时目录')
check(_under_tmp(m.paths.output_dir()), 'paths.output_dir() 已指向临时目录')
check(_under_tmp(m.paths.ENRICH_FILE), 'paths.ENRICH_FILE 已指向临时目录（不导入真实结果表）')
check(_under_tmp(m.query_export_dir()), '查询导出目录也落在临时目录')
check(_under_tmp(m.ts_query_export_path(1)), '真实 ts_query_export_path 落在临时目录')

m.init_customer_db()
check(m.db_query_customers({})[0] == 0, '临时库初始为空（没有从真实 Excel 导进任何数据）')

SAMPLES = [
    dict(company_name='Alpha Bag GmbH', website='https://alpha-bag.de',
         email='sale@alpha-bag.de', phone='+49 30 111', contact_url='',
         country='德国', industry='塑料包装袋', score=85, rating='重点客户', source='谷歌搜索'),
    dict(company_name='Beta Liner Ltd', website='https://beta-liner.co.uk',
         email='', phone='+44 20 222', contact_url='',
         country='英国', industry='塑料包装袋', score=60, rating='普通客户', source='手动采集'),
    dict(company_name='Gamma Pet Supplies', website='https://gamma-pet.ca',
         email='hi@gamma-pet.ca', phone='', contact_url='https://gamma-pet.ca/contact',
         country='加拿大', industry='宠物用品', score=45, rating='观察', source='谷歌地图'),
    # 历史行业名（重标行业.py 还没跑）：查询页必须能筛出来，所以下拉不能硬编码 8 个规范值
    dict(company_name='Delta Furniture', website='https://delta-furniture.mx',
         email='', phone='', contact_url='',
         country='墨西哥', industry='家具家居', score=20, rating='观察', source='谷歌搜索'),
    dict(company_name='Epsilon Auto Parts', website='https://epsilon-auto.mx',
         email='x@epsilon-auto.mx', phone='+52 55 333', contact_url='',
         country='墨西哥', industry='汽配', score=55, rating='普通客户', source='谷歌搜索'),
    # 无行业 / 无邮箱 / 无评分
    dict(company_name='Zeta NoScore', website='https://zeta-noscore.fr',
         email='', phone='+33 1 444', contact_url='',
         country='法国', industry='', score=None, rating='', source='手动采集'),
    # 邮箱电话都没有
    dict(company_name='Eta Blank', website='https://eta-blank.ca',
         email='', phone='', contact_url='',
         country='加拿大', industry='宠物用品', score=70, rating='重点客户', source='谷歌搜索'),
    # 无国家，但有联系页
    dict(company_name='Theta ContactOnly', website='https://theta.com',
         email='', phone='', contact_url='https://theta.com/contact',
         country='', industry='户外用品', score=30, rating='观察', source='谷歌地图'),
]
for s in SAMPLES:
    m.db_upsert_customer(s)
TOTAL = len(SAMPLES)
check(m.db_query_customers({})[0] == TOTAL, f'播种 {TOTAL} 条')


def q(filters=None, order='score_desc', limit=100, offset=0):
    """直接走后端函数（HTTP 层在 ⑨ 组单独测）。"""
    return m.db_query_customers(filters or {}, order=order, limit=limit, offset=offset)


def names(filters=None, order='score_desc'):
    return [r['company_name'] for r in q(filters, order=order)[1]]


section('② 分面统计（facet）：真实取值 + 条数')
f = m.db_facet_counts()
check(f['total'] == TOTAL, f"total = {f['total']}")
ind = {o['value']: o['count'] for o in f['industries']}
check(ind.get('塑料包装袋') == 2 and ind.get('宠物用品') == 2, f'行业计数：{ind}')
# 关键：历史行业名也要出现在下拉里（硬编码规范枚举就会漏掉这两条）
check(ind.get('家具家居') == 1 and ind.get('汽配') == 1,
      '历史行业名（家具家居 / 汽配）也在选项里 —— 下拉是按真实数据生成的')
check(f['industries_blank'] == 1, f"「未标注行业」= {f['industries_blank']}")
con = {o['value']: o['count'] for o in f['countries']}
check(con.get('加拿大') == 2 and con.get('墨西哥') == 2, f'国家计数：{con}')
check(f['countries_blank'] == 1, f"「未填写国家」= {f['countries_blank']}")
src = {o['value']: o['count'] for o in f['sources']}
check(src == {'谷歌搜索': 4, '手动采集': 2, '谷歌地图': 2}, f'来源计数：{src}')
rat = {o['value']: o['count'] for o in f['ratings']}
check(rat.get('观察') == 3 and rat.get('重点客户') == 2 and rat.get('普通客户') == 2, f'评级计数：{rat}')
check(f['ratings_blank'] == 1, f"「未评级」= {f['ratings_blank']}")
ct = f['contact']
# 逐条数一遍样本：有邮箱 = Alpha/Gamma/Epsilon 3 条；有电话 = Alpha/Beta/Epsilon/Zeta 4 条；
# 有联系页 = Gamma/Theta 2 条；邮箱电话都没有 = Delta/Eta/Theta 3 条。
check(ct['has_email'] == 3 and ct['has_phone'] == 4 and ct['has_contact_url'] == 2 and ct['no_contact'] == 3,
      f'联系方式统计：{ct}')
check(f['score'] == {'min': 20, 'max': 85}, f"评分范围：{f['score']}（跳过 NULL）")
check(f['date']['min'] == f['date']['max'], f"采集日期范围：{f['date']}")

section('③ 各维度筛选')
check(q({'industries': ['塑料包装袋']})[0] == 2, '行业=塑料包装袋 → 2')
check(q({'industries': ['家具家居', '汽配']})[0] == 2, '勾两个历史行业名 → 2（OR 语义）')
check(q({'industries': [m.db.QUERY_EMPTY]})[0] == 1, '行业选「未标注」→ 1（空值也算命中）')
check(q({'industries': ['塑料包装袋', m.db.QUERY_EMPTY]})[0] == 3, '行业「塑料包装袋 + 未标注」→ 3')
check(q({'countries': ['墨西哥']})[0] == 2, '国家=墨西哥 → 2')
check(q({'countries': [m.db.QUERY_EMPTY]})[0] == 1, '国家选「未填写」→ 1')
check(q({'sources': ['手动采集']})[0] == 2, '来源=手动采集 → 2')
check(q({'sources': ['谷歌搜索', '谷歌地图']})[0] == 6, '来源=搜索+地图 → 6')
check(q({'ratings': ['重点客户']})[0] == 2, '评级=重点客户 → 2')
check(q({'score_min': 50})[0] == 4, '评分 >= 50 → 4')
check(q({'score_max': 45})[0] == 3, '评分 <= 45 → 3')
check(q({'score_min': 50, 'score_max': 60})[0] == 2, '评分 50–60 → 2')
check(q({'score_min': 0})[0] == TOTAL - 1, '评分 >= 0 → 7（无分的那条被排除）')
for val, want in (('has_email', 3), ('has_phone', 4), ('has_contact_url', 2),
                  ('has_both', 2), ('has_any', 5), ('no_email', 5),
                  ('no_phone', 4), ('no_contact', 3)):
    check(q({'contact': val})[0] == want, f'联系方式={val} → {want}')
check(q({'kw': 'alpha'})[0] == 1, '关键词 alpha → 1')
check(q({'kw': 'pet'})[0] == 1, '关键词 pet → 1')
check(q({'kw': '塑料包装袋'})[0] == 2, '关键词能命中行业字段 → 2')
check(q({'kw': '墨西哥'})[0] == 2, '关键词能命中国家字段 → 2')
check(q({'kw': 'ALPHA'})[0] == 1, '关键词大小写不敏感（SQLite LIKE 默认）→ 1')
# ⚠️ 参数化只防注入，**不转义 LIKE 的通配符** —— % 仍会被 SQL 当成「任意字符」。
#    如实断言这个行为（真想搜字面量 % 的人几乎没有，不值得为此加转义层）。
check(q({'kw': '%'})[0] == TOTAL, '关键词里的 % 仍是 LIKE 通配符（参数化只防注入、不转义通配符）')
check(q({'kw': "x'; DROP TABLE customers; --"})[0] == 0, '注入式关键词查不到东西，且表还在')
check(m.db_query_customers({})[0] == TOTAL, '注入式关键词之后表完好无损')
check(q({'industries': ['塑料包装袋'], 'countries': ['德国']})[0] == 1, '多维度 AND → 1')
check(q({'sources': ['谷歌搜索'], 'ratings': ['重点客户'], 'score_min': 80})[0] == 1, '三重条件 → 1')
today = f['date']['min']
check(q({'seen_after': today})[0] == TOTAL, f'采集时间 >= {today} → {TOTAL}')
check(q({'seen_before': today})[0] == TOTAL, f'采集时间 <= {today} → {TOTAL}（当天不会被漏）')
check(q({'seen_after': '2099-01-01'})[0] == 0, '未来的开始日期 → 0')

section('④ 排序白名单')
check(names(order='score_desc')[0] == 'Alpha Bag GmbH', '评分降序首位 = 最高分')
check(names(order='score_asc')[0] == 'Delta Furniture', '评分升序首位 = 最低分')
check(names(order='score_desc')[-1] == 'Zeta NoScore', '无评分的行沉到末尾（不占榜首）')
check(names(order='name')[0] == 'Alpha Bag GmbH', '公司名 A→Z')
check(names(order='oldest')[0] == 'Alpha Bag GmbH', '最旧优先 = 最早入库那条')
check(names(order='newest')[0] == 'Theta ContactOnly', '最新优先 = 最后入库那条')
check(names(order='x; DROP TABLE customers') == names(order='score_desc'),
      '非法排序键静默回落默认排序（不报错、也不拼进 SQL）')
check(m.db_query_customers({})[0] == TOTAL, 'SQL 注入式排序键之后表还在')

section('⑤ 分页与 limit 钳制')
total0, page0, lim0 = q({}, limit=3, offset=0)
_, page1, _ = q({}, limit=3, offset=3)
_, page2, _ = q({}, limit=3, offset=6)
ids = [r['id'] for r in page0] + [r['id'] for r in page1] + [r['id'] for r in page2]
check(total0 == TOTAL and len(ids) == TOTAL and len(set(ids)) == TOTAL,
      f'三页并集正好 {TOTAL} 条且不重叠')
check(len(page2) == 2, '最后一页只有 2 条（不补空行）')
check(q({}, limit=3, offset=99)[1] == [], '偏移超出范围 → 空页（total 仍为真实值）')
check(q({}, limit=3, offset=99)[0] == TOTAL, '空页的 total 仍是命中总数')
check(q({}, limit=0)[2] == 1, 'limit=0 被钳到 1（不会退化成取全部）')
check(q({}, limit=99999)[2] == m.QUERY_MAX_LIMIT, f'超大 limit 被钳到 {m.QUERY_MAX_LIMIT}')
check(q({}, limit='abc')[2] == 50, '非法 limit 字符串回落 50')
check(q({}, offset=-5)[1][0]['id'] == page0[0]['id'], '负 offset 被钳到 0')

section('⑥ 非法输入被拒')
for bad, desc in (({'score_min': 'abc'}, '评分区间填字母'),
                  ({'score_max': '1.5'}, '评分区间填小数'),
                  ({'seen_after': '2026/01/01'}, '日期用了斜杠'),
                  ({'seen_before': '20260101'}, '日期没分隔符')):
    try:
        m.db_query_customers(bad)
        check(False, f'{desc} 应被拒绝')
    except ValueError as e:
        check(True, f'{desc} → ValueError：{e}')
check(q({'score_min': ''})[0] == TOTAL, '评分区间留空 = 不限制')

section('⑦ 导出 Excel')
r = m.app.test_client().post('/api/db/export',
                             json={'filters': {'countries': ['墨西哥']},
                                   'order': 'score_desc'}).get_json()
check(r.get('ok') is True, f'导出返回 ok：{r}')
check(r.get('rows') == 2, f"导出 2 条（实际 {r.get('rows')}）")
check('查询导出' in r.get('name', ''), f"文件名带「查询导出」：{r.get('name')}")
path = os.path.join(m.query_export_dir(), r.get('name', ''))
check(os.path.isfile(path), '文件真的写出了')
check(os.path.dirname(os.path.abspath(path)) == os.path.abspath(m.query_export_dir()),
      '落在「查询导出」子目录里')
wb = load_workbook(path, read_only=True)
ws = wb.active
head = [c.value for c in ws[1]]
rows = [tuple(c.value for c in row) for row in ws.iter_rows(min_row=2)]
wb.close()
check(head == [t for _, t in m.QUERY_EXPORT_COLUMNS], f'表头 14 列与契约一致：{head}')
check(len(head) == 14 and head[0] == '公司名称' and head[-1] == '最近更新时间', '首尾列名对得上')
check(len(rows) == 2, f'数据 2 行（实际 {len(rows)}）')
flat = ' '.join(str(x) for row in rows for x in row)
check('Delta Furniture' in flat and 'Epsilon Auto Parts' in flat, '导出的确实是筛选命中的那两条')
check('Alpha' not in flat, '没命中的客户没被写进去')
check('家具家居' in flat, '行业列带上了真实值（历史行业名原样导出）')

section('⑧ 导出不影响「本轮结果」链路')
check(os.path.basename(m.paths.ENRICH_FILE) == '__no_such_enrich__.xlsx',
      'paths.ENRICH_FILE 没被导出改动')
check(m.STATE.get('output') in ('', None), "STATE['output'] 没被导出改动")
# 反证 + 正证：查询导出**必须**在子目录里，否则会被当成「最新结果文件」
import glob as _glob
wanted = os.path.join(OUT, '食品-20000101_1200-德国.xlsx')
open(wanted, 'wb').close()                     # 随便造一个「结果文件」占位（名字含 8 位日期）
# ⚠️ 占位文件刻意用 2000 年（比查询导出旧），这样下面那条反证才会成立 ——
#    用未来日期的话「取最新」选中的仍是结果文件，反证就白写了。
check(os.path.basename(m.find_latest_result()) == os.path.basename(wanted),
      'find_latest_result 选中 output/ 根下的结果文件')
check(len(_glob.glob(os.path.join(OUT, '*.xlsx'))) == 1,
      'output/ 根下只有那份结果文件（查询导出不在这一层）')
check('查询导出' not in os.path.basename(m.find_latest_result()),
      '查询导出表不会被误认成「最新结果文件」（这正是放进子目录的原因）')
# 真·反证：把它复制到 output/ 根下，立刻会被选中 —— 说明子目录不是可选项
tmp_copy = os.path.join(OUT, r.get('name'))
import shutil as _shutil
_shutil.copy2(path, tmp_copy)
check('查询导出' in os.path.basename(m.find_latest_result()),
      '【反证】若把查询导出放到 output/ 根下，它立刻会劫持「最新结果文件」')
os.remove(tmp_copy)
check(os.path.basename(m.find_latest_result()) == os.path.basename(wanted), '删掉后恢复原状')

section('⑨ HTTP 路由层')
c = m.app.test_client()
resp = c.get('/db')
body = resp.get_data(as_text=True)
check(resp.status_code == 200, '/db 返回 200')
check('PAGE_CSS_PLACEHOLDER' not in body, '/db 的样式占位符已被替换')
check('table.live' in body and '.btn-start' in body and '.tag-r1' in body,
      '/db 拿到了 page.html 注入的共享样式')
for need in ('id="facetGrid"', 'id="resBody"', 'id="btnQuery"', 'id="btnExport"',
             'id="btnPrev"', 'id="btnNext"', 'id="scoreMin"', 'id="seenAfter"',
             'id="contact"', 'id="order"', 'id="pagesize"', 'id="log"'):
    check(need in body, f'/db 页面有 {need}')
check('__empty__' in body and '食品' not in body.split('id="facetGrid"')[1][:400],
      '行业选项由接口动态生成（页面里没硬编码行业名）')
check('/api/db/query' in body and '/api/db/export' in body and '/api/db/facets' in body,
      '/db 页打开了三个新接口')
check('clientWidth' not in body and 'resTable' in body, '/db 结果表元素在位')

fj = c.get('/api/db/facets').get_json()
check(fj.get('ok') is True and fj.get('total') == TOTAL, f'/api/db/facets 契约正确：total={fj.get("total")}')
qj = c.post('/api/db/query', json={'filters': {'ratings': ['观察']}, 'order': 'score_desc',
                                   'limit': 2, 'offset': 0}).get_json()
check(qj.get('ok') is True and qj.get('total') == 3 and len(qj.get('rows', [])) == 2,
      f'/api/db/query 分页契约：total={qj.get("total")} 本页={len(qj.get("rows", []))}')
check(qj.get('limit') == 2 and qj.get('offset') == 0, '/api/db/query 回显 limit/offset')
check('website_key' not in (qj.get('rows') or [{}])[0], '返回行里不带内部去重键 website_key')
check(c.post('/api/db/query', json={'filters': {'score_min': 'x'}}).get_json().get('ok') is False,
      '/api/db/query 对非法条件返回 ok=False（不是 500）')
check(c.post('/api/db/query', json={}).get_json().get('total') == TOTAL,
      '/api/db/query 空 body 也能跑（等价于不加条件）')
check(c.post('/api/db/query').get_json().get('ok') is True, '/api/db/query 非 JSON body 不崩')

dl = c.get(r['url'])
check(dl.status_code == 200 and len(dl.get_data()) == os.path.getsize(path),
      '下载路由能取回刚导出的文件')
dl.close()          # ⚠️ send_file 的响应持有文件句柄，不关掉后面删文件会 WinError 32
for bad in ('../客户开发工具.py', '..%2F..%2F客户开发工具.py', '__不存在__.xlsx'):
    check(c.get('/api/db/download/' + bad).status_code == 404,
          f'下载挡住越权/不存在的名字：{bad}')
check(m.query_page.__name__ == 'query_page' and 'query_page' in m.app.view_functions,
      '/db 路由已注册')
check(all(n in m.app.view_functions for n in
          ('api_db_facets', 'api_db_query', 'api_db_export', 'api_db_download', 'api_db_open_folder')),
      '查询相关 5 个 API 路由都已注册')

section('⑩ 导出边界')
check(c.post('/api/db/export', json={'filters': {'kw': 'zzz-查无此人-zzz'}}).get_json().get('ok') is False,
      '命中 0 条时拒绝导出（不产出空表）')
_saved = m.QUERY_EXPORT_MAX
try:
    m.QUERY_EXPORT_MAX = 2
    e = c.post('/api/db/export', json={'filters': {}}).get_json()
    check(e.get('ok') is False and '上限' in (e.get('msg') or ''),
          f'命中数超过单次上限时明确拒绝：{e.get("msg")}')
finally:
    m.QUERY_EXPORT_MAX = _saved
# 清理本组导出的文件（只删自己造的两个）
for p in (path, wanted):
    if os.path.exists(p):
        os.remove(p)
check(os.listdir(m.query_export_dir()) == [], '导出目录已清空（只留空目录）')

section('⑪ 删除客户（勾选批量 / 每行 ✕ 打同一条接口）')


def id_of(name):
    for _r in q({})[1]:
        if _r['company_name'] == name:
            return _r['id']
    return None


def total_now():
    return q({})[0]


# —— 纯函数层：任何「不合法输入」都不许退化成清库 ——
check(m.db_delete_customers_by_ids([]) == (0, []), '空列表直接返回 0（绝不清库）')
check(m.db_delete_customers_by_ids(None) == (0, []), 'None 也直接返回 0')
check(m.db_delete_customers_by_ids('1,2') == (0, []), '传字符串也返回 0（不当可迭代拆）')
check(m.db_delete_customers_by_ids(['x', -1, 0, None, True]) == (0, []),
      '全是不合法 id 时返回 0（这才是「不清库」那道门）')
check(total_now() == TOTAL, '以上四次调用一行都没删掉')

za = id_of('Zeta NoScore')
check(m.db_delete_customers_by_ids([za, za]) == (1, []),
      f'同一个 id 传两次只算一条（id={za}）')
check(total_now() == TOTAL - 1, f'删掉 1 条后总数 {TOTAL} → {total_now()}')
check(q({'kw': 'zeta-noscore'})[0] == 0, '删掉的客户已经查不到了')
check(m.db_delete_customers_by_ids([999999]) == (0, [999999]),
      '不存在的 id 如实报 missing（不报错也不牵连别的行）')

# —— 删除前备份：必须落**打桩目录**（_backups_dir() 由 db_path() 推导，漏打桩就会写真实 DB/backups/）——
m.db._last_delete_backup_at = 0.0        # 清掉节流，确保这次真的会备份
_bak = m.backup_db_before_delete()
check(_bak != '' and os.path.exists(_bak), f'删除前确实落了一份备份：{os.path.basename(_bak or "")}')
check(_under_tmp(_bak), '备份落在打桩的临时目录里（没往真实 DB/backups/ 塞测试垃圾）')
check(m.backup_db_before_delete() == '', '300 秒节流生效：紧接着再删不会重复备份')

# —— HTTP 层 ——
check(c.post('/api/db/delete', json={'ids': []}).get_json().get('ok') is False,
      'ids 为空数组时被拒（不是「等于清库」）')
check(c.post('/api/db/delete', json={'ids': 'abc'}).get_json().get('ok') is False,
      'ids 不是数组时被拒')
check(c.post('/api/db/delete', json={}).get_json().get('ok') is False, '缺 ids 时被拒')
check(c.post('/api/db/delete').get_json().get('ok') is False, '非 JSON body 不崩')
check(total_now() == TOTAL - 1, '以上四个被拒的请求真的一行都没删')

before = total_now()
a_id, b_id = id_of('Delta Furniture'), id_of('Epsilon Auto Parts')
m.db._last_delete_backup_at = 0.0        # 再清一次节流：验证**路由**自己也会先备份
dj = c.post('/api/db/delete', json={'ids': [a_id, b_id, 999999]}).get_json()
check(dj.get('ok') is True and dj.get('deleted') == 2, f'批量删 2 条：{dj}')
check(dj.get('missing') == [999999], f'顺带如实回报不存在的 id：{dj.get("missing")}')
check(bool(dj.get('backup')), f'路由在删之前自己做了备份：{dj.get("backup")}')
check(os.path.exists(os.path.join(m.db._backups_dir(), dj.get('backup') or 'x')),
      '路由返回的那个备份文件名在磁盘上真的存在')
check(total_now() == before - 2, f'总数再 -2（{before} → {total_now()}）')

_saved_del_max = m.QUERY_DELETE_MAX
try:
    m.QUERY_DELETE_MAX = 1
    big = c.post('/api/db/delete', json={'ids': [id_of('Alpha Bag GmbH'),
                                                id_of('Beta Liner Ltd')]}).get_json()
    check(big.get('ok') is False and '最多' in (big.get('msg') or ''),
          f'一次删太多时明确拒绝：{big.get("msg")}')
finally:
    m.QUERY_DELETE_MAX = _saved_del_max
check(total_now() == before - 2, '被拒的超限请求没删掉任何一行')
check(m.db_delete_customer('beta-liner.co.uk') == 1
      and m.db_delete_customers_by_ids([]) == (0, []),
      '原有的按网站键删除仍然可用，且与按 id 删除并存不冲突')

# —— 隔离性：删除链路同样不许碰「本轮结果」指针 ——
check(os.path.basename(m.paths.ENRICH_FILE) == '__no_such_enrich__.xlsx',
      'paths.ENRICH_FILE 没被删除链路改动')
check(m.STATE.get('output') in ('', None), "STATE['output'] 没被删除链路改动")

# —— 页面与路由 ——
body2 = c.get('/db').get_data(as_text=True)
for _need in ('id="btnDelSel"', 'id="ckAll"', 'class="row-del"', 'class="row-ck"',
              'id="btnDelSel"', "getElementById('btnDelSel')", "'/api/db/delete'",
              'function deleteRows(', 'function syncSel(', 'function selectedIds(',
              "getElementById('resBody').addEventListener('click'"):
    check(_need in body2, f'/db 页面含删除相关实现：{_need}')
check('data-id' in body2, '删除按钮/勾选框带 data-id（按主键删，不按网址）')
check('.row-del' in body2 and '.btn-del' in body2,
      '删除相关样式写在本页自己的 <style> 里')
check('api_db_delete' in m.app.view_functions, '删除接口路由已注册')
check(m.QUERY_DELETE_MAX == 500, f'单次批量删除上限为 {m.QUERY_DELETE_MAX}')

print('\n' + '=' * 62)
print(f'通过 {_ok} 项' + (f'，失败 {len(_fail)} 项：' if _fail else '，全部通过 ✅'))
for d in _fail:
    print('   ❌', d)
print('临时目录：', TMP)
sys.exit(1 if _fail else 0)
