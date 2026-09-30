# -*- coding: utf-8 -*-
"""真机校验「关键词库」新增行业是否真的驱动了页面三级联动：
  A. 行业下拉出现第 8 项「塑料包装袋」
  B. 选它 → 细分品类 5 项 → 具体产品 10 项 → 词条 41 条
  C. 勾上「具体产品=抽绳垃圾袋」→ 列表 4 条，勾选框的 value 是英文词
  D. 语言切「德语」→ 未译词条回落英文（前端 k[lang] || k.en）
  E. 后端 /api/keywords 与 JSON 文件内容一致（防止接口层被缓存/改写）
起临时 Flask 实例 + Chrome，不联网、不碰真实客户库。

⚠️ 顺序约定：Flask 3.x 的 app.json.sort_keys 默认 True，jsonify 会对**每一层** dict
按键排序输出，所以页面三级下拉的顺序永远是 sorted(keys)，**与 关键词库.json 里的键序无关**。
（这是既有行为，拆包前的 7 个行业也一样。）因此本脚本一律拿 sorted(...) 做期望值，
只对「集合相等」做硬断言；文件键序不参与断言。"""
import importlib.util
import json
import os
import sys
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
KW = r'D:\waimao\dp\关键词库.json'
PNG = r'D:\waimao\dp\.workbuddy\_kwlib_ui.png'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

PORT = m.pick_port('127.0.0.1', (5013, 8000, 8080, 8765, 9000, 7000))[0]
print('临时实例端口：', PORT)
threading.Thread(target=lambda: m.app.run(host='127.0.0.1', port=PORT, debug=False,
                                          use_reloader=False, threaded=True), daemon=True).start()
time.sleep(1.5)

with open(KW, 'rb') as f:
    lib = json.loads(f.read().decode('utf-8'))
# 页面/接口看到的是 Flask 排序后的顺序
exp_inds = sorted(lib.keys())
exp_cats = sorted(lib['塑料包装袋'].keys())
exp_prods = sorted(p for subs in lib['塑料包装袋'].values() for p in subs)
exp_terms = {c: {p: [e['en'] for e in lst] for p, lst in subs.items()}
             for c, subs in lib['塑料包装袋'].items()}
exp_total = sum(len(l) for subs in lib['塑料包装袋'].values() for l in subs.values())
print('期望：行业 %d 个 / 塑料包装袋 %d 品类 %d 产品 %d 词条'
      % (len(exp_inds), len(exp_cats), len(exp_prods), exp_total))

page = None
try:
    page = m.create_browser_page()
    page.get('http://127.0.0.1:%d/' % PORT)
    time.sleep(1.5)

    # ---------- A. 行业下拉 ----------
    inds = page.run_js("return [...document.querySelectorAll('#kwIndustry option')]"
                       ".map(o => o.value);")
    print('行业下拉：', inds)
    assert len(inds) == 8, '行业下拉不是 8 项：%s' % inds
    assert '塑料包装袋' in inds, '新行业没出现在下拉里：%s' % inds
    assert set(inds) == set(lib.keys()), \
        '行业集合与 JSON 不一致：页面 %s / 文件 %s' % (set(inds), set(lib.keys()))
    assert inds == exp_inds, '下拉顺序不是 sorted(keys)：%s vs %s' % (inds, exp_inds)
    print('  ✓ 行业下拉 8 项 = JSON 全部行业，顺序为 sorted(keys)（Flask 排序）')

    # ---------- B. 选中新行业 → 品类 / 产品 ----------
    page.run_js("""
      const s = document.getElementById('kwIndustry');
      s.value = '塑料包装袋'; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.5)
    cats = page.run_js("return [...document.querySelectorAll('#kwCategory option')]"
                       ".map(o => o.value).filter(Boolean);")
    prods = page.run_js("return [...document.querySelectorAll('#kwProduct option')]"
                        ".map(o => o.value).filter(Boolean);")
    n_all = page.run_js("return document.querySelectorAll('#kwList .kw-item').length;")
    print('细分品类：', cats)
    print('具体产品：', prods)
    print('词条总条数：', n_all)
    assert cats == exp_cats, '品类不符：%s vs %s' % (cats, exp_cats)
    assert n_all == exp_total == 41, '词条数不是 41：页面 %s / 期望 %s' % (n_all, exp_total)
    print('  ✓ 5 品类齐全，品类=全部时 41 词条全量列出')

    # ---------- B2. 逐个细分品类 → 产品下拉并集应为 10 ----------
    # 注意：「具体产品」下拉只在选定细分品类后填充（选「全部细分品类」时为空），这是页面既有行为。
    got_prods = []
    for c in exp_cats:
        page.run_js("""
          const s = document.getElementById('kwCategory');
          s.value = %s; s.dispatchEvent(new Event('change'));
        """ % json.dumps(c))
        time.sleep(0.25)
        ps = page.run_js("return [...document.querySelectorAll('#kwProduct option')]"
                         ".map(o => o.value).filter(Boolean);")
        exp_c = sorted(lib['塑料包装袋'][c].keys())
        assert ps == exp_c, '品类「%s」下产品不符：%s vs %s' % (c, ps, exp_c)
        print('    %s → %s' % (c, ps))
        got_prods += ps
    assert sorted(got_prods) == exp_prods, '产品并集不符：%s' % sorted(got_prods)
    assert len(got_prods) == len(set(got_prods)) == 10, '产品有重复或不是 10 个：%s' % got_prods
    print('  ✓ 5 品类 / 10 产品（无重复）/ 41 词条全部就位')

    # 选回「全部细分品类」，方便后面按产品取词
    page.run_js("""
      const s = document.getElementById('kwCategory');
      s.value = ''; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.25)

    # ---------- C. 选到具体产品：抽绳垃圾袋 ----------
    # 先选细分品类「家用垃圾袋」，产品下拉才可用
    page.run_js("""
      const s = document.getElementById('kwCategory');
      s.value = '家用垃圾袋'; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.25)
    page.run_js("""
      const s = document.getElementById('kwProduct');
      s.value = '抽绳垃圾袋'; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.4)
    vals = page.run_js("return [...document.querySelectorAll('#kwList .kw-chk')].map(c => c.value);")
    cns = page.run_js("return [...document.querySelectorAll('#kwList .kw-cn')].map(c => c.textContent);")
    print('抽绳垃圾袋 →', vals)
    print('            cn:', cns)
    assert vals == exp_terms['家用垃圾袋']['抽绳垃圾袋'], '抽绳垃圾袋的词条不符：%s' % vals
    assert all(v.strip() == v and v for v in vals), '勾选框 value 有空值或首尾空白'
    print('  ✓ 抽绳垃圾袋 4 条英文词条、勾选框 value 正确')

    # ---------- D. 语言回落 ----------
    page.run_js("""
      const s = document.getElementById('kwLang');
      s.value = 'de'; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.4)
    vals_de = page.run_js("return [...document.querySelectorAll('#kwList .kw-chk')].map(c => c.value);")
    print('语言=德语 →', vals_de)
    assert vals_de == vals, '德语音未译时应回落英文，实际：%s' % vals_de
    print('  ✓ 未译语言正确回落英文（前端 k[lang] || k.en）')

    # 恢复英语并截图
    page.run_js("""
      const s = document.getElementById('kwLang');
      s.value = 'en'; s.dispatchEvent(new Event('change'));
    """)
    time.sleep(0.4)
    page.get_screenshot(path=PNG, full_page=True)

    # ---------- E. 接口与文件一致 ----------
    api = page.run_js("""
      return fetch('/api/keywords').then(r => r.json()).then(d => Object.keys(d));
    """)
    print('接口返回的行业：', api)
    assert set(api) == set(lib.keys()), '接口行业集合与 JSON 不一致：%s' % api
    assert api == exp_inds, '接口顺序不是 sorted(keys)：%s' % api
    print('  ✓ /api/keywords 的行业集合与 关键词库.json 一致（顺序为 Flask 排序）')

    # ---------- F. 组合预览：新行业词条能否正常拼进公式 ----------
    # 用「分别搜」让 4 条词条各占一个 product query，便于逐条核对
    page.run_js("""
      const r = document.querySelector('input[name="match"][value="each"]');
      r.checked = true; r.dispatchEvent(new Event('change', {bubbles:true}));
      const ta = document.getElementById('products');
      ta.value = %s; ta.dispatchEvent(new Event('input'));
    """ % json.dumps('\n'.join(vals)))
    time.sleep(0.5)
    combo_txt = page.run_js("return document.getElementById('comboList').textContent;")
    summary = page.run_js("return document.getElementById('comboSummary').textContent;")
    n_cond = page.run_js("return document.querySelectorAll('#conds input:checked').length;")
    n_line = page.run_js("return document.querySelectorAll('#comboList .cmb-line').length;")
    print('组合摘要：', summary)
    print('组合条数：', n_line, '（勾选条件 %d 个）' % n_cond)
    assert n_cond >= 1, '默认应至少勾选一个搜索条件'
    for v in vals:
        assert '"%s"' % v in combo_txt, '词条没进组合预览：%s' % v
    assert n_line == len(vals) * n_cond, \
        '组合条数应为 词条数×条件数 = %d，实际 %d' % (len(vals) * n_cond, n_line)
    assert '&gl=' in combo_txt and '&hl=' in combo_txt, '公式尾部应显示 &gl=&hl= 灰字'
    print('  ✓ 4 条词条全部拼进公式，条数 = 4×%d，尾部带 &gl=&hl=' % n_cond)

    print('\n✅ 关键词库界面校验全部通过')
    print('截图：', PNG, os.path.getsize(PNG), 'bytes')
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
