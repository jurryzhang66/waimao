# -*- coding: utf-8 -*-
"""打桩冒烟测试：不联网、不开浏览器，验证「谷歌地图采集」闭环流程。

与 _smoke_search.py 同套路：加载主工具后把浏览器/地图抓取这几个外部依赖换成假实现，
只让 run_maps 的「主循环 + 详情读取 + 去重 + 老客户跳过 + 就地补全 + 回写库 + 落盘」跑起来。
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

TMP = tempfile.mkdtemp(prefix='smoke_maps_')
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

calls = {'detail': [], 'enrich': [], 'back': 0, 'quit': 0, 'open_urls': [], 'saved': None}


class FakePage:
    tab_id = 'FAKE-MAPS-TAB'

    def quit(self):
        calls['quit'] += 1


# ⚠️ run_maps 现在带参调用 create_browser_page(persistent=True)；桩用宽签名，
#    以后再加启动参数也不用跟着改（_check_serp.py 有静态断言钉住「只在两处传 True」）。
m.create_browser_page = lambda *a, **k: FakePage()
# maps_open / wait_captcha 都在地图链路内部，直接打桩（真机行为由 _probe_maps.py 覆盖）
m.sleep_check = lambda seconds: True


def fake_maps_open(page, url, attempts=2):
    calls['open_urls'].append(url)
    return True


m.maps_open = fake_maps_open


def fake_back(page, tab_id):
    calls['back'] += 1
    assert tab_id == 'FAKE-MAPS-TAB', f'切回的标签 id 不对：{tab_id}'


m._back_to_search = fake_back

# ---- 假商家数据 -------------------------------------------------------------
# place id 用 !1s0x..:0x.. 形式，正好喂给 maps_place_key 去重
HREF_A = 'https://www.google.com/maps/place/A/@45.7,4.8,17z/data=!1s0xaaa1:0x1'
HREF_B = 'https://www.google.com/maps/place/B/@45.7,4.8,17z/data=!1s0xbbb2:0x2'
HREF_C = 'https://www.google.com/maps/place/C/@45.7,4.8,17z/data=!1s0xccc3:0x3'
HREF_D = 'https://www.google.com/maps/place/D/@45.7,4.8,17z/data=!1s0xddd4:0x4'
HREF_E = 'https://www.google.com/maps/place/E/@45.7,4.8,17z/data=!1s0xeee5:0x5'
HREF_F = 'https://www.google.com/maps/place/F/@45.7,4.8,17z/data=!1s0xfff6:0x6'

# 第 1 条后面塞一条「同 place id 的不同 URL」，验证去重键生效
FAKE_HREFS = [HREF_A, HREF_A + '&entry=ttu', HREF_B, HREF_C, HREF_D, HREF_E, HREF_F]

DETAILS = {
    HREF_A: {'name': 'LYON PACK FOOD', 'phone': '+33478890001',
             'website': 'https://lyonpack.fr', 'address': '12 Rue des Halles, Lyon',
             'category': 'Grossiste alimentaire', 'place_url': HREF_A},
    HREF_B: {'name': 'International Store', 'phone': '+33478890002',
             'website': '', 'address': '5 Quai Saint-Antoine, Lyon',
             'category': 'Épicerie asiatique', 'place_url': HREF_B},
    HREF_C: {'name': 'Old Customer SARL', 'phone': '+33478890003',
             'website': 'https://old-customer.fr', 'address': 'Lyon',
             'category': 'Grossiste', 'place_url': HREF_C},
    HREF_D: None,                                  # 详情页没读通 → 应被跳过
    HREF_E: {'name': 'Pasta Import SAS', 'phone': '',
             'website': 'https://pasta-import.fr', 'address': 'Villeurbanne',
             'category': 'Importateur', 'place_url': HREF_E},
    HREF_F: {'name': 'Never Visited', 'phone': '', 'website': '',
             'address': '', 'category': '', 'place_url': HREF_F},
}


def fake_collect(page, want, max_rounds=16):
    return list(FAKE_HREFS)


m.maps_collect_hrefs = fake_collect


def fake_detail(page, place_url):
    calls['detail'].append(place_url)
    return DETAILS.get(place_url)


m.maps_detail = fake_detail


def fake_has(website):
    return m.normalize_domain(website) == m.normalize_domain('https://old-customer.fr')


m.db_has_customer = fake_has


def fake_enrich(page, url):
    calls['enrich'].append(url)
    if 'lyonpack' in url:
        return {'emails': ['contact@lyonpack.fr'], 'phones': ['+33 4 72 00 00 00'],
                'contact_url': url + '/contact', 'china_signal_text': ''}
    if 'pasta-import' in url:
        return {'emails': ['info@pasta-import.fr'], 'phones': [],
                'contact_url': '', 'china_signal_text': ''}
    return {'emails': [], 'phones': [], 'contact_url': '', 'china_signal_text': ''}


m.enrich = fake_enrich


def spy_save(results, industry=''):
    calls['saved'] = results
    return True


m._save_enrich_excel = spy_save


def export_now():
    """模拟用户点「📥 导出 Excel」：真打一次 `/api/export_excel`。

    ⛔ 新语义（2026-10-13）：run_maps 采集阶段**不写库、不落盘**，只往 `STATE['rows']` 攒行 +
    置 `pending_export=True`。只有这一步才「先逐条入库、再写结果 Excel」。
    """
    with m.app.test_client() as c:
        return c.post('/api/export_excel').get_json()


m.STATE['rows'] = []
m.STATE['stop'] = False

print('================ 开始地图冒烟测试 ================')
m.run_maps(['nouilles'], ['wholesale'], [('fr', '法国', 'fr', 'fr')], city='Lyon',
           target_count=3, industry='食品', auto_enrich=True)

print('\n================ 断言 ================')
# ---- 搜索 URL：国家中心坐标 + 城市 + hl/gl + 身份词 ----
assert calls['open_urls'], '一条地图 URL 都没发出'
u = calls['open_urls'][0]
print('实际地图 URL：', u)
lat, lng = m.COUNTRY_CENTERS['fr']
assert f'@{lat},{lng},11z' in u, f'地图 URL 没带法国中心坐标：{u}'
assert u.startswith('https://www.google.com/maps/search/'), 'URL 前缀不对'
assert 'hl=fr' in u and 'gl=fr' in u, f'URL 缺 hl/gl：{u}'
assert 'Lyon' in u, f'城市没拼进查询词：{u}'
assert 'grossiste' in u.lower(), f'身份词没拼进查询词（不带只会返回餐馆）：{u}'

# ---- 详情逐条导航：h1 及其重复项 → h2 → h3 → h4 → h5 → h6；h7 不访问 ----
assert calls['detail'] == [HREF_A, HREF_B, HREF_C, HREF_D, HREF_E], \
    f'详情导航顺序/次数不对：{calls["detail"]}'
print('详情依次导航：', len(calls['detail']), '次  →', [x.rsplit("/", 1)[-1][:3] for x in calls['detail']])

# ---- ① 采集阶段**不落盘、不入库**（2026-10-13 新语义）----
assert calls['saved'] is None, '采集阶段不该落盘（新语义：要等点「📥 导出 Excel」）'
assert m.STATE['pending_export'] is True, '跑完应进入「待导出」状态'

# ---- ② 实时明细就是「待导出的那一份」：3 条完整行，且带地图来源标记 ----
live = m.STATE['rows']
assert len(live) == 3, f'实时明细应有 3 条，实际 {len(live)}'
assert [r['n'] for r in live] == [1, 2, 3], '实时明细序号应为 1/2/3'
assert live[0]['emails'] == ['contact@lyonpack.fr'], '实时明细首条邮箱不对'
for r in live:
    for k in ('n', 'title', 'url', 'emails', 'phones', 'contact_url', 'score',
              'rating', 'snippet', 'formula', 'industry', 'country', 'source'):
        assert k in r, f'待导出明细缺字段：{k}'
assert all(r['source'] == '谷歌地图' for r in live), '地图链路的每一行都要带 source=谷歌地图'
print('实时明细 {0} 条，序号 {1}'.format(len(live), [r['n'] for r in live]))

with m.app.test_client() as c:
    resp = c.get('/api/status?since=0').get_json()
assert len(resp['rows']) == 3, '/api/status 未返回 rows 或条数不符'
assert resp.get('pending_export') is True, '/api/status 未返回 pending_export（前端按钮靠它启用）'

# ---- ③ 此刻库里**还没有**这 3 条地图记录 ----
conn = sqlite3.connect(m.db_path())
n_before = conn.execute("SELECT COUNT(*) FROM customers WHERE source='谷歌地图'").fetchone()[0]
conn.close()
assert n_before == 0, f'采集阶段不该写库（实际已有 {n_before} 条地图记录）'

# ---- ④ 点「📥 导出 Excel」→ 才写客户库 + 落盘 ----
je = export_now()
assert je.get('ok') is True and je.get('saved') is True, f'导出应成功：{je}'
assert m.STATE['rows'] == [] and m.STATE['pending_export'] is False, \
    f'导出后应清空明细并复位状态：rows={m.STATE["rows"]} pending={m.STATE["pending_export"]}'

# ---- 落盘 3 条（A 新增、B 新增（无官网）、E 新增）；C 老客户跳过、D 读不通、F 未轮询到 ----
assert calls['saved'] is not None, '导出后应该落盘了'
assert len(calls['saved']) == 3, f'应停在目标 3 条，实际 {len(calls["saved"])}'
names = [r['title'] for r in calls['saved']]
assert names == ['LYON PACK FOOD', 'International Store', 'Pasta Import SAS'], f'入库商家不对：{names}'

row_a, row_b, row_e = calls['saved']
# A：地图电话 + 官网电话（去重后并列），邮箱来自官网
assert row_a['phones'][0] == '+33478890001', '地图电话没放首位'
assert '+33 4 72 00 00 00' in row_a['phones'], '官网补到的电话没并入'
assert row_a['emails'] == ['contact@lyonpack.fr'], '官网邮箱没抓到'
# B：没有官网 → 用 place 链接占位，不访问官网（不调 enrich）
assert row_b['url'] == HREF_B, f'无官网商家应以 place 链接占位：{row_b["url"]}'
assert row_b['emails'] == [] and row_b['phones'] == ['+33478890002'], 'B 的联系方式不对'
assert HREF_B not in calls['enrich'], '无官网的商家不该去访问官网'
# E：地图没给电话，邮箱来自官网
assert row_e['emails'] == ['info@pasta-import.fr'] and row_e['phones'] == [], 'E 的联系方式不对'
assert all('谷歌地图' in r['formula'] for r in calls['saved']), '来源标记没写进公式字段'
assert calls['enrich'] == ['https://lyonpack.fr', 'https://pasta-import.fr'], \
    f'只该对有官网的商家补全：{calls["enrich"]}'
assert calls['back'] == 2, f'每次补全后应切回地图标签，实际 {calls["back"]}'
assert calls['quit'] == 1, f'浏览器应关闭 1 次，实际 {calls["quit"]}'

# ---- 10 列硬契约 ----
for r in calls['saved']:
    for k in ('title', 'url', 'emails', 'phones', 'contact_url', 'score',
              'rating', 'snippet', 'formula', 'country', 'industry'):
        assert k in r, f'落盘记录缺字段：{k}'
    assert r['snippet'], '摘要不该为空（应为 类目 · 地址 或名称）'
print(f'落盘 {len(calls["saved"])} 条 | 补全 {len(calls["enrich"])} 次 | 切回地图 {calls["back"]} 次 | '
      f'关浏览器 {calls["quit"]} 次')

# ---- 客户库（导出之后才有）：来源标记「谷歌地图」、无官网商家去重键用 place id ----
conn = sqlite3.connect(m.db_path())
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT company_name,website,website_key,phone,email,source,industry "
                    "FROM customers WHERE source='谷歌地图' ORDER BY company_name").fetchall()
conn.close()
print(f'库内「谷歌地图」来源记录 {len(rows)} 条')
for r in rows:
    print('   库内：', dict(r))
assert len(rows) == 3, f'库里应有 3 条地图记录，实际 {len(rows)}'
by_name = {r['company_name']: r for r in rows}
assert by_name['International Store']['website_key'] == m.maps_place_key(HREF_B), \
    '无官网商家的去重键应是 place id'
assert by_name['LYON PACK FOOD']['website_key'] == 'lyonpack.fr', \
    f'有官网商家的去重键应是域名：{by_name["LYON PACK FOOD"]["website_key"]}'
assert by_name['Pasta Import SAS']['industry'] == '食品', '行业标签没写进库'

print('\n✅ 地图冒烟测试全部通过')

shutil.rmtree(TMP, ignore_errors=True)
