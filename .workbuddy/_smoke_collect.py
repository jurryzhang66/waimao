# -*- coding: utf-8 -*-
"""打桩冒烟测试：不联网、不开浏览器，验证「手动采集」闭环。

与 _smoke_maps.py 同套路：加载主工具后把浏览器/enrich/requests 换成假实现，
只让 collect_from_html 的「三级抓取 → 评分 → 计入本轮明细」跑起来。
数据库与结果文件都指向临时目录，绝不触碰真实客户库。

覆盖 7 条：
  ① 秒级命中（HTML 里有 mailto）→ 不入浏览器、**不写库**，只进本轮明细；采集阶段不碰结果文件
  ①b 传入本轮产品词 → 拿回评分里那 +10
  ② 同一网址再采一次 → 命中「本轮内去重」（此刻它还没入库，靠内存明细挡），且不触发升级
  ③ HTML 无邮箱 + 联系页也抓不到 → 自动升级到 Chromium（enrich 恰好 1 次）
  ④ 结束本轮 _flush_manual_session() → **先入库**、再新建一份 10 列结果文件（降序），指向它
  ⑤ 落盘失败（Excel 被占用）→ 保留本轮数据 + session_error，恢复后可重试成功
  ⑥ 路由层：/api/collect 缺 X-DP-Ext 必须 403
  ⑦ 库内校验：手动采集的 5 条都在库、source=手动采集、迁移种子行不受影响
  ⑧ 删除单条明细：本轮还没入库 → 只动内存明细、不碰库、不产备份、被删的既不进 Excel 也不进库
  ⑨ clean_emails 误报过滤（资源名 / 埋点 DSN 全挡、真邮箱零误杀）
"""
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile

from openpyxl import load_workbook

SRC = r'D:\waimao\dp\客户开发工具.py'
spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

TMP = tempfile.mkdtemp(prefix='smoke_collect_')
OUT = os.path.join(TMP, 'output')
os.makedirs(OUT, exist_ok=True)

# ⚠️ 主程序已拆出 core/ 包：真正建连接的是 core/db.py 的 db_connect()，它调的是 core.db.db_path()。
# 只补 m.db_path 打不到 core.db 内部 —— 假公司会被写进**真实客户库** DB/客户库.sqlite3。
m.db_path = lambda: os.path.join(TMP, 'test.sqlite3')
m.db.db_path = m.db_path
# 结果 Excel 也指向临时目录；每次调用给一个新文件名，方便验证「本轮一份新文件」
_out_n = [0]


def fake_ts_result_path(industry='', country=''):
    _out_n[0] += 1
    return os.path.join(OUT, f'r{_out_n[0]}.xlsx')


m.ts_result_path = fake_ts_result_path
# ⚠️ _save_enrich_excel 里用的是 core.paths.ENRICH_FILE（活变量），必须打在 core.paths 上
m.paths.ENRICH_FILE = os.path.join(OUT, 'main.xlsx')


def _under_tmp(p):
    return os.path.commonpath([os.path.realpath(p),
                               os.path.realpath(TMP)]) == os.path.realpath(TMP)


assert _under_tmp(m.db.db_path()), f'core.db.db_path 未指向临时目录：{m.db.db_path()}'
assert _under_tmp(m.db_path()), f'入口 db_path 未指向临时目录：{m.db_path()}'
assert _under_tmp(m.ts_result_path('x', 'y')), f'ts_result_path 未指向临时目录'
assert _under_tmp(m.paths.ENRICH_FILE), f'ENRICH_FILE 未指向临时目录'
print('打桩护栏 OK：', m.db.db_path())

calls = {'enrich': [], 'browser': 0, 'req': 0}


class FakePage:
    def quit(self):
        pass


m.create_browser_page = lambda: FakePage()
m._manual_browser = lambda: FakePage()
m.sleep_check = lambda seconds: True


def fake_enrich(page, url):
    calls['enrich'].append(url)
    # ⚠️ 邮箱必须**按域名给**：db_upsert_customer 在 website_key 未命中时会用 lower(email)
    #    兜底匹配，所有网址给同一个邮箱会让两条不同域名被合并成一条。
    host = m.normalize_domain(url)
    return {'emails': [f'sales@{host}'], 'phones': [],
            'contact_url': url + '/contact', 'china_signal_text': ''}


m.enrich = fake_enrich


class FakeRequests:
    """第②级（requests 抓联系页）打桩：全部失败 → 逼它走第③级升级路径。"""

    @staticmethod
    def get(*a, **k):
        calls['req'] += 1
        raise OSError('stubbed network failure')


m.requests = FakeRequests()

m.MANUAL_STATE.update({'running': False, 'stop': False, 'total': 0, 'done': 0,
                       'added': 0, 'existed': 0, 'failed': 0, 'upgraded': 0,
                       'current': '', 'ext_last_seen': 0.0,
                       'session_active': False, 'session_started_at': 0.0,
                       'session_rows': [], 'session_rid_seq': 0,
                       'session_industry': '', 'session_country': '',
                       'session_excel': '', 'session_error': '',
                       'session_finish_pending': False})
m.STATE['running'] = False

# ---- 先铺一份「上一轮自动搜索结果」的 Excel：1 行、评分 40。它应当**始终不被手动采集碰到** ----
seed = {'title': 'Seed Co', 'url': 'https://seed.com', 'emails': [], 'phones': [],
        'contact_url': '', 'score': 40, 'rating': '观察', 'snippet': '种子行',
        'formula': '[手动采集] https://seed.com', 'country': '法国', 'industry': '塑料包装袋'}
m._save_enrich_excel([seed], industry='塑料包装袋')
assert os.path.exists(m.paths.ENRICH_FILE), '初始结果文件没建出来'
SEED_PATH = m.paths.ENRICH_FILE
SEED_OUTPUT = m.STATE['output']
print('上一轮结果文件：', os.path.basename(SEED_PATH))
# 模拟「工具启动」：init_customer_db 在**库为空**时会把现有结果 Excel 迁移导入一次。
# 这是真实行为，先手动跑掉它，后面的断言才是确定的（否则第一次采集时才触发导入）。
m.init_customer_db()


def excel_rows(path):
    wb = load_workbook(path)
    ws = wb.active
    head = [c.value for c in ws[1]]
    data = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    wb.close()
    return head, data


print('\n================ ① 秒级命中：HTML 里有 mailto ================')
HTML_MAIL = ('<html><head><title>Trash Bags Wholesale Supplier</title>'
             '<meta name="description" content="Leading wholesale trash bag manufacturer"></head>'
             '<body><script>var x=1</script><p>Contact us</p>'
             '<a href="mailto:info@plasticbagpc.com">info@plasticbagpc.com</a>'
             '<a href="/contact-us">Contact</a></body></html>')
r1 = m.collect_from_html('https://plasticbagpc.com', 'Trash Bags Wholesale Supplier', HTML_MAIL)
print('结果：', {k: v for k, v in r1.items() if k != 'row'})
assert r1['ok'] and r1['added'] and not r1['existed'], f'第一条应新增：{r1}'
assert r1['tier'] == 1, f'应走①级秒级路径，实际 {r1["tier"]}'
assert r1['upgraded'] is False, '秒级命中不该升级'
assert calls['enrich'] == [], f'①级路径绝不该开浏览器，实际调用 enrich：{calls["enrich"]}'
assert calls['req'] == 0, f'①级路径不该发 HTTP 请求，实际 {calls["req"]} 次'
assert r1['row']['emails'] == ['info@plasticbagpc.com'], f'邮箱没抽到：{r1["row"]["emails"]}'
assert r1['row']['industry'] == '塑料包装袋', f'行业没自动判出来：{r1["row"]["industry"]}'
assert r1['row']['snippet'].startswith('Leading wholesale'), '摘要没取到 meta description'
assert r1['row']['formula'] == '[手动采集] https://plasticbagpc.com', '标签公式不对'
# 邮箱30 + 批发/供应身份词25 + 非博客10 = 65
# ⚠️ 拿不到 PRODUCT_WORDS 的 +10，因为那张词表写死的是猫砂垫 ['litter','liner','cat','pet']，
#    「trash bags」不在里面 —— 这正是「按本轮产品词动态传入」要解决的问题。
assert r1['row']['score'] == 65, f'评分不对：{r1["row"]["score"]}'
assert r1['row']['rating'] == '普通客户', f'评级不对：{r1["row"]["rating"]}'
# ⚠️ 本轮会话：这条应自动开了一轮，并进了明细；但**不该动结果文件**
assert m.MANUAL_STATE['session_active'] is True, '第一条应自动开一轮（扩展在别处点也算）'
assert m.MANUAL_STATE['session_industry'] == '', '没传行业时本轮口径应为空（落盘时再从行里推）'
assert [r['url'] for r in m.MANUAL_STATE['session_rows']] == ['https://plasticbagpc.com'], \
    f'本轮明细没记上：{m.MANUAL_STATE["session_rows"]}'
assert m.paths.ENRICH_FILE == SEED_PATH, '采集阶段不该碰结果文件（本轮结束才落盘）'
# ⛔ 本轮改动的核心：采集阶段**也不写客户库**（要等用户点「🏁 结束并生成 Excel」那一下）。
#    写库改在 _flush_manual_session() 里做 → 把国家/行业填错的那一轮可以直接丢掉，不污染库。
assert not m.db_has_customer('https://plasticbagpc.com'), \
    '采集阶段不该写客户库（入库时机已改到「结束并生成 Excel」）'
head, data = excel_rows(SEED_PATH)
assert len(data) == 1 and data[0][0] == 'Seed Co', f'上一轮的结果文件被改动了：{data}'
print('✓ 秒级进本轮明细（不写库、不落盘），且上一轮结果文件原封不动')

print('\n================ ①b 传入本轮产品词 → 拿回那 +10 ================')
r1b = m.collect_from_html('https://flatbag-maker.de', 'Trash Bag Wholesale GmbH',
                          HTML_MAIL.replace('Trash Bags Wholesale Supplier', 'Trash Bag Wholesale GmbH')
                                  .replace('plasticbagpc.com', 'flatbag-maker.de'),
                          product_words=['trash bag', 'drawstring bag'])
print('结果：', {k: v for k, v in r1b.items() if k != 'row'})
assert r1b['added'], '应新增'
assert r1b['row']['score'] == 75, f'传了产品词后应拿到 +10 变成 75，实际 {r1b["row"]["score"]}'
assert r1b['row']['rating'] == '重点客户', f'评级应升到重点客户，实际 {r1b["row"]["rating"]}'
assert len(m.MANUAL_STATE['session_rows']) == 2, '本轮明细应有 2 条'
print('✓ 不传产品词 65（普通客户）→ 传产品词 75（重点客户），可选入参零回归')

print('\n================ ② 同网址再采一次：本轮内去重 ================')
# ⚠️ 此刻 plasticbagpc 还**没入库**（要等「结束」），所以这里命中的是**本轮内去重**
#    （_session_has_url），而不是 db_has_customer —— 效果一样：不再当新客户、不再升级抓取。
r2 = m.collect_from_html('https://plasticbagpc.com', 'Trash Bags Wholesale Supplier', HTML_MAIL)
print('结果：', {k: v for k, v in r2.items() if k != 'row'})
assert r2['ok'] and r2['existed'] and not r2['added'], f'应识别为本轮已采过：{r2}'
assert calls['enrich'] == [], '本轮内已采过的站不该再开浏览器补全'
assert m.MANUAL_STATE['existed'] == 1 and m.MANUAL_STATE['added'] == 2, \
    f'本轮计数不对：added={m.MANUAL_STATE["added"]} existed={m.MANUAL_STATE["existed"]}'
assert len(m.MANUAL_STATE['session_rows']) == 3, '跳过的条目也要在明细里留痕（否则用户不知道它去哪了）'
assert m.MANUAL_STATE['session_rows'][-1]['kind'] == 'existed', '最后一条应是 kind=existed'
assert m.paths.ENRICH_FILE == SEED_PATH, '去重也不该碰结果文件'
print('✓ 去重跳过 + 明细留痕，结果文件仍未被碰')

print('\n================ ③ 无邮箱 → 升级到 Chromium（恰好 1 次）================')
HTML_NO_MAIL = ('<html><head><title>Wicket Bag Co</title></head><body>'
                '<a href="/contact">Get in touch</a><p>We supply bin liners</p></body></html>')
r3 = m.collect_from_html('https://wicketbag.co.uk', 'Wicket Bag Co', HTML_NO_MAIL)
print('结果：', {k: v for k, v in r3.items() if k != 'row'})
assert r3['ok'] and r3['added'], f'第三条应新增：{r3}'
assert r3['tier'] == 3, f'应升级到③级，实际 {r3["tier"]}'
assert r3['upgraded'] is True, '应标记为已升级'
assert calls['req'] == 1, f'第②级应只试 1 个候选（页面自带的 /contact 链接），实际 {calls["req"]}'
assert calls['enrich'] == ['https://wicketbag.co.uk'], \
    f'升级路径应恰调 1 次 enrich 且是本网址：{calls["enrich"]}'
assert r3['row']['emails'] == ['sales@wicketbag.co.uk'], '升级后邮箱没并进来'
assert r3['row']['contact_url'].endswith('/contact'), '升级后联系页没记上'
# emails30 + contact10 + 非博客10 = 50（enrich 打桩没给电话；'wicket bag' 不含 'liner'）
assert r3['row']['score'] == 50, f'升级后评分不对：{r3["row"]["score"]}'
assert m.MANUAL_STATE['upgraded'] == 1, '升级计数没累加'

print('\n================ ④ 结束本轮 → 落一份新的 10 列结果文件 ================')
r4 = m.collect_from_html('https://binliner-supply.fr', 'Bin Liner Supply',
                         HTML_NO_MAIL.replace('Wicket', 'BinLiner'))
assert r4['ok'] and r4['added'], '第四条应新增'
assert len(m.MANUAL_STATE['session_rows']) == 5, f'本轮明细应 5 条（含 1 条已存在）'
assert m.paths.ENRICH_FILE == SEED_PATH, '结束前仍不该碰结果文件'

before = sorted(os.listdir(OUT))
res = m._flush_manual_session()
after = sorted(os.listdir(OUT))
print('结束落盘：', res)
print('文件变化：', before, '→', after)
assert res['ok'] and res['saved'], f'结束应成功落盘：{res}'
assert len(after) == len(before) + 1, '应新生成一份文件（而不是追加进上一轮的）'
assert m.paths.ENRICH_FILE != SEED_PATH, '新文件应成为「最新结果文件」'
assert m.MANUAL_STATE['session_active'] is False, '结束后本轮应关闭'
assert m.MANUAL_STATE['session_rows'] == [], '结束后明细应清空'
assert m.MANUAL_STATE['session_excel'] == os.path.basename(m.paths.ENRICH_FILE), \
    'session_excel 应是新文件基名'
assert m.STATE['output'].startswith('output/'), f'STATE["output"] 应是 output/ 相对串：{m.STATE["output"]}'

head, data = excel_rows(m.paths.ENRICH_FILE)
print('列头：', head)
print('数据行：', [(r[0], r[5]) for r in data])
assert head == m.EXCEL_HEADER_10, f'10 列契约被破坏：{head}'
assert len(data) == 4, f'本轮 4 条新客户（已存在的 1 条不写进 Excel），实际 {len(data)}'
names = [r[0] for r in data]
assert names[0] == 'Trash Bag Wholesale GmbH', f'应按评分降序（75 打头）：{names}'
scores = [r[5] for r in data]
assert scores == sorted(scores, reverse=True), f'未按评分降序：{scores}'
assert 'seed.com' not in str(data) and 'Seed Co' not in names, '上一轮的种子行不该被卷进来'
assert all(r[8].startswith('[手动采集]') for r in data), '公式列应带 [手动采集] 前缀'
# ⛔ 本轮改动的落点：**入库发生在「结束」这一刻**（而不是采集那一刻）。
#    结束后必须满足「Excel 里的每一行，客户库里都有」——否则下次再采到同一个站会被当成
#    新客户重复进表（用户实测踩过：同一个站一份表里出现 3 次）。
import sqlite3 as _sq4
_c4 = _sq4.connect(m.db_path())
try:
    _keys4 = {r[0] for r in _c4.execute('SELECT website_key FROM customers')}
finally:
    _c4.close()
assert {'plasticbagpc.com', 'flatbag-maker.de', 'wicketbag.co.uk',
        'binliner-supply.fr'} <= _keys4, f'结束后 4 条新客户应已入库：{_keys4}'
_excel4 = {m.normalize_domain(str(r[1])) for r in data}
assert _excel4 <= _keys4, f'Excel 每一行都得能在库里找到：表 {_excel4} / 库 {_keys4}'
print('✓ 本轮 4 条独立成一份文件，10 列契约 + 降序 + 不污染上一轮；且结束这一刻才入库')

print('\n================ ⑤ 落盘失败 → 保留数据、可重试 ================')
# ⚠️ 邮箱必须跟着域名改：db_upsert_customer 在 website_key 未命中时会用 lower(email)
#    兜底匹配，沿用 plasticbagpc.com 的邮箱会把这条并到那一条上去。
r5 = m.collect_from_html('https://retry-test.com', 'Retry Test Co',
                         HTML_MAIL.replace('plasticbagpc.com', 'retry-test.com'))
assert r5['added'] and m.MANUAL_STATE['session_active'] is True, '应自动开新一轮'
_real_save = m._save_enrich_excel
m._save_enrich_excel = lambda *a, **k: False        # 模拟「结果 Excel 被 Excel 打开着」
before_files = sorted(os.listdir(OUT))
fail = m._flush_manual_session()
print('落盘失败返回：', fail)
assert fail['ok'] is False and fail['saved'] is False, f'应报告失败：{fail}'
assert not fail['msg'].startswith('本轮没有'), '失败原因应是保存失败而不是空轮'
assert len(m.MANUAL_STATE['session_rows']) == 1, '失败时本轮明细必须保留（否则数据白采）'
assert m.MANUAL_STATE['session_active'] is True, '失败时本轮应保持进行中，好让用户重试'
assert m.MANUAL_STATE['session_error'], '应给出可读的失败原因'
assert sorted(os.listdir(OUT)) == before_files, '失败时不该产出半截文件'
# ⚠️ 入库刻意排在写表**之前** → Excel 没写成功时，这条其实已经在库里了。
#    这正是 api_manual_session_delete 里那条「例外分支」的来源（这种行删掉要连库一起删），
#    见 _smoke_manual_session.py ⑪ 的第二个用例。
assert m.db_has_customer('https://retry-test.com'), '入库在前：Excel 失败时这条已落库'
m._save_enrich_excel = _real_save                  # 恢复（Excel 关掉了）
retry = m._flush_manual_session()
print('重试返回：', retry)
assert retry['ok'] and retry['saved'], f'恢复后应重试成功：{retry}'
assert m.MANUAL_STATE['session_active'] is False and m.MANUAL_STATE['session_rows'] == []
assert not m.MANUAL_STATE['session_error'], '成功后应清掉错误信息'
# 重试会再 upsert 一次 → 必须是幂等的（按 website_key），库里不能出现重复行
import sqlite3 as _sq5
_c5 = _sq5.connect(m.db_path())
try:
    _n5 = _c5.execute("SELECT COUNT(*) FROM customers WHERE website_key='retry-test.com'"
                      ).fetchone()[0]
finally:
    _c5.close()
assert _n5 == 1, f'重试入库是幂等的，库里不该有重复行，实际 {_n5}'
print('✓ 失败不丢数据、不产半截文件；恢复后一键重试成功（重试入库幂等，不会重复）')

print('\n================ ⑥ 库内校验 ================')
conn = sqlite3.connect(m.db_path())
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT company_name,website_key,email,contact_url,score,rating,"
                    "industry,country,source,search_formula FROM customers "
                    "ORDER BY score DESC").fetchall()
conn.close()
for r in rows:
    print('   库里：', dict(r))
# 5 条手动采集（plasticbag / flatbag / wicketbag / binliner / retry-test）+ 1 条启动迁移的种子行
assert len(rows) == 6, f'库里应有 6 条（5 手动 + 1 迁移种子），实际 {len(rows)}'
manual = [r for r in rows if r['source'] == '手动采集']
migrated = [r for r in rows if r['source'] != '手动采集']
assert len(manual) == 5, f'手动采集应有 5 条，实际 {len(manual)}'
assert len(migrated) == 1 and migrated[0]['website_key'] == 'seed.com', \
    f'迁移进来的种子行应保持 source=谷歌搜索：{[dict(r) for r in migrated]}'
by_key = {r['website_key']: r for r in manual}
assert set(by_key) == {'plasticbagpc.com', 'flatbag-maker.de', 'wicketbag.co.uk',
                       'binliner-supply.fr', 'retry-test.com'}, by_key.keys()
assert all(r['search_formula'].startswith('[手动采集]') for r in manual), '公式字段应带 [手动采集] 前缀'
assert by_key['plasticbagpc.com']['industry'] == '塑料包装袋', '行业没写进库'
assert by_key['binliner-supply.fr']['contact_url'] == 'https://binliner-supply.fr/contact', \
    '升级抓到的联系页没写进库'
print('   ✓ 5 条手动采集 source 全部为「手动采集」；种子行仍是「谷歌搜索」（迁移语义未被破坏）')

print('\n================ ⑦ 路由层：缺 X-DP-Ext 必须 403 ================')
with m.app.test_client() as c:
    bad = c.post('/api/collect', json={'url': 'https://x.com'})
    print('不带自定义头 →', bad.status_code)
    assert bad.status_code == 403, f'没带 X-DP-Ext 应 403，实际 {bad.status_code}'
    ok = c.post('/api/collect', json={'url': 'https://x.com'}, headers={'X-DP-Ext': '1'})
    assert ok.status_code == 200, f'带头上应放行，实际 {ok.status_code}'
    body = ok.get_json()
    assert body['ok'] and body['added'], f'带头采集应入库：{body}'
    # 返回给扩展的 row 结构必须保持原样 —— kind 只是本轮明细的内部标记
    assert 'kind' not in (body.get('row') or {}), \
        f'返回给扩展的 row 不该带内部 kind 字段：{sorted((body.get("row") or {}).keys())}'
    ping = c.get('/api/ping').get_json()
    assert ping['app'] == 'waimao-dp', f'/api/ping 身份标记不对：{ping}'
    assert 'manual_running' in ping, '/api/ping 应带手动采集运行态'
    # 新路由必须在场（前端靠它们开轮/结束）
    st = c.get('/api/manual/state').get_json()
    for k in ('session_active', 'session_rows', 'session_industry', 'session_country',
              'session_excel', 'session_error'):
        assert k in st, f'/api/manual/state 缺字段 {k}'
    print('   /api/manual/state 的 session_* 字段齐备')
print('✓ 403 拦截、/api/ping 身份标记、会话字段契约均正确')

print('\n================ ⑧ 删除单条明细：本轮还没入库 → 只动内存明细 ================')
# ⚠️ 2026-10-11 起手动采集是「点『🏁 结束并生成 Excel』才一次性入库」，所以本轮明细里
#    kind='added' 的行**此刻还不在客户库里** —— 删它只是把它从「待入库清单」里拿掉：
#      · 客户库本来就没有这条 → 不该删库、更不该平白产生一份备份；
#      · 灰字 kind='existed' 行是别人早采过的老客户 → 也一样不碰（用户明确要求）。
#    唯一会动库的情况是「本轮已入库成功、但结果 Excel 没写成功」（见 ⑤ 组的注释），
#    那种行才需要连库一起删 —— 这条分支在 _smoke_manual_session.py ⑪ 有专门用例。
# ⑦ 那次 /api/collect（x.com）已经自动开了一轮，这里接着它往下走。
assert m.MANUAL_STATE['session_active'] is True, '前置：⑦ 的采集应已自动开一轮'
r8a = m.collect_from_html('https://del-alpha.com', 'Del Alpha',
                          HTML_MAIL.replace('plasticbagpc.com', 'del-alpha.com'))
r8b = m.collect_from_html('https://del-beta.com', 'Del Beta',
                          HTML_MAIL.replace('plasticbagpc.com', 'del-beta.com'))
assert r8a['added'] and r8b['added'], '前置：两条新站应进本轮明细'
st8 = list(m.MANUAL_STATE['session_rows'])
print('本轮明细：', [(r.get('rid'), r['url']) for r in st8])
assert len(st8) == 3, f'本轮应 3 条，实际 {len(st8)}'
rids = [r['rid'] for r in st8]
assert len(set(rids)) == 3 and all(isinstance(x, int) for x in rids), f'rid 应各不相同：{rids}'
del_rid, del_url = rids[0], st8[0]['url']
assert len(m.MANUAL_STATE['session_rows']) == 3 and m.MANUAL_STATE['added'] == 3, '前置计数应为 3'
assert not m.db_has_customer(del_url), f'前置：{del_url} 此刻**不该**在库里（本轮还没点结束）'

_bk_before8 = (sorted(os.listdir(m.db._backups_dir()))
               if os.path.isdir(m.db._backups_dir()) else [])
with m.app.test_client() as c:
    jd = c.post('/api/manual/session/delete', json={'rid': del_rid}).get_json()
_bk_after8 = (sorted(os.listdir(m.db._backups_dir()))
              if os.path.isdir(m.db._backups_dir()) else [])
print('删除返回：', jd)
assert jd['ok'] is True and jd['deleted'] == 0, f'本轮未入库 → 客户库应删 0 条：{jd}'
assert jd['backup'] == '', f'没动库就不该平白备份一份：{jd}'
assert jd['rows'] == 2, f'明细应剩 2 条：{jd}'
assert _bk_after8 == _bk_before8, '不该新增备份文件'
assert not m.db_has_customer(del_url), '客户库依旧没有这条（它本来就没进去过）'
assert [r['rid'] for r in m.MANUAL_STATE['session_rows']] == rids[1:], '留下的应恰好是另外两条'
assert m.MANUAL_STATE['added'] == 2, f'added 计数应回退到 2，实际 {m.MANUAL_STATE["added"]}'
assert m.MANUAL_STATE['session_active'] is True, '删完本轮仍在进行中（没被误关）'

# 删不存在 / 不带 rid → 一律拒绝（绝不能退化成「删全部」甚至清库）
with m.app.test_client() as c:
    bad1 = c.post('/api/manual/session/delete', json={'rid': 999999}).get_json()
    bad2 = c.post('/api/manual/session/delete', json={}).get_json()
assert bad1['ok'] is False and bad2['ok'] is False, f'非法请求应被拒：{bad1} / {bad2}'
assert len(m.MANUAL_STATE['session_rows']) == 2, '被拒的请求不该动过明细'

# 再删一条（同样是 added 但没入库）→ 一样不碰库、不产备份
with m.app.test_client() as c:
    jk = c.post('/api/manual/session/delete', json={'rid': rids[1]}).get_json()
assert jk['ok'] and jk['deleted'] == 0 and jk['backup'] == '', f'同样不碰库：{jk}'
assert sorted(os.listdir(m.db._backups_dir()) if os.path.isdir(m.db._backups_dir()) else []) \
    == _bk_before8, '删第二条仍不该产生备份'

# 结束落盘：被删的既不进 Excel、也不进库
res8 = m._flush_manual_session()
print('结束落盘：', res8)
assert res8['ok'] and res8['saved'], f'应成功落盘：{res8}'
assert res8['rows'] == 1, f'应只落 1 行（剩下的那条）：{res8}'
_head8, data8 = excel_rows(m.paths.ENRICH_FILE)
assert len(data8) == 1, f'Excel 应只 1 行，实际 {len(data8)}'
urls8 = ' '.join(str(r[1] or '') for r in data8)
assert 'del-' in urls8, f'Excel 里应是没被删的那条：{urls8}'
assert 'x.com' not in urls8 and 'del-alpha' not in urls8, f'被删的不该出现在 Excel：{urls8}'
# ⛔ 新的核心不变量：**Excel 里写的每一行，客户库里都得有**（否则下次再采到同站又当新客户重复进表）
_c8 = sqlite3.connect(m.db_path())
try:
    _db8 = {r[0] for r in _c8.execute('SELECT website_key FROM customers')}
finally:
    _c8.close()
_excel8 = {m.normalize_domain(str(r[1])) for r in data8}
assert _excel8 <= _db8, f'Excel 每一行都得能在库里找到：表 {_excel8} / 库 {_db8}'
assert m.normalize_domain('https://del-alpha.com') not in _db8, '被删那条不该被写进库'
print('✓ 未入库的明细删了只动内存 | 不产备份 | 计数回退 | 被删的既不进 Excel 也不进库')

# 删到 0 条也要正常；本轮不能因此被误关（用户还能接着采）
r8c = m.collect_from_html('https://del-gamma.com', 'Del Gamma',
                          HTML_MAIL.replace('plasticbagpc.com', 'del-gamma.com'))
assert r8c['added'] and m.MANUAL_STATE['session_active'] is True, '应能继续采集'
_only_rid = m.MANUAL_STATE['session_rows'][0]['rid']
with m.app.test_client() as c:
    je8 = c.post('/api/manual/session/delete', json={'rid': _only_rid}).get_json()
assert je8['ok'] and je8['rows'] == 0, f'删到 0 条也应正常返回：{je8}'
assert m.MANUAL_STATE['session_active'] is True, '删空后本轮仍应进行中'
_empty = m._flush_manual_session()
assert _empty['ok'] and _empty['saved'] is False, f'删空后结束应是空轮、不落盘：{_empty}'
print('✓ 删空后本轮不误关；空轮不落盘')

print('\n================ ⑨ clean_emails 误报过滤：资源名 / 埋点 DSN 不能当邮箱 ================')
# 用户实测反馈：结果表里出现了 `xxx_1512x@2x.png`（srcset 里的图片资源名）和 Sentry 埋点 DSN。
# 根因是 EMAIL_RE 的 TLD 只要求「2 个以上字母」→ `…@2x.png` 整体合规（域名段 2x、TLD png）。
# 这一段把三类噪声钉死，同时保证真邮箱一个都不误杀（下面的样本全是从真实库里捞出来的）。
ce = m.clean_emails

_CE_BAD_ASSET = [
    'copy_of_brick_banner_3_2f20ddef-bc09-445c-b72b-f67bd04593e7_1512x@2x.png',
    'sale_a7af39eb-4e71-4157-a284-ce9cf45d7cf8_1512x@2x.png',
    '130@3x.png', 'logo@2x.png', 'en@x2.png', 'asset-1@2x.webp',
    'bg-2@2x-scaled-1.jpeg', 'chosen-sprite@2x.png', 'flags@2x.png',
    'categories@3x.png', 'image_footer_qr@2x.a1d0e8ca.png',
    'maddies_serving_the_pet_industry_200@3.png', 'sweetalert2@10.js',
    'intl-tel-input-flags@2x.png', 'dji_0598-1@2x-1024x620.jpg',
]
for _b in _CE_BAD_ASSET:
    assert ce('<img srcset="https://cdn.x/%s 2x">' % _b) == [], '图片资源名被当成邮箱：%s' % _b
print('✓ 资源文件名（srcset 里的 xxx_1512x@2x.png 等）%d 个全部挡住' % len(_CE_BAD_ASSET))

_CE_BAD_DSN = [
    '8c4075d5481d476e945486754f783364@sentry.io',
    '046c982186afa15dc9513490293d26b1@o37417.ingest.sentry.io',
    '9b74111f40989eb7c26d8f236cc00f0c@o4507413183004672.ingest.us.sentry.io',
    'aa9e75413d709c702aa734c3ae4fdcfb@o235577.ingest.us.sentry.io',
    'x@cdn.jsdelivr.net', 'x@api.hotjar.com', 'px@ads.google.com',
]
for _b in _CE_BAD_DSN:
    assert ce('<script>var dsn="https://%s"</script>' % _b) == [], '埋点 DSN 被当成邮箱：%s' % _b
print('✓ 埋点 / 第三方宿主 DSN %d 个全部挡住' % len(_CE_BAD_DSN))

# ⚠️ 这一组是防误杀的护栏，比「挡得住」更重要：163.com / 126.com / 21cn.com 是纯数字 label 的
#    合法免费邮域 —— 倍图规则若写成带裸数字分支的正则，会把它们一起吃掉。
_CE_KEEP = [
    'info@plasticbagpc.com', 'sales@wicketbag.co.uk', 'contact@lyonpack.fr',
    'info@pasta-import.fr', 'office@shared-key.it', 'info@auto-high.com',
    'derrick_sheng@163.com', '786sokom@gmail.com', 'hello@126.com', 'x@21cn.com',
    'amores.ventas@kume.com.mx', 'asiapack@outlook.fr', 'atencion@gruposl.com.sv',
    'booking@heritageresorts.mu', 'comercial@wmtrading.com.br',
    'comunicacionsocial@comceoccte.org.mx', 'commande.chr@redisma.re',
    'info@company.com.cn', 'user@sub.mail.co.uk', 'a_b-c@my-shop2.com',
    'support@910ths.sa', 'store@thebeastiary.ca',
]
for _g in _CE_KEEP:
    assert ce('<a href="mailto:%s">%s</a>' % (_g, _g)) == [_g], '真邮箱被误杀：%s' % _g
print('✓ 真邮箱 %d 个零误杀（含多级 TLD / 子域 / 数字域 / 连字符 / free mail）' % len(_CE_KEEP))

# 老写法 `any(n in dom for n in NOISE_EMAIL)` 是**子串**匹配 → mywix.com / shopwix.com 会被误杀。
# 改成「等于或 .后缀」后必须放行，同时 wix 系真宿主照挡。
assert ce('a@mywix.com') == ['a@mywix.com'], 'mywix.com 被 wix.com 子串误杀'
assert ce('a@shopwix.com') == ['a@shopwix.com'], 'shopwix.com 被 wix.com 子串误杀'
assert ce('a@wix.com') == [] and ce('a@mail.wix.com') == [], 'wix 系宿主该挡没挡'
print('✓ 噪声宿主改成后缀匹配：mywix.com 放行、wix.com / mail.wix.com 照挡')

# 混合场景 + 返回契约（大小写混写要去重、最多 3 个、全小写、返回 list）
_CE_MIX = (
    '<img srcset="hero_1512x@2x.png 2x, foo@3x.webp 3x">'
    '<script>dsn="https://8c4075d5481d476e945486754f783364@sentry.io"</script>'
    '<a href="mailto:Sales@Acme.com">Sales@Acme.com</a>'
    '<p>sales@acme.com</p><p>info@acme.com</p>'
    '<p>wholesale@acme.com</p><p>ops@acme.com</p>'
)
_got = ce(_CE_MIX)
assert _got == ['sales@acme.com', 'info@acme.com', 'wholesale@acme.com'], \
    '混合场景应只留前 3 个真邮箱（且去重）：%s' % _got
assert isinstance(_got, list) and all(e == e.lower() for e in _got), '返回契约（list / 全小写）变了'
assert ce('') == [] and ce('<p>no mail here</p>') == [], '没有邮箱的页面应回空列表'
print('✓ 混合场景只留真邮箱；小写 / 去重 / 最多 3 个 / 空页回 [] 契约不变')

print('\n✅ 手动采集冒烟测试全部通过')
print('   ① 秒级不开浏览器 / 采集阶段既不写库也不落盘 | ①b 产品词+10 | ② 本轮内去重留痕')
print('   ③ 升级恰 1 次 | ④ 结束才入库 + 落一份新表（10 列/降序/不污染上一轮）| ⑤ 失败可重试')
print('   ⑥ 路由 403 | ⑧ 未入库的明细删了只动内存（不碰库/不产备份），被删的既不进表也不进库')
print('   ⑨ clean_emails 误报过滤：资源名/埋点 DSN 全挡、真邮箱零误杀')

shutil.rmtree(TMP, ignore_errors=True)
