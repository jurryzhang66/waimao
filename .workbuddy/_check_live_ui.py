# -*- coding: utf-8 -*-
"""真机校验两块前端改动：
  A. 「5. 关键词组合预览」——选法国 + 输入 nouilles，确认条件词切法语、并显示 &gl=fr&hl=fr
  B. 「本轮已入库明细」——注入假数据，确认行数/徽章/空态/不撑破容器
起临时 Flask 实例 + Chrome，不联网、不碰真实客户库。"""
import importlib.util
import os
import sys
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
DIR = r'D:\waimao\dp\.workbuddy'
PNG_COMBO = os.path.join(DIR, '_combo_fr.png')
PNG_LIVE = os.path.join(DIR, '_live_ui.png')

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

PORT = m.pick_port('127.0.0.1', (5012, 8000, 8080, 8765, 9000))[0]
print('临时实例端口：', PORT)


def serve():
    m.app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False, threaded=True)


threading.Thread(target=serve, daemon=True).start()
time.sleep(1.5)

page = None
try:
    page = m.create_browser_page()
    page.get(f'http://127.0.0.1:{PORT}/')
    time.sleep(1.2)

    # ---------- A. 预览：法国 + nouilles ----------
    page.run_js(r"""
      const c = document.getElementById('countries');
      c.value = 'fr'; c.dispatchEvent(new Event('change'));
      const p = document.getElementById('products');
      p.value = 'nouilles'; p.dispatchEvent(new Event('input'));
    """)
    time.sleep(0.6)
    summary = page.run_js("return document.getElementById('comboSummary').textContent;")
    lines = page.run_js(
        "return [...document.querySelectorAll('#comboList .cmb-line')].map(e => e.textContent);")
    lang_sel = page.run_js("return document.getElementById('kwLang').value;")
    print('汇总行：', summary)
    print('语言下拉自动联动为：', lang_sel)
    for i, l in enumerate(lines, 1):
        print(f'  公式{i}：', l)

    assert lang_sel == 'fr', f'选法国后语言下拉应联动成 fr，实际 {lang_sel}'
    assert '条件词语言：法语' in summary, f'汇总行没显示条件词语言：{summary}'
    assert '目标国家：法国' in summary, f'汇总行没显示目标国家：{summary}'
    assert any('grossiste OR distributeur' in l for l in lines), '条件词没切法语（批发商）'
    assert any('importateur' in l for l in lines), '条件词没切法语（进口商）'
    assert all('&gl=fr&hl=fr' in l for l in lines), '公式行没显示国家筛选参数'
    assert not any('wholesaler' in l for l in lines), '法语下仍出现英文条件词'
    print('  ✓ 条件词已本地化，国家参数已显示')
    page.get_screenshot(path=PNG_COMBO, full_page=True)
    print('  截图：', PNG_COMBO, os.path.getsize(PNG_COMBO), 'bytes')

    # 顺手校验后端确实用同一套模板（预览与实际查询一致）
    assert m.cond_template('wholesale', 'fr') == '{p} (grossiste OR distributeur)'
    assert m.cond_template('wholesale', 'de') == '{p} (Großhändler OR Distributor)'
    assert m.cond_template('wholesale', 'fa') == '{p} (wholesaler OR distributor)', \
        '缺该语言时应回落英文'
    assert m.cond_template('contact', 'fr') == 'inurl:contact {p}', '无角色词的条件不该被本地化改动'
    assert m.cond_template('linkedin', 'fr') == 'site:linkedin.com/in {p} (achats OR approvisionnement OR acheteur)'
    print('  ✓ 后端 cond_template 与前端一致；fa 回落英文、contact 不参与本地化')

    # ---------- B. 实时入库明细 ----------
    page.run_js(r"""
      renderRows([
        {n:1, title:'Miamland Grossiste Pates et Nouilles France',
         url:'https://www.miamland.com/', emails:['contact@miamland.com','commercial@miamland.com'],
         phones:['+33 4 72 00 11 22'], contact_url:'https://www.miamland.com/contact',
         score:65, rating:'普通客户', industry:'食品', country:'法国'},
        {n:2, title:'Agriculture and Agri-Food Canada', url:'https://agriculture.canada.ca/',
         emails:[], phones:[], contact_url:'', score:10, rating:'观察',
         industry:'食品', country:'加拿大'},
        {n:3, title:'DCA Distribution - Grossiste alimentaire', url:'https://dca-distribution.fr/',
         emails:['info@dca-distribution.fr'], phones:[],
         contact_url:'https://dca-distribution.fr/contact', score:55,
         rating:'普通客户', industry:'食品', country:'法国'}
      ]);
    """)
    time.sleep(0.8)
    got = page.run_js("return document.querySelectorAll('#liveBody tr').length;")
    badge = page.run_js("return document.getElementById('liveCount').textContent;")
    empty_disp = page.run_js("return document.getElementById('liveEmpty').style.display;")
    wide = page.run_js(
        "var t=document.querySelector('table.live');"
        "var w=document.querySelector('.live-scroll');"
        "return [t.scrollWidth, w.clientWidth];")
    print('渲染行数：', got, '| 徽章：', badge, '| 空态 display：', empty_disp)
    print('表格宽/容器宽：', wide)
    assert got == 3, f'应渲染 3 行，实际 {got}'
    assert '3' in badge, f'徽章应显示 3 条，实际 {badge}'
    assert empty_disp == 'none', '有数据时占位提示应隐藏'
    assert wide[0] <= wide[1] + 2, f'表格被撑出容器：{wide}'
    page.get_screenshot(path=PNG_LIVE, full_page=True)
    print('截图：', PNG_LIVE, os.path.getsize(PNG_LIVE), 'bytes')

    print('\n✅ 预览 + 实时明细表 真机校验全部通过')
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
