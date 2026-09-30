# -*- coding: utf-8 -*-
"""打桩冒烟测试：不联网、不开浏览器，验证「边搜边补」闭环流程。

做法：加载主工具模块后，把浏览器/搜索/抓取这几个外部依赖全部替换成假实现，
只让「主循环 + 补全 + 回写客户库 + 落盘」这段真实逻辑跑起来。
数据库与结果文件都指向临时目录，绝不触碰真实客户库。
"""
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile

SRC = r'D:\waimao\dp\客户开发工具.py'
spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

TMP = tempfile.mkdtemp(prefix='smoke_')
# ⚠️ 主程序已拆出 core/ 包：真正建连接的是 core/db.py 的 db_connect()，它调的是 core.db.db_path()。
# 只补 m.db_path 打不到 core.db 内部 —— 假公司会被写进**真实客户库** DB/客户库.sqlite3。
m.db_path = lambda: os.path.join(TMP, 'test.sqlite3')
m.db.db_path = m.db_path
m.ts_result_path = lambda industry='', country='': os.path.join(TMP, 'out.xlsx')


# ---- 打桩护栏：两处 db_path 都必须在临时目录内，否则直接报错（防静默污染生产库）----
def _under_tmp(p):
    return os.path.commonpath([os.path.realpath(p),
                               os.path.realpath(TMP)]) == os.path.realpath(TMP)


assert _under_tmp(m.db.db_path()), f'core.db.db_path 未指向临时目录：{m.db.db_path()}'
assert _under_tmp(m.db_path()), f'入口 db_path 未指向临时目录：{m.db_path()}'
assert _under_tmp(m.ts_result_path('x', 'y')), \
    f'ts_result_path 未指向临时目录：{m.ts_result_path("x", "y")}'
print('打桩护栏 OK：core.db.db_path =', m.db.db_path())

calls = {'activate': 0, 'enriched': [], 'saved': None, 'quit': 0, 'search': 0,
         'formulas': [], 'params': []}


class FakePage:
    tab_id = 'FAKE-TAB'

    def activate_tab(self, tid):
        calls['activate'] += 1
        assert tid == 'FAKE-TAB', f'切回的标签 id 不对：{tid}'

    def quit(self):
        calls['quit'] += 1


m.create_browser_page = lambda: FakePage()


def fake_open_search(page, formula, country_params, start=0, min_items=3, attempts=3):
    calls['search'] += 1
    if start == 0:                       # 只记录第 1 页，翻页会重复
        calls['formulas'].append(formula)
        calls['params'].append(country_params)
    return True


m.open_search = fake_open_search
m.wait_captcha = lambda page, max_wait=180: True
m.sleep_check = lambda seconds: True

# 每轮搜索用不同的假结果集，避免第二轮被「客户库已有」全部挡掉
CUR_ITEMS = [{'title': f'Test Co {i}', 'url': f'https://testco{i}.com/',
              'snippet': 'wholesale distributor'} for i in range(1, 6)]
# 注意签名要与 run_search 里的调用一致：extract_results(page, seen_titles, china_filters)
# 返回三元组 (items, blocked_count, china_reasons)，china_reasons 是 dict
m.extract_results = lambda page, seen_titles, china_filters=None: (CUR_ITEMS, 0, {})


def fake_enrich(page, url):
    calls['enriched'].append(url)
    if 'testco1' in url:
        return {'emails': ['sales@testco1.com'], 'phones': ['+1 555 0100'],
                'contact_url': url + 'contact'}
    return {'emails': [], 'phones': [], 'contact_url': ''}


m.enrich = fake_enrich


def spy_save(results, industry=''):
    calls['saved'] = results
    return True


m._save_enrich_excel = spy_save

print('================ 开始冒烟测试 ================')
m.run_search(['cat litter'], ['wholesale'], [('us', '美国', 'us', 'en')], 1, '-alibaba',
             'or', 3, '宠物用品', True)

print('\n================ 断言 ================')
assert calls['saved'] is not None, '结果未落盘'
assert len(calls['saved']) == 3, f'应停在目标 3 条，实际 {len(calls["saved"])}'
assert calls['activate'] == 3, f'切回搜索标签应 3 次，实际 {calls["activate"]}'
assert len(calls['enriched']) == 3, f'补全应执行 3 次，实际 {len(calls["enriched"])}'
assert calls['quit'] == 1, f'浏览器应关闭 1 次，实际 {calls["quit"]}'
print(f'落盘条数 {len(calls["saved"])} | 就补全 {len(calls["enriched"])} 次 | '
      f'切回搜索标签 {calls["activate"]} 次 | 关闭浏览器 {calls["quit"]} 次')

for r in calls['saved']:
    for k in ('title', 'url', 'emails', 'phones', 'contact_url', 'score',
              'rating', 'snippet', 'formula', 'country'):
        assert k in r, f'落盘记录缺字段：{k}'

# ---- STATE['rows']：前端实时明细表的数据源，必须与入库条数一致 ----
live = m.STATE['rows']
assert len(live) == 3, f'实时明细应有 3 条，实际 {len(live)}'
assert live[0]['emails'] == ['sales@testco1.com'], '实时明细第一家的邮箱不对'
assert live[0]['rating'] == '普通客户' and live[0]['score'] == 65, '实时明细评分/评级不对'
assert live[1]['emails'] == [], '实时明细第二家邮箱应为空'
assert [r['n'] for r in live] == [1, 2, 3], '实时明细序号应为 1/2/3'
print('实时明细 {0} 条，序号 {1}，首条邮箱 {2}'.format(
    len(live), [r['n'] for r in live], live[0]['emails']))

# ---- /api/status 必须带上 rows 与 db_total ----
with m.app.test_client() as c:
    resp = c.get('/api/status?since=0').get_json()
assert 'rows' in resp and len(resp['rows']) == 3, '/api/status 未返回 rows 或条数不符'
assert resp.get('db_total') is not None, '/api/status 未返回 db_total（库总数徽章无法实时刷新）'
print('接口 /api/status：rows {0} 条，db_total {1}'.format(len(resp['rows']), resp['db_total']))

conn = sqlite3.connect(m.db_path())
conn.row_factory = sqlite3.Row
# 只断言本轮写入的 3 条（init_customer_db 会顺带把项目里旧的结果 Excel 导入临时库，与本次无关）
rows = conn.execute("SELECT company_name,website,email,phone,score,rating,industry "
                    "FROM customers WHERE website LIKE 'https://testco%' ORDER BY website").fetchall()
total = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
conn.close()
print(f'临时库总记录 {total} 条，其中本轮写入 {len(rows)} 条')
assert len(rows) == 3, f'本轮应写入 3 条，实际 {len(rows)}'
for r in rows:
    print('   库内：', dict(r))
assert rows[0]['email'] == 'sales@testco1.com', '抓到邮箱的记录没写进库'
assert rows[0]['industry'] == '宠物用品', '行业标签没写进库'
assert rows[1]['email'] == '', '第二家没有邮箱，应为空'

# ---- 后续几轮：法国 + 法语产品词，验证「条件词按国家语言本地化」+「gl/hl 参数」 ----
# 每轮只勾一个条件、用不同域名，避免被「已达标 / 客户库已有」提前中断。
def fr_run(tag, cond_keys, lang='', target=2):
    global CUR_ITEMS
    CUR_ITEMS = [{'title': f'Grossiste {tag} {i}', 'url': f'https://{tag}-{i}.fr/',
                  'snippet': 'grossiste importateur'} for i in range(1, 6)]
    calls['formulas'].clear()
    calls['params'].clear()
    print(f'\n---- 法国 · 条件 {cond_keys} · lang={lang!r} ----')
    m.run_search(['nouilles'], cond_keys, [('fr', '法国', 'fr', 'fr')], 1,
                 '-alibaba', 'or', target, '食品', True, lang)
    print('实际发出的第 1 页公式：')
    for f in calls['formulas']:
        print('   ', f)
    assert calls['formulas'], '一条公式都没发出'
    assert all(p == '&gl=fr&hl=fr' for p in calls['params']), \
        f'国家参数不对：{calls["params"]}'


fr_run('ws', ['wholesale'])
assert all('grossiste OR distributeur' in f for f in calls['formulas']), \
    '法语下「找批发商」没换成 grossiste/distributeur'

fr_run('im', ['importer'])
assert all('importateur' in f for f in calls['formulas']), \
    '法语下「找进口商」没换成 importateur'

fr_run('ln', ['linkedin'])
assert all('achats OR approvisionnement OR acheteur' in f for f in calls['formulas']), \
    '法语下领英条件没换成本地词'
assert not any('""' in f for f in calls['formulas']), \
    '公式里出现双引号（模板不该再给 {p} 加引号）'

fr_run('ct', ['contact'])
assert all('inurl:contact "nouilles"' in f for f in calls['formulas']), \
    f'contact 公式不对：{calls["formulas"]}'
assert not any('""' in f for f in calls['formulas']), 'contact 公式出现双引号'

# 未传 lang 时按国家 hl 推断（上面三轮已验证）；显式传 lang 时以传入为准
fr_run('en', ['wholesale'], lang='en')
assert all('wholesaler OR distributor' in f for f in calls['formulas']), \
    '显式传 lang=en 时应以传入为准'
assert not any('grossiste' in f for f in calls['formulas']), 'lang=en 时不该出现法语词'
print('  ✓ 条件词按国家语言本地化；显式 lang 优先于国家 hl')
print('  ✓ fa（波斯语）等缺失语言由 cond_template 回落英文，已有断言覆盖')

print('\n✅ 冒烟测试全部通过')

shutil.rmtree(TMP, ignore_errors=True)
