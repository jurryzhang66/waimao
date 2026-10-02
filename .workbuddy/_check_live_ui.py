# -*- coding: utf-8 -*-
"""真机校验五块前端改动：
  A. 「5. 关键词组合预览」——选法国 + 输入 nouilles，确认条件词切法语、并显示 &gl=fr&hl=fr
  B. 「本轮已入库明细」——注入假数据，确认行数/徽章/空态/不撑破容器
  C. 首页顶栏导航（V1.5 加）——两个链接的 href / 文案 / 样式真的生效
  D. 「6. 自定义搜索词」——卡片落位、预览切「原样」分支、清空回标准模式、地图模式下置灰
  E. 「国家限定」四选一——默认 none、cr 只挂 URL、site: 只进搜索词、美国跳过 site:、
     地图模式整块收起、自定义词模式下不生效
起临时 Flask 实例 + Chrome，不联网、不碰真实客户库。"""
import importlib.util
import json
import os
import sys
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
DIR = r'D:\waimao\dp\.workbuddy'
PNG_COMBO = os.path.join(DIR, '_combo_fr.png')
PNG_LIVE = os.path.join(DIR, '_live_ui.png')
PNG_RAW = os.path.join(DIR, '_raw_query_card.png')
PNG_LIMIT = os.path.join(DIR, '_country_limit.png')

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
    assert all(' - - - ' not in l for l in lines), '预览不应显示空过滤项生成的独立短横线'
    assert not any('wholesaler' in l for l in lines), '法语下仍出现英文条件词'
    print('  ✓ 条件词已本地化，国家参数已显示')

    # ---------- A2. buyer + 多产品 OR 语义 ----------
    page.run_js(r"""
      const p = document.getElementById('products');
      p.value = 'nouilles\nrice noodles';
      p.dispatchEvent(new Event('input'));
      const buyer = document.querySelector('#conds input[value="buyer"]');
      buyer.checked = true;
      buyer.dispatchEvent(new Event('change', {bubbles:true}));
    """)
    time.sleep(0.4)
    semantic_lines = page.run_js(
        "return [...document.querySelectorAll('#comboList .cmb-line')].map(e => e.textContent);")
    assert any('(\"nouilles\" OR \"rice noodles\")' in l for l in semantic_lines), \
        '多产品 OR 没有整体加括号'
    assert any('acheteur OR achats OR approvisionnement OR sourcing' in l for l in semantic_lines), \
        'buyer 条件没有出现在预览公式中（法语本地化）'
    assert any('[客户发现]' in l for l in page.run_js(
        "return [...document.querySelectorAll('#comboList .cmb-head')].map(e => e.textContent);")), \
        '客户发现用途分类没有显示'
    # 恢复测试页面的单产品状态，后续截图与既有断言保持稳定。
    page.run_js(r"""
      const p = document.getElementById('products');
      p.value = 'nouilles';
      p.dispatchEvent(new Event('input'));
      document.querySelector('#conds input[value="buyer"]').checked = false;
      document.querySelector('#conds input[value="buyer"]').dispatchEvent(new Event('change', {bubbles:true}));
    """)
    time.sleep(0.4)
    print('  ✓ buyer 条件、多产品 OR 括号与用途分类实际渲染正确')
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

    # ---------- C. 首页顶栏导航（V1.5 加）----------
    # ⚠️ 这条非真机测不出来：href 写错 / 被删掉 / `.nav-a` 样式没生效，都**不会**报任何错，
    #    只表现为「首页少了两个入口」或「导航退化成两条带下划线的裸链接」。
    nav = json.loads(page.run_js(r"""
      return JSON.stringify([...document.querySelectorAll('.nav a.nav-a')].map(a => {
        const cs = getComputedStyle(a);
        return {href: a.getAttribute('href'), text: a.textContent.trim(),
                color: cs.color, deco: cs.textDecorationLine};
      }));
    """))
    print('顶栏导航：', nav)
    assert [d['href'] for d in nav] == ['/manual', '/db'], \
        '首页顶栏导航应依次指向 /manual 与 /db，实际 %s' % [d['href'] for d in nav]
    assert '手动采集页' in nav[0]['text'] and '客户库查询' in nav[1]['text'], \
        '导航文案不对：%s' % [d['text'] for d in nav]
    assert all(d['color'] == 'rgb(26, 115, 232)' for d in nav), \
        '导航没拿到 .nav-a 的样式（共享 <style> 没注入？）：%s' % [d['color'] for d in nav]
    assert all(d['deco'] == 'none' for d in nav), '导航链接还带着下划线（.nav-a 没生效）'
    order = page.run_js(r"""
      const n = document.querySelector('.nav'), c = document.querySelector('.card');
      return (n.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) ? 'before' : 'after';
    """)
    assert order == 'before', '顶栏导航应排在第一张卡之前，实际 %s' % order
    print('  ✓ 首页顶栏两个导航就位（/manual、/db）且样式已生效')

    # ---------- D. 「6. 自定义搜索词」（原样搜 / 与标准模式互斥 / 地图置灰）----------
    # ⚠️ 这一段必须真机测：卡片落位、预览切分支、地图置灰，三者写错都**不会**报任何运行时报错
    #    —— 只表现为「卡片不见了 / 预览还按条件算 / 切到地图还能填」。
    pos = json.loads(page.run_js(r"""
      const grid = document.querySelector('.grid');
      const raw  = document.getElementById('rawCard');
      const btn  = document.querySelector('.btn-row');
      if (!raw) return JSON.stringify({missing: true});
      const ta = document.getElementById('rawQueries');
      return JSON.stringify({
        missing: false,
        afterGrid: !!(grid.compareDocumentPosition(raw) & Node.DOCUMENT_POSITION_FOLLOWING),
        beforeBtn: !!(raw.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING),
        tag: ta.tagName,
        rows: ta.getAttribute('rows'),
        title: raw.querySelector('h3').textContent.trim(),
      });
    """))
    print('第 6 卡：', pos)
    assert not pos['missing'], '主页没有 #rawCard（第 6 张卡）'
    assert pos['afterGrid'], '第 6 卡应排在 .grid（第 1-5 卡）之后'
    assert pos['beforeBtn'], '第 6 卡应排在「▶ 开始搜索」按钮行之前'
    assert pos['tag'] == 'TEXTAREA', f'自定义搜索词应是多行文本框，实际 {pos["tag"]}'
    assert pos['title'].startswith('6.'), f'卡片标题不该是：{pos["title"]}'

    # 填两行有效 + 一行纯空白：预览必须切到「原样」分支，且空白行不进公式
    page.run_js(r"""
      const t = document.getElementById('rawQueries');
      t.value = 'cat litter grossiste\n\n   \n"pet food" importer Lyon';
      t.dispatchEvent(new Event('input'));
    """)
    raw_sum = page.run_js("return document.getElementById('comboSummary').textContent;")
    raw_lines = json.loads(page.run_js(
        "return JSON.stringify([...document.querySelectorAll('#comboList .cmb-line')]"
        ".map(d => d.textContent.trim()));"))
    print('自定义预览汇总：', raw_sum)
    for i, l in enumerate(raw_lines, 1):
        print(f'  自定义公式{i}：', l)
    assert '条自定义查询（原样搜索，不拼任何词）' in raw_sum, \
        f'预览没切到自定义分支：{raw_sum}'
    assert '目标国家：法国' in raw_sum, f'自定义预览没显示目标国家：{raw_sum}'
    assert len(raw_lines) == 2, f'两行有效词应出 2 条，实际 {len(raw_lines)}'
    assert raw_lines[0].startswith('cat litter grossiste'), f'第 1 条不是原样：{raw_lines[0]}'
    assert raw_lines[1].startswith('"pet food" importer Lyon'), f'第 2 条不是原样：{raw_lines[1]}'
    assert not any('-amazon' in l or '-etsy' in l for l in raw_lines), \
        f'自定义预览不该拼排除词：{raw_lines}'
    assert all('&gl=fr&hl=fr' in l for l in raw_lines), \
        f'自定义预览也应显示国家参数（它挂在 URL 上、不在搜索词里）：{raw_lines}'
    assert not any('wholesaler' in l or 'importateur' in l for l in raw_lines), \
        f'自定义模式下不该出现条件词：{raw_lines}'
    print('  ✓ 填了自定义词 → 预览切「原样」分支（2 条、无排除词、无条件词、空白行已丢）')

    page.get_screenshot(path=PNG_RAW, full_page=True)
    print('  截图：', PNG_RAW, os.path.getsize(PNG_RAW), 'bytes')

    # 清空 → 必须回到标准模式（互斥的另一半：不能两边同时生效）
    page.run_js(r"""
      const t = document.getElementById('rawQueries');
      t.value = '';
      t.dispatchEvent(new Event('input'));
    """)
    back = page.run_js("return document.getElementById('comboSummary').textContent;")
    print('清空后汇总：', back)
    assert '条自定义查询' not in back, f'清空自定义框后预览没回到标准模式：{back}'
    assert '个产品组合' in back, f'清空后应回到标准模式预览：{back}'
    print('  ✓ 清空自定义框 → 预览回到标准模式（互斥成立）')

    # 切到谷歌地图 → 自定义框必须置灰 + 出提示；切回网页搜索 → 恢复
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'maps').checked = true;
      onSource();
    """)
    maps_state = json.loads(page.run_js(r"""
      const t = document.getElementById('rawQueries');
      return JSON.stringify({disabled: !!t.disabled,
                             hint: document.getElementById('rawMapsHint').style.display,
                             bg: getComputedStyle(t).backgroundColor});
    """))
    print('地图模式下的自定义框：', maps_state)
    assert maps_state['disabled'] is True, '切到地图模式时自定义搜索词没被置灰'
    assert maps_state['hint'] == 'block', '切到地图模式时没显示「地图不使用自定义词」的提示'
    assert maps_state['bg'] == 'rgb(246, 247, 249)', \
        f'置灰样式没生效（应拿到 .raw-card textarea:disabled 的底色）：{maps_state["bg"]}'
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'google').checked = true;
      onSource();
    """)
    assert page.run_js("return document.getElementById('rawQueries').disabled;") is False, \
        '切回谷歌网页搜索后自定义框没恢复可用'
    print('  ✓ 地图模式置灰 + 提示；切回网页搜索即恢复')

    # ---------- E. 「国家限定」四选一（默认关 / cr 走 URL / site: 走搜索词 / 只标准模式）----------
    # 两支最怕的静默失效：① 默认值被改成非 none；② 前端预览与后端实搜不一致。
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'google').checked = true;
      document.getElementById('countries').value = 'fr';
      const p = document.getElementById('products');
      p.value = 'nouilles'; p.dispatchEvent(new Event('input'));
      [...document.querySelectorAll('#conds input')].forEach(x => { x.checked = (x.value === 'wholesale'); });
      const t = document.getElementById('rawQueries'); t.value = '';
      onSource();
    """)

    def cl_preview():
        """返回 (汇总行, 公式行, URL 参数行)。"""
        page.run_js("renderCombos();")
        return (page.run_js("return document.getElementById('comboSummary').textContent;"),
                json.loads(page.run_js(
                    "return JSON.stringify([...document.querySelectorAll('#comboList .cmb-line')]"
                    ".map(d => d.textContent.trim()));")),
                json.loads(page.run_js(
                    "return JSON.stringify([...document.querySelectorAll('#comboList .cmb-arg')]"
                    ".map(d => d.textContent.trim()));")))

    def pick_limit(v, code='fr'):
        page.run_js(f"""
          const c = document.getElementById('countries');
          if (c.value !== '{code}') {{ c.value = '{code}'; c.dispatchEvent(new Event('change')); }}
          const r = document.querySelector('input[name="country_limit"][value="{v}"]');
          r.checked = true;
          r.dispatchEvent(new Event('change', {{bubbles: true}}));
        """)

    assert page.run_js(
        "return document.querySelector('input[name=\"country_limit\"]:checked').value;") == 'none', \
        '国家限定默认没选中「不改」'
    s0, f0, a0 = cl_preview()
    print('默认（none）汇总：', s0)
    print('  参数：', a0[0] if a0 else '')
    assert '个产品组合' in s0, f'默认没走标准模式：{s0}'
    assert all(x == '&gl=fr&hl=fr' for x in a0), f'默认参数不该含 cr：{a0}'
    assert not any('site:.fr' in l for l in f0), f'默认不该把 site: 写进搜索词：{f0}'
    print('  ✓ 默认 none：参数 &gl=fr&hl=fr、搜索词无 site:')

    pick_limit('cr')
    _, f1, a1 = cl_preview()
    print('cr 模式参数：', a1[0] if a1 else '')
    assert all(x == '&gl=fr&hl=fr&cr=countryFR' for x in a1), f'cr 没挂到 URL 参数上：{a1}'
    assert not any('site:.fr' in l for l in f1), f'cr 模式不该动搜索词：{f1}'
    print('  ✓ cr 只挂 URL：&gl=fr&hl=fr&cr=countryFR（搜索词不变）')

    pick_limit('site')
    _, f2, a2 = cl_preview()
    print('site 模式公式：', f2[0] if f2 else '')
    assert all('site:.fr' in l for l in f2), f'site: 没进搜索词：{f2}'
    assert all(x == '&gl=fr&hl=fr' for x in a2), f'site 模式不该加 cr：{a2}'
    print('  ✓ site: 只进搜索词')

    pick_limit('both')
    _, f3, a3 = cl_preview()
    assert all('&cr=countryFR' in x for x in a3) and all('site:.fr' in l for l in f3), \
        f'both 没同时生效：参数 {a3} / 公式 {f3}'
    print('  ✓ both = cr + site: 同时生效')

    # 美国：site 留空 → site 模式下的搜索词应与「不改」逐字一致
    # （用对比法而不是 `'site:' not in l` —— 默认中国过滤会往公式里拼 -site:.cn）
    pick_limit('none', 'us')
    _, fUsNone, _ = cl_preview()
    pick_limit('site', 'us')
    _, fUsSite, _ = cl_preview()
    print('美国 + site 模式公式：', fUsSite[0] if fUsSite else '')
    assert fUsSite == fUsNone, f'美国不该加 site:（公式应与默认一致）：{fUsSite} vs {fUsNone}'
    pick_limit('cr', 'us')
    _, _, aUsCr = cl_preview()
    assert all('&cr=countryUS' in x for x in aUsCr), f'美国 cr 应生效：{aUsCr}'
    print('  ✓ 美国：site: 自动跳过（公式与默认逐字一致），cr 照常生效')

    page.get_screenshot(path=PNG_LIMIT, full_page=True)
    print('  截图：', PNG_LIMIT, os.path.getsize(PNG_LIMIT), 'bytes')

    # 切到地图 → 国家限定整块收起（它只服务网页搜索）
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'maps').checked = true;
      onSource();
    """)
    disp = page.run_js("return document.getElementById('countryLimit').style.display;")
    print('地图模式下 #countryLimit 的 display：', disp)
    assert disp == 'none', '切到地图模式时国家限定没整块收起'
    print('  ✓ 地图模式：#countryLimit 整块收起')

    # 自定义词模式 → 即使选了 both 也不生效（与后端 run_search 的强制置 none 一致）
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'google').checked = true;
      onSource();
      const t = document.getElementById('rawQueries');
      t.value = 'cat litter grossiste'; t.dispatchEvent(new Event('input'));
    """)
    pick_limit('both', 'fr')
    _, fRaw, aRaw = cl_preview()
    print('自定义模式 + both：', (aRaw[0] if aRaw else ''), '|', (fRaw[0] if fRaw else ''))
    assert all(x == '&gl=fr&hl=fr' for x in aRaw), f'自定义模式不该加 cr：{aRaw}'
    assert not any('site:.fr' in l for l in fRaw), f'自定义模式不该加 site:：{fRaw}'
    print('  ✓ 自定义词模式：国家限定被关掉（与后端互斥一致）')
    page.run_js("const t = document.getElementById('rawQueries'); t.value = ''; "
                "t.dispatchEvent(new Event('input'));")

    print('\n✅ 预览 + 实时明细表 + 顶栏导航 + 自定义搜索词 + 国家限定 真机校验全部通过')
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
