# -*- coding: utf-8 -*-
"""打桩冒烟测试：不联网、不开浏览器，验证「边搜边补」闭环流程。

做法：加载主工具模块后，把浏览器/搜索/抓取这几个外部依赖全部替换成假实现，
只让「主循环 + 补全 + 回写客户库 + 落盘」这段真实逻辑跑起来。
数据库与结果文件都指向临时目录，绝不触碰真实客户库。
"""
import importlib.util
import json
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
# ⛔ 回归调度器会注入 DP_UI_PREFS（主页「上次参数」记忆，M25）；本脚本已把 db_path 打到 TMP，
#    这里必须摘掉环境变量，让 ui_prefs_path() 老老实实跟随 db_path → 也落 TMP。
os.environ.pop('DP_UI_PREFS', None)
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
         'formulas': [], 'params': [], 'domain_keys': []}


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
# 注意签名要与 run_search 里的调用一致：extract_results(page, seen_titles, china_filters, domain_keys)
# 返回三元组 (items, blocked_count, china_reasons)，china_reasons 是 dict
# ⛔ domain_keys 必须显式收下：2026-10-19 起 run_search 会传第 4 个参数（自定义模式的平台域名拦截），
#    桩少写一个参数就会 TypeError，整个冒烟直接挂 —— 不是产品 bug，是桩没跟上。
def fake_extract_flat(page, seen_titles, china_filters=None, domain_keys=None):
    # 固定结果集版：同样记录 domain_keys，用来断言**标准模式永远传 None**（= 行为零变化）。
    calls['domain_keys'].append(None if domain_keys is None else sorted(domain_keys))
    return (CUR_ITEMS, 0, {})


m.extract_results = fake_extract_flat


def fake_enrich(page, url):
    calls['enriched'].append(url)
    if 'testco1' in url:
        return {'emails': ['sales@testco1.com'], 'phones': ['+1 555 0100'],
                'contact_url': url + 'contact'}
    if 'cn-supplier-' in url:            # 自定义模式对照实验用：带 +86 电话与 .cn 邮箱的中国站
        return {'emails': ['sales@cn-supplier.cn'], 'phones': ['+86 138 0000 0000'],
                'contact_url': url + 'contact'}
    return {'emails': [], 'phones': [], 'contact_url': ''}


m.enrich = fake_enrich


def spy_save(results, industry=''):
    calls['saved'] = results
    return True


m._save_enrich_excel = spy_save


def export_now():
    """模拟用户点「📥 导出 Excel」：真打一次 HTTP 接口（`/api/export_excel`）。

    ⛔ 新语义（2026-10-13）：采集阶段（run_search / run_maps）**不写库、不落盘** —— 只往
       `STATE['rows']` 攒行并置 `pending_export=True`。只有这一步才会「先逐条入库、再写结果 Excel」。
       所以本脚本里凡是要看 `calls['saved']` 的地方，都得先调它一次。
    导出成功后 `STATE['rows']` 会被清空、`pending_export` 复位。
    """
    with m.app.test_client() as c:
        return c.post('/api/export_excel').get_json()


print('================ 开始冒烟测试 ================')
m.run_search(['cat litter'], ['wholesale'], [('us', '美国', 'us', 'en')], 1, '-alibaba',
             'or', 3, '宠物用品', True)

print('\n================ 断言 ================')
# ---- ① 采集阶段**不落盘、不入库**（2026-10-13 新语义）----
# 跑完只往 STATE['rows'] 攒行 + 置「待导出」；等用户核对完点「📥 导出 Excel」才写库 + 落盘。
assert calls['saved'] is None, '采集阶段不该落盘（新语义：要等点「📥 导出 Excel」）'
assert m.STATE['pending_export'] is True, '跑完应进入「待导出」状态（否则用户既导不了也开不了新一轮）'
assert calls['activate'] == 3, f'切回搜索标签应 3 次，实际 {calls["activate"]}'
assert len(calls['enriched']) == 3, f'补全应执行 3 次，实际 {len(calls["enriched"])}'
assert calls['quit'] == 1, f'浏览器应关闭 1 次，实际 {calls["quit"]}'

# ---- ② STATE['rows'] 就是「待导出的那一份」：必须是与落盘同构的**完整 11 键行** ----
live = m.STATE['rows']
assert len(live) == 3, f'实时明细应有 3 条，实际 {len(live)}'
assert live[0]['emails'] == ['sales@testco1.com'], '实时明细第一家的邮箱不对'
assert live[0]['rating'] == '普通客户' and live[0]['score'] == 65, '实时明细评分/评级不对'
assert live[1]['emails'] == [], '实时明细第二家邮箱应为空'
assert [r['n'] for r in live] == [1, 2, 3], '实时明细序号应为 1/2/3'
# ⛔ 元素必须是完整行（含 snippet / formula / industry）—— /api/export_excel 直接拿它逐条入库，
#    少一个键就会静默写空（例如 industry 丢了 → 结果 Excel 的国家/行业名推断不出来）。
for r in live:
    for k in ('n', 'title', 'url', 'emails', 'phones', 'contact_url', 'score',
              'rating', 'snippet', 'formula', 'industry', 'country'):
        assert k in r, f'待导出明细缺字段：{k}'
print('实时明细 {0} 条，序号 {1}，首条邮箱 {2}'.format(
    len(live), [r['n'] for r in live], live[0]['emails']))

# ---- ③ 此刻客户库里**还没有**这些行（入库推迟到点「导出 Excel」那一刻）----
conn = sqlite3.connect(m.db_path())
conn.row_factory = sqlite3.Row
n_before = conn.execute("SELECT COUNT(*) FROM customers WHERE website LIKE 'https://testco%'"
                        ).fetchone()[0]
conn.close()
assert n_before == 0, f'采集阶段不该写库（实际已写入 {n_before} 条）'

# ---- ④ /api/status 必须带上 rows / pending_export / db_total ----
with m.app.test_client() as c:
    resp = c.get('/api/status?since=0').get_json()
assert 'rows' in resp and len(resp['rows']) == 3, '/api/status 未返回 rows 或条数不符'
assert resp.get('pending_export') is True, '/api/status 未返回 pending_export（前端按钮靠它启用）'
assert resp.get('db_total') is not None, '/api/status 未返回 db_total（库总数徽章无法实时刷新）'
print('接口 /api/status：rows {0} 条，pending_export {1}，db_total {2}'.format(
    len(resp['rows']), resp['pending_export'], resp['db_total']))

# ---- ⑤ 点「📥 导出 Excel」→ 才写客户库 + 落盘 ----
je = export_now()
assert je.get('ok') is True and je.get('saved') is True, f'导出应成功：{je}'
assert len(calls['saved']) == 3, f'导出应落盘 3 条，实际 {len(calls["saved"])}'
for r in calls['saved']:
    for k in ('title', 'url', 'emails', 'phones', 'contact_url', 'score',
              'rating', 'snippet', 'formula', 'country'):
        assert k in r, f'落盘记录缺字段：{k}'
# ⛔ 导出成功后必须清空明细 + 复位状态，否则刷新页面会再导一次（重复入库 + 多出一份表）
assert m.STATE['rows'] == [] and m.STATE['pending_export'] is False, \
    f'导出后应清空明细并复位状态：rows={m.STATE["rows"]} pending={m.STATE["pending_export"]}'

# ---- ⑥ 导出之后，库里才有这 3 条 ----
conn = sqlite3.connect(m.db_path())
conn.row_factory = sqlite3.Row
# 只断言本轮写入的 3 条（init_customer_db 会顺带把项目里旧的结果 Excel 导入临时库，与本次无关）
rows = conn.execute("SELECT company_name,website,email,phone,score,rating,industry "
                    "FROM customers WHERE website LIKE 'https://testco%' ORDER BY website").fetchall()
total = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
conn.close()
print(f'临时库总记录 {total} 条，其中本轮写入 {len(rows)} 条')
assert len(rows) == 3, f'导出后本轮应写入 3 条，实际 {len(rows)}'
for r in rows:
    print('   库内：', dict(r))
assert rows[0]['email'] == 'sales@testco1.com', '抓到邮箱的记录没写进库'
assert rows[0]['industry'] == '宠物用品', '行业标签没写进库'
assert rows[1]['email'] == '', '第二家没有邮箱，应为空'
print(f'落盘条数 {len(calls["saved"])} | 就补全 {len(calls["enriched"])} 次 | '
      f'切回搜索标签 {calls["activate"]} 次 | 关闭浏览器 {calls["quit"]} 次')

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

# ---- 自定义模式（主页第 6 卡）：原样搜索、一个字符都不加、国家只做标记、中国过滤全关 ----
# 用户 2026-10-02 拍板：完全原始查询；目标国家只填结果「国家」列，不进搜索词；与标准模式互斥；
# 只继承「采集数量 + 就地抓联系方式」；**不做**中国商家过滤。
def mk_items(tag):
    """每轮一组：① 会被中国过滤命中的站（.cn 域名 + China manufacturer + cn 邮箱/+86 电话）
    ② 一个干净的法国站。"""
    return [
        {'title': f'China Manufacturer Supplier {tag}', 'url': f'https://cn-supplier-{tag}.cn/',
         'snippet': 'China manufacturer factory in China'},
        {'title': f'Grossiste {tag}', 'url': f'https://grossiste-{tag}.fr/',
         'snippet': 'grossiste importateur'},
    ]


def reset_calls(items):
    global CUR_ITEMS
    CUR_ITEMS = items
    calls['formulas'].clear()
    calls['params'].clear()
    calls['domain_keys'].clear()
    calls['saved'] = None
    # ⛔ 每轮必须互相独立：清空「待导出明细」与行号发号器。
    #    否则 export_now() 会把**前面几轮**攒下的行一起导出（len(calls['saved']) 就不是本轮的了），
    #    而且 run_search 开头会把 n_seq 归零 → 与未清空的 rows 里的旧 n 撞号。
    #    （真实链路不会这样：api_start 每轮都会清 STATE['rows']；直调 run_search 才要自己清。）
    m.STATE.update(rows=[], result_count=0, n_seq=0, pending_export=False, export_error='')


# 对照组：标准模式 + 默认中国过滤（17 项全开）→ 中国那条应当被过滤掉
reset_calls(mk_items('a'))
print('\n---- 对照组：标准模式（中国过滤全开）----')
m.run_search(['nouilles'], ['wholesale'], [('fr', '法国', 'fr', 'fr')], 1,
             '-alibaba', 'or', 1, '食品', True, '', None)
assert calls['saved'] is None, '采集阶段不该落盘'
je = export_now()
assert je.get('ok') is True and je.get('saved') is True, f'导出应成功：{je}'
assert len(calls['saved']) == 1, \
    f'对照组应只留下法国那 1 条，实际 {len(calls["saved"] or [])}'
assert calls['saved'][0]['url'] == 'https://grossiste-a.fr/', \
    f'对照组剩下的应是法国站，实际 {calls["saved"][0]["url"]}'
# ⛔ 标准模式必须**永远**传 domain_keys=None —— 这是「标准模式零行为变化」的硬证据。
#    一旦这里出现非 None，说明新加的域名拦截漏进了标准链路（会把 amazon.de 之类改掉）。
assert calls['domain_keys'] and all(x is None for x in calls['domain_keys']), \
    f'标准模式不该传域名拦截集合：{calls["domain_keys"]}'
print('  ✓ 标准模式下中国站被过滤（对照组成立）；且 domain_keys 恒为 None（标准链路零影响）')

# 实验组：自定义模式 —— 同一组结果，中国那条必须**留下来**
# 改成「每次抽取都返回一批全新域名」的桩，否则第一条查询就达标、后面的查询根本不会跑，
# 断言就看不到第 2 条公式（也不该靠调大 target 硬凑，那样测的是达标逻辑不是公式）。
SEQ = {'n': 0}
CUR_TAG = ['b']


def fake_extract(page, seen_titles, china_filters=None, domain_keys=None):
    # 记下 run_search 真正传下来的「抓取前域名拦截」集合 —— 用来断言自定义模式把勾选项接上了、
    # 标准模式仍然是 None（零影响）。⚠️ 参数必须收 domain_keys，否则 TypeError。
    calls['domain_keys'].append(None if domain_keys is None else sorted(domain_keys))
    SEQ['n'] += 1
    items = mk_items(f'{CUR_TAG[0]}{SEQ["n"]}')
    # ⛔ 桩必须自己复现「第一步：抓取前按域名拦截」——
    #    真实现里这段就在 extract_results 内部（紧挨 is_blocked），这里整函数被桩替换掉，
    #    不复现的话 .cn 站会一路走到第二步，断言就测不到第一步了（第一版踩过）。
    kept, blocked = [], 0
    for it in items:
        if domain_keys and m.domain_rule_hit(it['url'], domain_keys):
            blocked += 1
            continue
        kept.append(it)
    return (kept, blocked, {})


m.extract_results = fake_extract
SEQ['n'] = 0
CUR_TAG[0] = 'b'
reset_calls([])
print('\n---- 实验组：自定义模式 ----')
m.run_search([], [], [('fr', '法国', 'fr', 'fr')], 1,
             '-alibaba -site:.cn', 'or', 4, '食品', True, '',
             None, ['cat litter grossiste', '   ', '"pet food" importer Lyon  '])
print('实际发出的第 1 页公式：')
for f in calls['formulas']:
    print('   ', repr(f))

# ① 原样：空白行丢弃、首尾空格清掉、不加引号、不拼产品词
assert calls['formulas'] == ['cat litter grossiste', '"pet food" importer Lyon'], \
    f'自定义公式不是原样（含空行/空格/引号处理）：{calls["formulas"]}'
# ② 排除词一个都不许拼进来
assert not any('-alibaba' in f or '-site:.cn' in f for f in calls['formulas']), \
    f'自定义模式不该拼排除词：{calls["formulas"]}'
# ③ 国家参数照旧挂 URL（不是进搜索词）
assert all(p == '&gl=fr&hl=fr' for p in calls['params']) and len(calls['params']) == 2, \
    f'国家参数不对：{calls["params"]}'
assert not any(('法国' in f) or ('France' in f) for f in calls['formulas']), \
    f'国家不该写进搜索词：{calls["formulas"]}'
print('  ✓ 公式逐字原样；不拼排除词；国家只走 &gl=&hl=，没进搜索词')

# ④ 落盘行：搜索公式原样、国家列打上「法国」。
# ⛔ 语义 2026-10-19 变了（M24）：自定义模式**不再放过 .cn 站** —— 用户在「5. 参数 · 域名过滤」
#    默认勾了「排除 .cn 域名」，自定义模式现在会拿这些勾选项在**抓取前**按域名挡掉
#    （＝用户说的「第一步排除平台域名、不进入抓取分析」）。所以 cn-supplier-*.cn 两条被挡，
#    只剩两个法国站。（这段原来断言「中国站全部保留」，那是旧语义，已作废。）
je = export_now()                     # ⛔ 新语义：先点「导出 Excel」才落盘
assert je.get('ok') is True and je.get('saved') is True, f'导出应成功：{je}'
saved = calls['saved'] or []
assert len(saved) == 2, f'自定义模式下 .cn 站应被拦截，只剩 2 个法国站，实际 {len(saved)}'
urls = {r['url'] for r in saved}
assert not any(u.endswith('.cn/') for u in urls), f'.cn 站没被第一步挡住：{urls}'
assert urls == {'https://grossiste-b1.fr/', 'https://grossiste-b2.fr/'}, f'留下来的应是两个法国站：{urls}'
assert all(r['formula'] in ('cat litter grossiste', '"pet food" importer Lyon') for r in saved), \
    f'落盘行的搜索公式不是原样：{[r["formula"] for r in saved]}'
assert all(r['country'] == '法国' for r in saved), \
    f'国家列没打上标记：{[r["country"] for r in saved]}'
# 必须证明它是**第一步（域名字段）**挡的：run_search 得把 'cn' 这个 key 传给 extract_results
dk = calls['domain_keys'][-1] if calls['domain_keys'] else None
assert dk and 'cn' in dk, f'自定义模式没把「排除 .cn」的 key 传给 extract_results：{dk}'
print(f'  ✓ .cn 站在抓取前被域名拦截挡掉（domain_keys={dk}）；公式逐字原样；国家列 = 法国')

# ⑤ 与标准模式互斥：自定义模式下传了产品词/条件也不该被使用
SEQ['n'] = 0
CUR_TAG[0] = 'c'
reset_calls([])
m.run_search(['nouilles'], ['wholesale'], [('fr', '法国', 'fr', 'fr')], 1,
             '-alibaba', 'or', 1, '食品', True, '',
             None, ['grossiste alimentaire'])
assert calls['formulas'] == ['grossiste alimentaire'], \
    f'自定义模式应忽略产品词/条件，实际 {calls["formulas"]}'
assert not any('nouilles' in f or 'grossiste OR distributeur' in f for f in calls['formulas']), \
    '自定义模式下产品词/条件词不该出现'
print('  ✓ 互斥成立：自定义模式下产品词与条件词被完全忽略')

# ---- 自定义模式「第一步」：平台域名判定（domain_rule_hit）----
# 用户 2026-10-19：「自定义搜索词的时候，第一步就应该排除这些平台常用的域名，不进入抓取分析。」
# ⚠️ 这里直接单测判定函数 —— extract_results 已被桩掉，拦截逻辑走不到。
#    关键在于「品牌标签按域名段**相等**判」，不是子串（子串会误杀 amazonas.com）。
print('\n---- 自定义模式：平台域名判定 ----')
for _u, _k, _want in [
    ('https://www.alibaba.com/x', 'alibaba', 'alibaba'),            # 主域
    ('https://alibaba.co.uk/x', 'alibaba', 'alibaba'),              # 国别变体
    ('https://www.amazon.de/dp/B0', 'amazon', 'amazon'),            # ⛔ is_blocked 挡不住的那个
    ('https://sellercentral.amazon.co.uk/x', 'amazon', 'amazon'),   # 子域也算
    ('https://amazonas.com/', 'amazon', None),                      # ⛔ 不能误杀（亚马逊州）
    ('https://my-ebay-shop.com/', 'ebay', None),                    # ⛔ 不能子串命中
    ('https://de.wikipedia.org/', 'wikipedia', 'wikipedia'),
    ('https://shop.example.cn/', 'cn', 'cn'),
    ('https://normal-shop.fr/', 'amazon', None),
]:
    _got = m.domain_rule_hit(_u, {_k})
    assert _got == _want, f'{_u} 用 {_k} 判定应为 {_want}，实际 {_got}'
assert m.domain_rule_hit('https://alibaba.com/', set()) is None, '没有勾选项时不该挡任何站'
assert m.domain_rule_hit('https://alibaba.com/', {'wechat'}) is None, \
    '非域名类 key（wechat）不该被当域名判据'
print('  ✓ 段相等判据：amazon.de / alibaba.co.uk / sellercentral.* 命中；amazonas.com / my-ebay-shop.com 不误杀')

# ---- 自定义模式「第二步」：联系方式命中「只标记、不删行」----
# 用户 2026-10-19：「拿到联系方式，再进行联系方式过滤，联系方式过滤只做标记不做删除。」
# 造一个**不是 .cn** 的站 + 标题带 WeChat → 第一步挡不住，第二步必须命中标记、且行必须留下。
MARK_ITEMS = [{'title': 'Grossiste animaux WeChat', 'url': 'https://wechat-shop-x.fr/',
               'snippet': 'grossiste'}]


def fake_extract_mark(page, seen_titles, china_filters=None, domain_keys=None):
    calls['domain_keys'].append(None if domain_keys is None else sorted(domain_keys))
    return (MARK_ITEMS, 0, {})


m.extract_results = fake_extract_mark
reset_calls([])
m.run_search(['x'], [], [('fr', '法国', 'fr', 'fr')], 1, '', 'or', 1, '食品', True, '',
             None, ['grossiste animaux wechat'])
_rows = m.STATE['rows']
assert len(_rows) == 1, f'联系方式命中不该删行（只标记）：{len(_rows)} 条'
assert _rows[0]['marks'] == ['微信'], f'标记不对：{_rows[0].get("marks")}'
assert m.STATE['pending_export'] is True, '只标记时仍应进入「待导出」'
# Excel 摘要列必须带前缀，且**仍是 10 列**（飞书/建库按下标读，列数不能变）
_r10 = m._row10(_rows[0])
assert len(_r10) == 10, f'结果 Excel 必须仍是 10 列，实际 {len(_r10)}'
assert _r10[7].startswith('[标记] 微信 · '), f'摘要列没带标记前缀：{_r10[7]}'
_je = export_now()
_sv = calls['saved'] or []
assert len(_sv) == 1 and _sv[0]['marks'] == ['微信'], f'导出丢了标记：{_sv}'
print('  ✓ 联系方式命中：行保留 + marks=["微信"] + 摘要列「[标记] 微信 · …」（仍 10 列）')

# 对照：把「联系方式过滤」全部取消 → 不该产生任何标记
# ⚠️ 必须换一个未入库的新域名：上一段已经 export 过，同一个站会被「客户库已有」直接跳过、
#    rows 变成空列表（第一版踩过，断言会假红）。
MARK_ITEMS = [{'title': 'Grossiste animaux WeChat y', 'url': 'https://wechat-shop-y.fr/',
               'snippet': 'grossiste'}]
m.extract_results = fake_extract_mark
reset_calls([])
m.run_search(['x'], [], [('fr', '法国', 'fr', 'fr')], 1, '', 'or', 1, '食品', True, '', [],
             ['grossiste animaux wechat'])
assert m.STATE['rows'] and m.STATE['rows'][0]['marks'] == [], \
    f'没勾联系方式过滤时不该标记：{m.STATE["rows"]}'
print('  ✓ 联系方式过滤全部取消时不产生标记（勾选才判）')

# ---- 国家限定（主页第 4 步，可选，默认关）：cr 只挂 URL、site: 只进搜索词、美国不加 site: ----
# 用户 2026-10-02 拍板：做一个四选一分支（none 默认 / cr / site / both），只对标准网页模式生效。
# ⚠️ 断言里的 site: 要写全后缀（'site:.fr'）—— 默认中国过滤会往公式里拼 '-site:.cn'，
#    光判 'site:' 会假红。
FR = [('fr', '法国', 'fr', 'fr')]
US = [('us', '美国', 'us', 'en')]
IR = [('ir', '伊朗', 'ir', 'fa')]
CAF = [('ca_fr', '加拿大(法语)', 'ca', 'fr')]


def cl_run(tag, countries, limit=None, raws=None, target=1):
    """跑一轮并返回 (formulas, params)。limit=None → **完全不传** country_limit，
    以此验证「默认参数」路径与原行为逐字一致。"""
    SEQ['n'] = 0
    CUR_TAG[0] = tag
    reset_calls([])
    pos = (['nouilles'], ['wholesale'], countries, 1, '-alibaba', 'or', target, '食品', True, '')
    kw = {}
    if raws is not None:
        kw['raw_queries'] = raws
    if limit is not None:
        kw['country_limit'] = limit
    m.run_search(*pos, **kw)
    assert calls['formulas'], f'[{tag}] 一条公式都没发出'
    return list(calls['formulas']), list(calls['params'])


print('\n---- 国家限定 ----')
f_none, p_none = cl_run('cl0', FR)
assert p_none == ['&gl=fr&hl=fr'], f'默认（不传）不该加 cr：{p_none}'
assert 'site:.fr' not in f_none[0], f'默认（不传）不该加 site:：{f_none}'
print(f'  ✓ 默认不传参 = 原行为逐字一致：{p_none[0]}')

f_cr, p_cr = cl_run('cl1', FR, limit='cr')
assert p_cr[0] == '&gl=fr&hl=fr&cr=countryFR', f'cr 模式参数不对：{p_cr}'
assert 'site:.fr' not in f_cr[0], f'cr 模式不该动搜索词：{f_cr}'
print(f'  ✓ cr 只挂 URL：{p_cr[0]}（搜索词不变）')

f_site, p_site = cl_run('cl2', FR, limit='site')
assert p_site[0] == '&gl=fr&hl=fr', f'site 模式不该加 cr：{p_site}'
assert ' site:.fr' in f_site[0], f'site 模式没把后缀拼进搜索词：{f_site}'
print(f'  ✓ site: 只进搜索词：{f_site[0][:70]}…')

f_both, p_both = cl_run('cl3', FR, limit='both')
assert p_both[0] == '&gl=fr&hl=fr&cr=countryFR', f'both 模式参数不对：{p_both}'
assert ' site:.fr' in f_both[0], f'both 模式搜索词没加后缀：{f_both}'
print('  ✓ both = 两者同时生效')

# 美国：site 留空（.com 为主、.us 极少）→ site 模式下公式应与「不改」完全相同；cr 仍有效
f_us_none, _ = cl_run('cl4', US)
f_us_site, _ = cl_run('cl5', US, limit='site')
assert f_us_site == f_us_none, \
    f'美国不该加 site:（公式应与默认一致）：{f_us_site} vs {f_us_none}'
_, p_us_cr = cl_run('cl6', US, limit='cr')
assert p_us_cr[0].endswith('&cr=countryUS'), f'美国 cr 应有效：{p_us_cr}'
print('  ✓ 美国：site: 自动跳过（公式与默认一致），cr 照常生效')

# 伊朗不在谷歌 cr 支持列表 → cr 留空，cr 模式下参数应与默认一致
_, p_ir_none = cl_run('cl7', IR)
_, p_ir_cr = cl_run('cl8', IR, limit='cr')
assert p_ir_cr == p_ir_none, f'伊朗 cr 应留空不拼：{p_ir_cr} vs {p_ir_none}'
print('  ✓ 伊朗（不在 cr 支持列表）cr 自动跳过')

# 非 ISO 内部代码 ca_fr → 映射到加拿大
_, p_cafr = cl_run('cl9', CAF, limit='cr')
assert p_cafr[0].endswith('&cr=countryCA'), f'ca_fr 应映射 countryCA：{p_cafr}'
print('  ✓ ca_fr（内部代码）→ cr=countryCA')

# 非法值静默回落 none（与其它参数的容错口径一致）
_, p_bad = cl_run('cl10', FR, limit='乱写')
assert p_bad == ['&gl=fr&hl=fr'], f'非法限定值应回落 none：{p_bad}'
print('  ✓ 非法限定值静默回落 none')

# 互斥：自定义模式下即使传了 both 也不加（cr 不进 URL、site: 不进搜索词）
f_raw, p_raw = cl_run('cl11', FR, limit='both', raws=['cat litter grossiste'])
assert f_raw == ['cat litter grossiste'], f'自定义模式应原样：{f_raw}'
assert p_raw == ['&gl=fr&hl=fr'], f'自定义模式不该加 cr：{p_raw}'
print('  ✓ 互斥：自定义模式下国家限定被完全关掉')

# ---- 运行中删除 → 那条**不进结果 Excel**（只动内存明细） ----
# 背景（2026-10-13 新语义）：采集阶段既不写库也不落盘，`STATE['rows']` 本身就是「待导出的那一份」。
# 所以页面上点 ✕ 只要从 `STATE['rows']` 里摘掉即可 —— 导出时自然就不会带上它。
# （旧实现靠 `STATE['rows_deleted']` 记「墓碑」，让 worker 的 finally 按 n 过滤后再落盘；
#   现在 per-round 的落盘被整个挪到 /api/export_excel，墓碑机制已**整套下线**。）
# 这段走的是**真实路径**：采集跑到第 2 条时，用 flask test_client 真打一次 /api/live/delete。
# ⚠️ 必须放在下面「/api/start 的 HTTP 层」之前 —— 那一段会把 m.run_search 换成假实现。
# ⚠️ 删除接口要求 running and phase=='search'（或 pending_export），所以这里得先把 STATE 摆成「采集中」。
#    （run_search 的 finally 会自己把 running 置回 False，不用手动复位。）
LIVE_ITEMS = [{'title': f'Live Co {i}', 'url': f'https://liveco{i}.example.com/',
               'snippet': 'wholesale distributor'} for i in (1, 2, 3)]
LIVE_DEL = {'jd': None, 'enrich_n': 0}


def fake_extract_live(page, seen_titles, china_filters=None, domain_keys=None):
    # 一页直接给够 3 条，跑一轮就达标（不要靠多页凑，否则断言看不到「第 2 条处理时删第 1 条」）
    # ⚠️ 必须收 domain_keys（run_search 会传第 4 个参数），这一轮是标准模式 → 恒为 None。
    calls['domain_keys'].append(None if domain_keys is None else sorted(domain_keys))
    return (list(LIVE_ITEMS), 0, {})


def fake_enrich_live(page, url):
    calls['enriched'].append(url)
    # ⚠️ 不能用 len(calls['enriched']) 当计数：reset_calls() 只清 saved/formulas/params，不清 enriched，
    #    整脚本跑下来它是累积的，永远等不到第 2 次。
    LIVE_DEL['enrich_n'] += 1
    if LIVE_DEL['enrich_n'] == 2:
        # 第 2 条正在处理时，模拟用户在上面的实时明细里点了第 1 条的 ✕。
        # （此时 worker 没持 STATE_LOCK —— enrich 的调用点在锁外，不会死锁。）
        with m.app.test_client() as c:
            LIVE_DEL['jd'] = c.post('/api/live/delete', json={'n': 1}).get_json()
    return {'emails': [], 'phones': [], 'contact_url': ''}


print('\n---- 运行中删除 → 不进结果 Excel ----')
_orig_extract = m.extract_results
_orig_enrich = m.enrich
m.extract_results = fake_extract_live
m.enrich = fake_enrich_live
LIVE_DEL['enrich_n'] = 0
reset_calls([])
m.STATE.update(running=True, phase='search', rows=[], n_seq=0, result_count=0,
               output='', stop=False, pending_export=False)
m.run_search(['cat litter'], ['wholesale'], FR, 1, '-alibaba', 'or', 3, '食品', True)
jd = LIVE_DEL['jd'] or {}
assert jd.get('ok') is True, f'采集进行中删一条应成功：{jd}'
# ⛔ 新语义：这些行**还没入库**，所以删除只动内存明细 —— deleted 必须恒为 0、也没有备份。
assert jd.get('deleted') == 0, f'新语义只删内存、不碰客户库，deleted 应恒为 0：{jd}'
assert jd.get('backup') == '', f'新语义没有删前备份这回事：{jd}'
assert len(m.STATE['rows']) == 2, f'内存明细应剩 2 条：{len(m.STATE["rows"])}'
assert [r['n'] for r in m.STATE['rows']] == [2, 3], f'应剩下 n=2,3：{m.STATE["rows"]}'
assert m.STATE['result_count'] == 2, \
    f'计数应跟着表格走（否则「本轮已采 N 个网站」比表格多 1）：{m.STATE["result_count"]}'
# 跑完进入「待核对」—— 明细停在 2 条，等用户核对完再点导出
assert m.STATE['pending_export'] is True, '跑完应进入「待导出」状态'
assert calls['saved'] is None, '采集阶段不该落盘（落盘要等点「导出 Excel」）'
# 点「📥 导出 Excel」→ 落盘只有 2 条，且不含被删那条
je = export_now()
assert je.get('ok') is True and je.get('saved') is True, f'导出应成功：{je}'
saved = calls['saved'] or []
assert len(saved) == 2, f'删掉 1 条后落盘应只剩 2 条（删内存没生效就会是 3）：{len(saved)}'
saved_urls = {r['url'] for r in saved}
assert 'https://liveco1.example.com/' not in saved_urls, \
    f'被删的那条仍进了结果 Excel（＝假删除）：{saved_urls}'
assert saved_urls == {'https://liveco2.example.com/', 'https://liveco3.example.com/'}, \
    f'留下来的应该是第 2、3 条：{saved_urls}'
print('  ✓ 采集中删掉第 1 条：只动内存（deleted=0、无备份）→ 明细剩 2 条、计数 2，'
      '导出后落盘 2 条且不含被删那条')
m.extract_results = _orig_extract
m.enrich = _orig_enrich
m.STATE.update(rows=[], n_seq=0, result_count=0, pending_export=False)

# ---- /api/start 的 HTTP 层：自定义词要真能送进去，且「产品词必填」这条校验要跟着放宽 ----
# 用「打桩 worker」验证**参数传递**（不起真线程、不联网、不写库）：
# api_start 里的 threading.Thread(target=run_search, ...) 是在调用时才查全局名，
# 所以替换 m.run_search / m.run_maps 就能把它截住。
spy_run = {'args': None, 'kw': None}
spy_maps = {'args': None, 'kw': None}


def fake_run_search(*a, **kw):
    spy_run['args'] = a
    spy_run['kw'] = kw


def fake_run_maps(*a, **kw):
    spy_maps['args'] = a
    spy_maps['kw'] = kw


m.run_search = fake_run_search
m.run_maps = fake_run_maps


def post_start(payload):
    m.STATE['running'] = False      # api_start 成功一次就会把 running 置 True，逐次复位
    with m.app.test_client() as c:
        return c.post('/api/start', json=payload).get_json()


print('\n---- /api/start：采集数量强必填 + 自定义词的参数传递与校验 ----')
# ⓪ 采集数量（主页第 1 卡）**强必填**：缺字段 / 空串都必须被拒，绝不能静默按 10 跑
#    （旧行为是 data.get('target_count', 10) → 缺键静默取 10，等于没必填）。
#    ⚠️ 这三条都要带上 products，否则会先撞上「产品关键词」那条校验、根本测不到这一条。
r = post_start({'products': 'x'})
assert not r.get('ok') and '本次任务采集数量' in r.get('msg', ''), \
    f'缺 target_count 应被拒（旧行为是静默取 10）：{r}'
r = post_start({'products': 'x', 'target_count': ''})
assert not r.get('ok') and '本次任务采集数量' in r.get('msg', ''), f'空串 target_count 应被拒：{r}'
r = post_start({'products': 'x', 'target_count': 10})
assert r.get('ok'), f'带合法 target_count 应放行：{r}'
print('  ✓ 采集数量强必填：缺字段 / 空串都被拒（不再静默取 10），带合法值才放行')
# ① 只填自定义词、产品词留空 → 必须放行（否则前端等于逼用户填一个用不上的产品词）
spy_run['kw'] = None
r = post_start({'products': '', 'target_count': 10, 'custom_queries':
                ['cat litter grossiste', '   ', 'cat litter grossiste', 123]})
assert r.get('ok'), f'只填自定义词应放行，实际：{r}'
assert spy_run['kw'] and spy_run['kw'].get('raw_queries') == ['cat litter grossiste'], \
    f'自定义词没传给 run_search（或空行/重复/非字符串没清干净）：{spy_run["kw"]}'
print('  ✓ 只填自定义词即可开始；空行/重复/非字符串已清洗后再传给 run_search')
# ② 两边都空 → 仍然要拦住（别把老校验一起放没了）
r = post_start({'products': '', 'target_count': 10, 'custom_queries': []})
assert not r.get('ok') and '产品关键词' in r.get('msg', ''), f'两边都空应拦住，实际：{r}'
print('  ✓ 产品词与自定义词都空时仍然拦住（老校验没被放没）')
# ③ 超上限 → 拒绝（防误粘一大段文本把整轮拖成几小时）
r = post_start({'products': 'x', 'target_count': 10,
                'custom_queries': [f'q{i}' for i in range(m.RAW_QUERY_MAX + 1)]})
assert not r.get('ok') and str(m.RAW_QUERY_MAX) in r.get('msg', ''), f'超上限应拒绝，实际：{r}'
print(f'  ✓ 超过 {m.RAW_QUERY_MAX} 条直接拒绝')
# ④ 地图模式 → 自定义词被忽略，且不许塞给 run_maps
spy_run['kw'] = None
spy_maps['kw'] = None
r = post_start({'products': 'x', 'target_count': 10, 'custom_queries': ['zzz'], 'source': 'maps'})
assert r.get('ok'), f'地图模式应正常开始，实际：{r}'
assert spy_maps['kw'] is not None, '地图模式没走 run_maps'
assert spy_run['kw'] is None, '地图模式不该调用 run_search'
assert 'raw_queries' not in (spy_maps['kw'] or {}), '自定义词被塞给了 run_maps（地图不用它）'
assert 'country_limit' not in (spy_maps['kw'] or {}), '国家限定被塞给了 run_maps（地图不用它）'
print('  ✓ 地图模式下自定义词与国家限定都被忽略（仍走 run_maps）')
# ⑤ 国家限定：透传给 run_search；非法值回落 none
spy_run['kw'] = None
r = post_start({'products': 'x', 'target_count': 10, 'country_limit': 'both'})
assert r.get('ok'), f'带国家限定应正常开始，实际：{r}'
assert spy_run['kw'].get('country_limit') == 'both', \
    f'国家限定没透传给 run_search：{spy_run["kw"]}'
spy_run['kw'] = None
post_start({'products': 'x', 'target_count': 10, 'country_limit': '乱写'})
assert spy_run['kw'].get('country_limit') == 'none', \
    f'非法限定值应回落 none：{spy_run["kw"]}'
print('  ✓ 国家限定透传给 run_search；非法值回落 none')

# ⑥ 「排除条件」的 **key** 数组要透传给 run_search —— 自定义模式的「第一步：抓平台域名」靠它。
# （amazon / ebay / etsy / wikipedia / youtube / facebook 这 6 项在自定义模式不拼搜索词，
#   只走域名拦截 —— 见 domain_rule_hit。temu 走 CHINA_FILTER_OPTIONS，同样只做域名拦截。）
spy_run['kw'] = None
post_start({'products': 'x', 'target_count': 10,
            'exclude_keys': ['amazon', 'ebay', '不是一个真 key']})
assert spy_run['kw'].get('exclude_keys') == ['amazon', 'ebay'], \
    f'exclude_keys 没透传或没走白名单：{spy_run["kw"]}'
spy_run['kw'] = None
post_start({'products': 'x', 'target_count': 10})
assert spy_run['kw'].get('exclude_keys') == [], \
    f'缺省时 exclude_keys 应是空列表（下游 set(...) 才不会炸）：{spy_run["kw"]}'
print('  ✓ 排除条件的 key 透传并过白名单；缺省是空列表')

# ---- /api/live/delete 的 HTTP 层：窗口校验、只删内存明细（不碰客户库）----
# ⛔ 语义 2026-10-13 变了：采集阶段不写库，所以删除**只动内存明细** —— deleted 恒为 0、无删前备份。
# 仍要盯住三条静默失效：① 已导出后还放行（那时该去客户库查询页整批清理）；
#                      ② 非法/缺失行号被当成合法（`n=True` 在 Python 里是 1，会误删第一条）；
#                      ③ 不该删的窗口（导出飞书 phase=='export'）被放行。
print('\n---- /api/live/delete：主页实时明细逐行删除 ----')
# 故意先往（临时）库里塞两条 —— 用来证明**删除不会碰客户库**：新语义下它俩必须原封不动。
# （顺带覆盖「删明细误伤同域名的库内记录」这种误删。）
m.db_upsert_customer({'company_name': 'Live Del One', 'website': 'https://live-del-1.it/',
                      'snippet': 'x', 'search_formula': 'f', 'country': '意大利', 'industry': '食品'})
m.db_upsert_customer({'company_name': 'Live Keep Two', 'website': 'https://live-keep-2.it/',
                      'snippet': 'x', 'search_formula': 'f', 'country': '意大利', 'industry': '食品'})
assert m.db_has_customer('https://live-del-1.it/'), '前置：第 1 条已（人为）在库'
assert m.db_has_customer('https://live-keep-2.it/'), '前置：第 2 条已（人为）在库'


def live_row(n, title, url, score=50):
    return {'n': n, 'title': title, 'url': url, 'emails': [], 'phones': [], 'contact_url': '',
            'score': score, 'rating': '普通客户' if score >= 50 else '观察',
            'snippet': 'x', 'formula': 'f', 'industry': '食品', 'country': '意大利'}


LIVE_ROWS = [live_row(1, 'Live Del One', 'https://live-del-1.it/'),
             live_row(2, 'Live Keep Two', 'https://live-keep-2.it/'),
             live_row(3, 'Live No Db', 'https://live-nodb-3.it/', score=10)]


def live_post(payload, running=True, phase='search', pending=False):
    """打一次删除接口，并先把 STATE 摆成指定的运行态 / 待导出态。"""
    m.STATE.update(running=running, phase=phase, pending_export=pending)
    with m.app.test_client() as c:
        return c.post('/api/live/delete', json=payload).get_json()


def live_reset():
    m.STATE.update(rows=[dict(r) for r in LIVE_ROWS], result_count=3, n_seq=3,
                   running=True, phase='search', pending_export=False)


live_reset()
# ① 采集已结束、且没进「待导出」→ 必须拒绝（该去客户库查询页整批清理）
jr = live_post({'n': 1}, running=False, phase='', pending=False)
assert jr.get('ok') is False, f'采集已结束（也没待导出）时不该放行：{jr}'
# ② 导出飞书阶段 → 也必须拒绝（running 是 True，但 phase='export'、结果 Excel 早写好了）
jex = live_post({'n': 1}, running=True, phase='export', pending=False)
assert jex.get('ok') is False, f'导出飞书阶段不该放行：{jex}'
# ③ 非法/缺失行号一律拒绝，且不许动数据
for _bad in ({}, {'n': 'abc'}, {'n': True}, {'n': 0}, {'n': -1}, {'n': None}):
    jb = live_post(_bad)
    assert jb.get('ok') is False, f'非法入参应拒绝：{_bad} → {jb}'
    assert len(m.STATE['rows']) == 3, f'被拒的请求不该动明细：{_bad}'
jsome = live_post({'n': 999})
assert jsome.get('ok') is False, f'删不存在的行号应拒绝：{jsome}'
print('  ✓ 采集已结束 / 导出飞书阶段 / 非法与缺失行号 / 不存在的行号 —— 全部拒绝且不动数据')

# ④ 采集中合法删除：只删内存、deleted=0、无备份、客户库原封不动
live_reset()
jd = live_post({'n': 1})
assert jd.get('ok') is True, f'采集中删一条应成功：{jd}'
assert jd.get('deleted') == 0, f'新语义：只删内存、不碰客户库，deleted 应恒为 0：{jd}'
assert jd.get('backup') == '', f'新语义：不再有删前备份：{jd}'
assert jd.get('rows') == 2, f'删完明细应剩 2 条：{jd}'
assert [r['n'] for r in m.STATE['rows']] == [2, 3], \
    f'内存明细应剩下 n=2,3（按 n 精确删、不连坐）：{m.STATE["rows"]}'
assert m.STATE['result_count'] == 2, f'计数应跟着表格走：{m.STATE["result_count"]}'
assert m.db_has_customer('https://live-del-1.it/') is True, \
    '⛔ 删明细不许碰客户库 —— 库里那条是别的来路进来的，动了就是误删'
assert m.db_has_customer('https://live-keep-2.it/') is True, '没被删的那条当然也不该动'
print('  ✓ 只删内存明细（deleted=0、无备份）：明细剩 n=2,3、计数 2、客户库两条都原封不动')

# ⑤ 采集结束、进入「待导出」→ **仍然可以删**（用户当场核对：一边看一边删，再点导出）
live_reset()
jpend = live_post({'n': 2}, running=False, phase='', pending=True)
assert jpend.get('ok') is True and jpend.get('deleted') == 0, \
    f'「待导出」窗口应放开删除 —— 这正是本次改造的核心用法：{jpend}'
assert [r['n'] for r in m.STATE['rows']] == [1, 3], f'应删掉 n=2：{m.STATE["rows"]}'
print('  ✓ 采集结束、待核对窗口仍可删（用户点名要的用法）')

# ⑥ 逐条删空：计数归零；再删不存在的行号被拒（绝不退化成清空客户库）
live_reset()
for _n in (1, 2, 3):
    live_post({'n': _n})
assert m.STATE['rows'] == [], f'明细应被删空：{m.STATE["rows"]}'
assert m.STATE['result_count'] == 0, f'删空后计数应归零：{m.STATE["result_count"]}'
jn = live_post({'n': 1})
assert jn.get('ok') is False, f'已删空后再删应拒绝：{jn}'
print('  ✓ 逐条删空后计数归零；再删已不存在的行号被拒（绝不退化成清空客户库）')
m.STATE.update(rows=[], n_seq=0, result_count=0, running=False, phase='', pending_export=False)

# ⑦ 主页「上次参数」记忆（2026-10-20）：/api/ui_prefs 落临时目录、白名单、坏文件回落
#    用户：「1、2、4、5 的卡片功能参数保留上一次记忆功能」。这里只测后端契约；
#    前端「库就绪后再恢复」的顺序由 _check_page.py R15 静态钉住。
prefs_file = m.ui_prefs_path()
assert _under_tmp(prefs_file), f'ui_prefs 没落在临时目录（会把真实记忆写脏）：{prefs_file}'
with m.app.test_client() as c:
    r = c.get('/api/ui_prefs')
    assert r.status_code == 200 and r.get_json() == {}, \
        f'文件不存在时应返回空对象：{r.status_code} {r.get_data(as_text=True)}'
    payload = {'targetCount': '50', 'country': 'fr', 'industry': '宠物用品',
               'category': '猫砂', 'product': '猫砂盆', 'lang': 'fr',
               'conds': ['wholesaler'], 'source': 'maps', 'mapsCity': 'Lyon',
               'pages': '3', 'countryLimit': 'cr', 'autoEnrich': False,
               'excludes': ['amazon'], 'chinaFilters': ['taobao'],
               'contactFilters': ['wechat'],
               '不是白名单': 'x', 'products': 'Cat Litter'}      # 后两个必须被丢掉
    r = c.post('/api/ui_prefs', json=payload)
    assert r.status_code == 200 and r.get_json().get('ok') is True, \
        f'保存失败：{r.status_code} {r.get_data(as_text=True)}'
    with open(prefs_file, encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['targetCount'] == '50' and saved['country'] == 'fr', f'关键字段没存上：{saved}'
    assert saved['conds'] == ['wholesaler'] and saved['contactFilters'] == ['wechat'], \
        f'勾选数组没存对：{saved}'
    assert saved['autoEnrich'] is False and saved['pages'] == '3', f'布尔/数字字段丢了：{saved}'
    assert '不是白名单' not in saved, f'非白名单字段被写进文件：{saved}'
    assert 'products' not in saved, '卡 3「产品关键词」被记忆了（用户只点了 1/2/4/5）'
    r = c.get('/api/ui_prefs')
    assert r.get_json().get('industry') == '宠物用品', f'GET 回读不一致：{r.get_json()}'
    # 坏 JSON：一律当「没有记忆」，不许 500（否则页面一加载就报错）
    with open(prefs_file, 'w', encoding='utf-8') as f:
        f.write('{oops')
    r = c.get('/api/ui_prefs')
    assert r.status_code == 200 and r.get_json() == {}, '坏文件应静默回落空对象'
    # 非对象 body：必须 400，不能把数组当 dict 存
    r = c.post('/api/ui_prefs', data='[1,2]', content_type='application/json')
    assert r.status_code == 400, f'非对象请求体应 400，实际 {r.status_code}'
print('  ✓ /api/ui_prefs：落临时目录、只存白名单（products 不入）、GET 回读、坏文件回落空对象')

print('\n✅ 冒烟测试全部通过')

shutil.rmtree(TMP, ignore_errors=True)
