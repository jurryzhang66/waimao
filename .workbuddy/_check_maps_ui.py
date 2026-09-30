# -*- coding: utf-8 -*-
"""真机校验「谷歌地图名录」这个新数据源的界面切换与预览：
  A. 切到地图模式 → 城市框出现、翻页/排除词隐藏、地图说明出现
  B. 「5. 关键词组合预览」显示完整可点的地图 URL，且与后端 maps_search_url() 完全一致
  C. 切回网页搜索 → 恢复原界面
起临时 Flask 实例 + Chrome，不联网、不碰真实客户库。"""
import importlib.util
import os
import sys
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
PNG = r'D:\waimao\dp\.workbuddy\_maps_ui.png'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

PORT = m.pick_port('127.0.0.1', (5013, 8000, 8080, 8765, 9000))[0]
print('临时实例端口：', PORT)
threading.Thread(target=lambda: m.app.run(host='127.0.0.1', port=PORT, debug=False,
                                          use_reloader=False, threaded=True), daemon=True).start()
time.sleep(1.5)

page = None
try:
    page = m.create_browser_page()
    page.get(f'http://127.0.0.1:{PORT}/')
    time.sleep(1.2)

    # 选法国 + 输入 nouilles
    page.run_js(r"""
      const c = document.getElementById('countries');
      c.value = 'fr'; c.dispatchEvent(new Event('change'));
      const p = document.getElementById('products');
      p.value = 'nouilles'; p.dispatchEvent(new Event('input'));
    """)
    time.sleep(0.4)

    # ---------- A. 切到地图模式 ----------
    page.run_js(r"""
      const r = document.querySelector('input[name="source"][value="maps"]');
      r.checked = true; r.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.4)
    disp = page.run_js("""
      const g = id => document.getElementById(id).style.display;
      return {city:g('mapsCityWrap'), note:g('mapsNote'), pages:g('pagesWrap'),
              excl:g('excludesWrap'), cond:g('condMapsHint'), china:g('chinaMapsHint')};
    """)
    print('地图模式下各区块 display：', disp)
    assert disp['city'] == 'block' and disp['note'] == 'block', '地图模式没显示城市框/说明'
    assert disp['pages'] == 'none' and disp['excl'] == 'none', '地图模式应隐藏翻页与排除词'
    assert disp['cond'] == 'block' and disp['china'] == 'block', '地图模式没显示条件/中国过滤提示'

    # 输入城市 → 预览应重绘
    page.run_js("""
      const el = document.getElementById('mapsCity');
      el.value = 'Lyon'; el.dispatchEvent(new Event('input'));
    """)
    time.sleep(0.4)
    # ⚠️ 截图只是给人看的证据，不是断言。整页截图（这页高 3800+px）Chrome 偶尔会
    #    CDP 超时，不该因此把整套界面校验判红（2026-09-30 全量回归里实测踩到）。
    try:
        page.get_screenshot(path=PNG, full_page=True)
    except Exception as _ex:
        print('  ⚠️ 整页截图失败（不影响断言）：', type(_ex).__name__)

    summary = page.run_js("return document.getElementById('comboSummary').textContent;")
    links = page.run_js("return [...document.querySelectorAll('#comboList .cmb-line a')]"
                        ".map(a => a.getAttribute('href'));")
    print('汇总行：', summary)
    for u in links:
        print('  地图 URL：', u)

    assert '条地图查询' in summary, f'汇总行没切到地图文案：{summary}'
    assert '目标国家：法国' in summary and '城市：Lyon' in summary, f'汇总行缺国家/城市：{summary}'
    assert '身份词：grossiste' in summary, f'汇总行没显示身份词：{summary}'
    assert links, '预览里没有地图 URL'
    for u in links:
        assert u.startswith('https://www.google.com/maps/search/'), f'URL 前缀不对：{u}'
        assert 'nouilles%20grossiste%20Lyon' in u, f'查询词（含城市与身份词）不对：{u}'
        assert '@46.6,2.21,11z' in u, f'没带法国中心坐标：{u}'
        assert 'hl=fr' in u and 'gl=fr' in u, f'缺 hl/gl：{u}'
    print('  ✓ 地图预览：城市 + 身份词 + 中心坐标 + hl/gl 全部就位')

    # ---------- B. 前后端 URL 一致性 ----------
    backend = m.maps_search_url('nouilles grossiste', 'fr', 'fr', 'fr', 'Lyon')
    for u in links:
        assert u == backend, f'前端预览与后端 maps_search_url 不一致：\n  前端 {u}\n  后端 {backend}'
    print('  ✓ 前端预览与后端 maps_search_url 完全一致：', backend)

    # ---------- C. 切回网页搜索 ----------
    page.run_js(r"""
      const r = document.querySelector('input[name="source"][value="google"]');
      r.checked = true; r.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.4)
    back = page.run_js("""
      const g = id => document.getElementById(id).style.display;
      return {city:g('mapsCityWrap'), pages:g('pagesWrap'), excl:g('excludesWrap')};
    """)
    print('切回网页搜索后：', back)
    assert back['city'] == 'none' and back['pages'] == 'block' and back['excl'] == 'block', \
        '切回网页搜索没恢复界面'
    s2 = page.run_js("return document.getElementById('comboSummary').textContent;")
    assert '条地图查询' not in s2, '切回后预览没回到网页搜索文案'
    print('  ✓ 切回网页搜索：界面与预览均已还原')

    print('\n✅ 地图数据源界面校验全部通过')
    print('截图：', PNG, (os.path.getsize(PNG) if os.path.exists(PNG) else '（未生成）'))
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
