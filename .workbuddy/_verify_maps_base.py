# -*- coding: utf-8 -*-
"""校验地图基础件：国家坐标、地图搜索 URL、去重键、normalize_domain 新分支。"""
import importlib.util
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

spec = importlib.util.spec_from_file_location('kf', r'D:\waimao\dp\客户开发工具.py')
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

# ---- 1. 国家坐标表覆盖所有国家 ----
codes = [c[0] for c in m.COUNTRIES]
missing = [c for c in codes if c not in m.COUNTRY_CENTERS]
print('COUNTRIES 数量      :', len(codes))
print('COUNTRY_CENTERS 数量:', len(m.COUNTRY_CENTERS))
print('缺坐标的国家        :', missing or '（无）')
assert not missing, f'这些国家没有中心坐标：{missing}'
for c in codes:
    lat, lng = m.COUNTRY_CENTERS[c]
    assert -90 <= lat <= 90 and -180 <= lng <= 180, f'{c} 坐标越界'
print('  ✓ 25 国坐标齐全且合法')

# ---- 2. COUNTRIES 仍是 4 元组（不能被顺手改坏） ----
assert all(len(c) == 4 for c in m.COUNTRIES), 'COUNTRIES 元组长度被改了'
print('  ✓ COUNTRIES 仍是 4 元组（前端 counts_js 与 run_search 解包不受影响）')

# ---- 3. 地图搜索 URL ----
u1 = m.maps_search_url('nouilles', 'fr', 'fr', 'fr', 'Lyon')
print()
print('法国 + Lyon        :', u1)
assert u1.startswith('https://www.google.com/maps/search/nouilles%20Lyon/@46.6,2.21,11z?'), u1
assert u1.endswith('hl=fr&gl=fr'), u1

u2 = m.maps_search_url('noodles wholesale', 'ca_fr', 'ca', 'fr')
print('加拿大法语区(留空城市):', u2)
assert '@46.81,-71.21,11z' in u2, 'ca_fr 没用到魁北克坐标'

u3 = m.maps_search_url('noodles', 'xx_unknown', 'us', 'en')   # 未知国家走兜底
print('未知国家（兜底）     :', u3)
assert '@39.83,-98.58,11z' in u3, '未知国家没回落到兜底坐标'
print('  ✓ URL 拼装正确（城市名进路径、@lat,lng 定位、hl/gl 挂查询串）')

# ---- 4. 去重键 ----
PLACE = ('https://www.google.com/maps/place/Miamland/@48.9,2.3,17z/'
         'data=!3m1!4b1!4m6!3m5!1s0x47e66e2964e34e2d:0x8ddca9ee380ef7e0!8m2!3d48.9!4d2.3')
k = m.maps_place_key(PLACE)
print()
print('place 去重键        :', k)
assert k == 'maps:0x47e66e2964e34e2d:0x8ddca9ee380ef7e0', k

assert m.maps_place_key('https://www.miamland.com/') == '', '普通网址不该被当成 place'
print('  ✓ 普通网址不误判')

# ---- 5. normalize_domain 三条分支 ----
cases = [
    (PLACE, 'maps:0x47e66e2964e34e2d:0x8ddca9ee380ef7e0'),
    ('https://www.miamland.com/', 'miamland.com'),
    ('http://transgourmet.fr/a?b=1', 'transgourmet.fr'),
    ('', ''),
]
for src, want in cases:
    got = m.normalize_domain(src)
    flag = 'OK ' if got == want else 'FAIL'
    print(f'  {flag} {got!r:<45} <- {src[:52]}')
    assert got == want, f'normalize_domain({src!r}) = {got!r}，期望 {want!r}'

# 关键：两个不同的 place URL 必须得到不同的键，否则无官网的商家会互相覆盖
k1 = m.normalize_domain(PLACE)
k2 = m.normalize_domain(PLACE.replace('0x8ddca9ee380ef7e0', '0xaaaaaaaaaaaaaaaa'))
assert k1 != k2, '两个不同 place 拿到了同一个键，会互相覆盖'
print('  ✓ 不同 place 得到不同键（无官网商家不会互相覆盖成一条）')
print()
print('✅ 地图基础件全部通过')
