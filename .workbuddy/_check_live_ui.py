# -*- coding: utf-8 -*-
"""真机校验七块前端改动：
  A. 「6. 关键词组合预览」——选法国 + 输入 nouilles，确认条件词切法语、并显示 &gl=fr&hl=fr
  B. 「本轮已入库明细」——注入假数据，确认行数/徽章/空态/不撑破容器
  C. 首页顶栏导航（V1.5 加）——两个链接的 href / 文案 / 样式真的生效
  D. 「7. 自定义搜索词」——卡片落位、预览切「原样」分支、清空回标准模式、地图模式下置灰
  E. 「国家限定」四选一——默认 none、cr 只挂 URL、site: 只进搜索词、美国跳过 site:、
     地图模式整块收起、自定义词模式下不生效
  F. 「本轮采集明细（实时 · 待核对）」逐行删除——✕ 弹居中模态框（不是原生 confirm）、
     Esc=取消且不发请求、确认后只从明细里拿掉（**不动客户库**）、
     采集结束但**尚未导出**时仍可删、导出飞书阶段整表只读
  G. 「1. 本次任务采集数量」——提为 .wrap 下第 1 张独立卡（目标国家顺延成 2.）、仍预填 10、
     切到地图后依然可见可编辑、清空后点「开始搜索」必须被拦住且一个请求都不发
起临时 Flask 实例 + Chrome，不联网。
⚠️ A–E 段只读真实客户库（/api/db_stats）；**F 段会真的往库里写同域名的记录**（用来证明
   「删明细不会误伤客户库」），所以 F 段开头必须先把 core.db.db_path 与 paths.ENRICH_FILE
   打桩到临时目录，并由 _under_tmp() 护栏兜住 —— 漏了它就会写到真实客户库。G 段只读页面，不碰库。"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
DIR = r'D:\waimao\dp\.workbuddy'
PNG_COMBO = os.path.join(DIR, '_combo_fr.png')
PNG_LIVE = os.path.join(DIR, '_live_ui.png')
PNG_RAW = os.path.join(DIR, '_raw_query_card.png')
PNG_LIMIT = os.path.join(DIR, '_country_limit.png')
PNG_LIVE_DEL = os.path.join(DIR, '_live_del_modal.png')
PNG_LIVE_MODAL = os.path.join(DIR, '_live_del_modal_open.png')
PNG_LIVE_RO = os.path.join(DIR, '_live_del_readonly.png')
PNG_TARGET = os.path.join(DIR, '_target_card.png')

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

    # ---------- D. 「7. 自定义搜索词」（原样搜 / 与标准模式互斥 / 地图置灰）----------
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
    print('第 7 卡：', pos)
    assert not pos['missing'], '主页没有 #rawCard（第 7 张卡）'
    assert pos['afterGrid'], '第 7 卡应排在 .grid 之后'
    assert pos['beforeBtn'], '第 7 卡应排在「▶ 开始搜索」按钮行之前'
    assert pos['tag'] == 'TEXTAREA', f'自定义搜索词应是多行文本框，实际 {pos["tag"]}'
    assert pos['title'].startswith('7.'), f'卡片标题不该是：{pos["title"]}'

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

    # ---------- F. 实时明细逐行删除（✕ + 居中模态框 + 待核对仍可删 / 导出阶段只读）----------
    # ⛔ 语义 2026-10-13 变了：自动链路改成「点『📥 导出 Excel』才入库」，删除**只动内存明细、
    #    不碰客户库**（此刻库里根本没有这些行）—— 所以本段不再有「删前备份」。
    # ⚠️ 但 DB 仍必须打桩到临时目录：本段会往（临时）库里塞几条**同域名的记录**，
    #    用来证明「删明细不会误伤库里的记录」；不打桩就会写到真实客户库 DB/客户库.sqlite3。
    #    本脚本前面 A–E 段从没打过桩（它们只读 /api/db_stats）。
    TMPDB = tempfile.mkdtemp(prefix='live_ui_db_')
    m.db_path = lambda: os.path.join(TMPDB, 't.sqlite3')
    m.db.db_path = m.db_path            # ⚠️ 真正建连接的是 core.db，只打 m.db_path 打不到它
    # ⚠️ 空库时 init_customer_db() 会从 paths.ENRICH_FILE 导数据 → 必须一并打桩，
    #    否则测试会跑在真实结果 Excel 上（看起来还是绿的）。
    m.paths.ENRICH_FILE = os.path.join(TMPDB, '不存在的旧结果.xlsx')

    def _under_tmp(p):
        return os.path.commonpath([os.path.realpath(p),
                                   os.path.realpath(TMPDB)]) == os.path.realpath(TMPDB)

    assert _under_tmp(m.db.db_path()), f'core.db.db_path 没指向临时目录：{m.db.db_path()}'
    assert _under_tmp(m.paths.ENRICH_FILE), f'ENRICH_FILE 没指向临时目录：{m.paths.ENRICH_FILE}'
    print('\nF 段打桩：临时库 =', m.db.db_path())

    LIVE_SEED = [('Miamland Grossiste', 'https://live-del-a.fr/'),
                 ('DCA Distribution', 'https://live-del-b.fr/'),
                 ('Pasta Import SAS', 'https://live-del-c.fr/')]
    m.init_customer_db()
    for _title, _url in LIVE_SEED:
        m.db_upsert_customer({'company_name': _title, 'website': _url, 'snippet': 'x',
                              'search_formula': 'f', 'country': '法国', 'industry': '食品'})
    assert m.db_has_customer('https://live-del-a.fr/'), '前置：待删的那条应先落（临时）库'

    m.STATE.update(running=True, phase='search', result_count=3, n_seq=3, pending_export=False, rows=[
        {'n': 1, 'title': 'Miamland Grossiste', 'url': 'https://live-del-a.fr/',
         'emails': ['contact@live-del-a.fr', 'sales@live-del-a.fr'],
         'phones': ['+33 4 72 00 11 22'],
         'contact_url': 'https://live-del-a.fr/contact', 'score': 65,
         'rating': '普通客户', 'industry': '食品', 'country': '法国'},
        {'n': 2, 'title': 'DCA Distribution', 'url': 'https://live-del-b.fr/',
         'emails': ['info@live-del-b.fr'], 'phones': [], 'contact_url': '',
         'score': 55, 'rating': '普通客户', 'industry': '食品', 'country': '法国'},
        {'n': 3, 'title': 'Pasta Import SAS', 'url': 'https://live-del-c.fr/',
         'emails': [], 'phones': [], 'contact_url': '', 'score': 10,
         'rating': '观察', 'industry': '食品', 'country': '法国'},
    ])

    # 重新载入页面，让实时表**从真后端**渲染（/api/status → STATE['rows']），而不是像 B 段那样
    # 用 renderRows() 注入假数据 —— 要打的正是这条真实链路。
    page.get(f'http://127.0.0.1:{PORT}/')
    time.sleep(1.2)

    def live_poll_and_wait(want, desc):
        page.run_js("poll();")
        for _ in range(60):
            k = page.run_js("return document.querySelectorAll('#liveBody tr').length;")
            if k == want:
                return k
            time.sleep(0.15)
        raise AssertionError(f'{desc}：等 #liveBody 变成 {want} 行超时，实际 {k}')

    live_poll_and_wait(3, '初始渲染')
    badge = page.run_js("return document.getElementById('liveCount').textContent;")
    ro0 = page.run_js(
        "return document.getElementById('liveWrap').classList.contains('livedel-ro');")
    hint0 = page.run_js("return document.getElementById('liveDelHint').textContent;")
    dns = page.run_js("return [...document.querySelectorAll('#liveBody .livedel-btn')]"
                      ".map(b => b.getAttribute('data-n'));")
    print('实时表：3 行 | 徽章', badge, '| 只读类', ro0, '| 提示', hint0)
    print('✕ 上的 data-n：', dns)
    assert '3' in badge, f'徽章应显示 3 条：{badge}'
    assert ro0 is False, '采集进行中不该把整表标成只读'
    assert '可点' in hint0, f'采集进行中应提示可以删：{hint0}'
    assert dns == ['1', '2', '3'], f'每个 ✕ 都应带后端发的 n：{dns}'

    # 表头 / 列数：本轮把「行业 / 国家」两列从 /manual 并了过来（两页共用 ui/live-table.js）。
    # ⚠️ 这是用户点名的诉求（「/manual 那张表更好用」的原因之一），所以按**真实 DOM**断言：
    #    列数、列序、以及这两列真的把后端字段渲染出来了（只加表头没加单元格 = 空列，看不出来）。
    ths = page.run_js("return [...document.getElementById('liveBody')"
                      ".closest('table').querySelectorAll('thead th')].map(x => x.textContent);")
    tds0 = page.run_js("return [...document.getElementById('liveBody')"
                       ".children[0].children].map(x => x.textContent.trim());")
    print('实时表表头：', ths)
    print('第一行单元格：', tds0)
    assert len(ths) == 9, f'实时表应是 9 列（本轮新增 行业 / 国家）：{ths}'
    assert ths[6] == '行业' and ths[7] == '国家', f'第 7、8 列应是「行业」「国家」：{ths}'
    assert len(tds0) == 9, f'每个数据行也该是 9 个格子（表头加了列、行没跟上）：{tds0}'
    assert tds0[6] == '食品' and tds0[7] == '法国', \
        f'行业 / 国家列没把后端字段渲染出来（成了空列）：{tds0}'
    # 多邮箱分隔符：**全链路统一成逗号**（后端 EMAIL_SEP = ', '，插件/页面/Excel/飞书一致），
    # 电话仍保留 ' / '。用户点名要求，且这是「复制粘贴到邮件客户端」的关键细节。
    assert tds0[2] == 'contact@live-del-a.fr, sales@live-del-a.fr', \
        f'多邮箱必须用逗号分隔（不是斜杠）：{tds0[2]!r}'
    assert '/' not in tds0[2], f'邮箱列不该再出现斜杠：{tds0[2]!r}'
    print('  ✓ 实时表 9 列（含新增的「行业 / 国家」），列序与行数据都对得上')

    # ① 点 ✕ → 弹页面自己的居中模态框（⚠️ 不是原生 confirm：原生那个贴在浏览器窗口顶部、
    #    位置与样式都改不了，用户明确不要）
    page.run_js("document.querySelectorAll('#liveBody .livedel-btn')[0].click();")
    time.sleep(0.3)
    geo = json.loads(page.run_js(r"""
      const el = document.getElementById('liveDelModal');
      const card = el.querySelector('.livedel-box');
      const cs = getComputedStyle(el);
      const r = card.getBoundingClientRect();
      return JSON.stringify({shown: el.classList.contains('show'), pos: cs.position,
        disp: cs.display, al: cs.alignItems, ju: cs.justifyContent,
        cx: r.left + r.width / 2, cy: r.top + r.height / 2,
        vw: innerWidth / 2, vh: innerHeight / 2});
    """))
    print('模态框几何：', {k: (round(v, 1) if isinstance(v, float) else v)
                        for k, v in geo.items()})
    assert geo['shown'] is True, '点 ✕ 没弹出模态框'
    assert geo['pos'] == 'fixed' and geo['disp'] == 'flex', f'模态框不是 fixed+flex：{geo}'
    assert geo['al'] == 'center' and geo['ju'] == 'center', f'模态框没居中：{geo}'
    assert abs(geo['cx'] - geo['vw']) <= 2 and abs(geo['cy'] - geo['vh']) <= 2, \
        f'模态框卡片没落在视口正中（只有原生 confirm 才贴顶部）：{geo}'
    body_txt = page.run_js("return document.getElementById('liveDelModalBody').textContent;")
    assert '不可撤销' in body_txt, f'模态框没说清后果：{body_txt}'
    assert '结果 Excel' in body_txt, f'模态框没说「不进本轮结果 Excel」：{body_txt}'
    print('  ✓ 点 ✕ 弹出页面自己的居中模态框（fixed + flex 居中、卡片落在视口正中）')
    # 存档「模态框打开着」的样子给自己/用户看：⚠️ 必须**视口截图**（full_page=False）——
    # 固定定位的元素在整页截图里会被拉到页面底部附近，「截出来的根本不是用户看到的画面」。
    # 截图只是证据不是断言，失败不影响结论。
    try:
        page.get_screenshot(path=PNG_LIVE_MODAL)
        print('  截图（模态框打开）：', PNG_LIVE_MODAL, os.path.getsize(PNG_LIVE_MODAL), 'bytes')
    except Exception as _ex:
        print('  ⚠️ 模态框截图失败（不影响断言）：', type(_ex).__name__)

    # ② Esc = 取消，且**一个请求都不许发**（不做「先删后撤」的假动作）
    page.run_js("document.dispatchEvent(new KeyboardEvent('keydown', "
                "{key: 'Escape', bubbles: true}));")
    time.sleep(0.3)
    assert page.run_js("return document.getElementById('liveDelModal')"
                       ".classList.contains('show');") is False, 'Esc 没关掉模态框'
    assert len(m.STATE['rows']) == 3, f'取消后不该动明细：{len(m.STATE["rows"])}'
    assert m.db_has_customer('https://live-del-a.fr/') is True, '取消后不该动客户库'
    print('  ✓ Esc = 取消：模态框关闭，明细 / 客户库 都没动（确实没发请求）')

    # ③ 再点 ✕ → 按 Enter 确认（同时覆盖键盘确认路径）→ 只从明细里拿掉，**客户库原封不动**
    page.run_js("document.querySelectorAll('#liveBody .livedel-btn')[0].click();")
    time.sleep(0.25)
    page.run_js("document.dispatchEvent(new KeyboardEvent('keydown', "
                "{key: 'Enter', bubbles: true}));")
    live_poll_and_wait(2, '删除后')
    badge2 = page.run_js("return document.getElementById('liveCount').textContent;")
    dns2 = page.run_js("return [...document.querySelectorAll('#liveBody .livedel-btn')]"
                       ".map(b => b.getAttribute('data-n'));")
    first_txt = page.run_js("return document.querySelector('#liveBody tr').textContent;")
    print('删除后：2 行 | 徽章', badge2, '| 剩余 data-n', dns2, '| 首行', first_txt[:40])
    assert '2' in badge2, f'徽章应跟着变成 2：{badge2}'
    assert dns2 == ['2', '3'], f'剩下的应是第 2、3 条（按 n 精确删、不连坐）：{dns2}'
    assert 'Miamland' not in first_txt, f'删掉的那条还留在表里：{first_txt[:60]}'
    assert [r['n'] for r in m.STATE['rows']] == [2, 3], \
        f'后端明细也该只剩 n=2,3：{m.STATE["rows"]}'
    # ⛔ 新语义：这些行**还没入库**，所以删明细绝不许碰客户库 —— 两条同域名的库内记录都必须还在
    #    （老行为是「双删」，现在动了就是误删别人的数据）。
    assert m.db_has_customer('https://live-del-a.fr/') is True, \
        '⛔ 删明细不该删客户库（新语义下库里那条不是本轮采的）'
    assert m.db_has_customer('https://live-del-b.fr/') is True, '没被删的那条当然也不该动'
    print('  ✓ Enter 确认删除：明细 3→2、徽章同步、客户库两条都原封不动（新语义只删内存）')
    page.get_screenshot(path=PNG_LIVE_DEL, full_page=True)
    print('  截图：', PNG_LIVE_DEL, os.path.getsize(PNG_LIVE_DEL), 'bytes')

    # ④ 导出飞书阶段 → 整表只读：✕ 置灰、点了既不弹框也不动数据
    #    ⚠️ 这个阶段 running 也是 True，但 phase='export'、结果 Excel 早写好了 —— 删了就是假删除，
    #       所以判据不能只看 running（前端 liveEditable / 后端 api_live_delete 同判据）。
    m.STATE.update(running=True, phase='export', pending_export=False)
    page.run_js("poll();")
    time.sleep(0.5)
    ro1 = page.run_js(
        "return document.getElementById('liveWrap').classList.contains('livedel-ro');")
    hint1 = page.run_js("return document.getElementById('liveDelHint').textContent;")
    print('导出飞书阶段：只读类', ro1, '| 提示', hint1)
    assert ro1 is True, '导出飞书阶段应把整表标成只读'
    assert '客户库查询' in hint1, f'应提示去客户库查询页清理：{hint1}'
    page.run_js("document.querySelectorAll('#liveBody .livedel-btn')[0].click();")
    time.sleep(0.3)
    assert page.run_js("return document.getElementById('liveDelModal')"
                       ".classList.contains('show');") is False, '只读状态下点 ✕ 不该弹模态框'
    assert len(m.STATE['rows']) == 2, f'只读状态下点 ✕ 不该动数据：{len(m.STATE["rows"])}'
    print('  ✓ 导出飞书阶段整表只读：✕ 置灰，点了既不弹框也不动数据')
    page.get_screenshot(path=PNG_LIVE_RO, full_page=True)
    print('  截图：', PNG_LIVE_RO, os.path.getsize(PNG_LIVE_RO), 'bytes')

    # ⑤ 采集已结束、**尚未导出**（pending_export）→ 重新可删
    #    这是本次改造的核心交互（用户点名）：跑完先核对，把不对的行删掉，再点「📥 导出 Excel」。
    #    ⚠️ 静默失效型：判据若只用 running，跑完就整表只读 → 用户只能对着错误数据干瞪眼。
    m.STATE.update(running=False, phase='', pending_export=True)
    page.run_js("poll();")
    time.sleep(0.5)
    ro2 = page.run_js(
        "return document.getElementById('liveWrap').classList.contains('livedel-ro');")
    hint2 = page.run_js("return document.getElementById('liveDelHint').textContent;")
    print('待核对（未导出）阶段：只读类', ro2, '| 提示', hint2)
    assert ro2 is False, '「待入库/待导出」阶段应放开删除 —— 跑完先核对正是这次改造的用法'
    assert '可点' in hint2, f'待核对阶段应提示可以删：{hint2}'
    page.run_js("document.querySelectorAll('#liveBody .livedel-btn')[0].click();")
    time.sleep(0.3)
    assert page.run_js("return document.getElementById('liveDelModal')"
                       ".classList.contains('show');") is True, '待核对阶段点 ✕ 应能弹确认框'
    page.run_js("document.dispatchEvent(new KeyboardEvent('keydown', "
                "{key: 'Enter', bubbles: true}));")
    live_poll_and_wait(1, '待核对阶段删除后')
    assert len(m.STATE['rows']) == 1, f'待核对阶段应能删到 1 条：{len(m.STATE["rows"])}'
    assert m.db_has_customer('https://live-del-b.fr/') is True, '待核对阶段删明细也不许碰客户库'
    print('  ✓ 「待核对（未导出）」阶段仍可删：✕ 可点、确认框可弹、客户库不受影响')

    # ---------- G. 「1. 本次任务采集数量」卡（提为第 1 张 / 三条链路统一 / 强必填）----------
    # 用户 2026-10-02 拍板：把采集数量从「参数」卡里提出来，做成排在「目标国家」之前的第 1 张卡，
    # 并改成强必填。三条都是**静默失效**型：
    #   ① 卡片位置错了 → 用户按「先写数量」的习惯找不到入口（页面照常工作，不报任何错）
    #   ② 切地图时被连带隐藏/置灰 → 「三种链路都要先填」破功
    #   ③ 清空后仍能提交 → 等于没必填（后端拿到 NaN/缺字段会按兜底值跑）
    # ✅ 本段只读页面（不打桩、不碰库），跑在最后不影响 F 段已完成的删除校验。
    m.STATE.update(running=False, phase='', rows=[], n_seq=0, result_count=0, pending_export=False)
    page.get(f'http://127.0.0.1:{PORT}/')
    time.sleep(1.0)

    # ① 位置：`.wrap` 下的**独立卡**（`.grid` 是容器、本身不是 .card，所以 :scope > .card 只取
    #    直系卡片）。第一张必须是采集数量，第二张才是目标国家。
    cards = json.loads(page.run_js(r"""
      const wrap = document.querySelector('.wrap');
      return JSON.stringify([...wrap.querySelectorAll(':scope > .card')]
        .map(c => ((c.querySelector('h3') || {}).textContent || '').trim()));
    """))
    print('主页 .wrap 下的独立卡片顺序：', cards)
    assert cards and cards[0].startswith('1.') and '本次任务采集数量' in cards[0], \
        f'采集数量卡没排在第一位（用户的习惯是「先写数量」）：{cards}'
    assert len(cards) > 1 and cards[1].startswith('2. 目标国家'), \
        f'「目标国家」应顺延成 2. 并紧跟采集数量卡：{cards}'
    assert cards[-1].startswith('📥'), f'最后一张独立卡应仍是实时明细表：{cards}'
    print('  ✓ 采集数量卡已提到第 1 位，目标国家顺延为「2.」')


    def _tc_state():
        return json.loads(page.run_js(r"""
          const el = document.getElementById('targetCount');
          const cs = getComputedStyle(el);
          return JSON.stringify({vis: el.offsetParent !== null, disp: cs.display,
            dis: el.disabled, val: el.value, tag: el.tagName, typ: el.type});
        """))


    st0 = _tc_state()
    print('采集数量框（默认/网页模式）：', st0)
    assert st0['vis'] and not st0['dis'], f'默认状态下采集数量框应可见可编辑：{st0}'
    assert st0['tag'] == 'INPUT' and st0['typ'] == 'number', f'应是数字输入框：{st0}'
    assert st0['val'] == '10', f'拍板是「强必填但保留预填 10」，预填值被改了：{st0}'

    # ② 切到谷歌地图 → 采集数量框**必须仍然可见可编辑**（三种链路都要先填这个数）
    page.run_js(r"""
      [...document.querySelectorAll('input[name="source"]')]
        .find(x => x.value === 'maps').checked = true;
      onSource();
    """)
    st1 = _tc_state()
    print('采集数量框（地图模式）：', st1)
    assert st1['vis'] and not st1['dis'], \
        f'切到地图后采集数量框被隐藏/置灰了 —— 「三种链路都要先填」会破功：{st1}'
    print('  ✓ 切到谷歌地图后采集数量框仍可见可编辑（三条链路统一）')

    # ③ 强必填：清空 → 点「开始搜索」必须被拦住，且**一个请求都不发**
    #    start() 是 async，但校验在第一个 await 之前，所以 alert 是同步弹出的 → 可以在同一个
    #    run_js 里既调 start() 又立刻读结果（避免中间被 1 秒一次的 poll 插进来干扰计数）。
    blocked = json.loads(page.run_js(r"""
      const _oa = window.alert, _of = window.fetch;
      window.__alerts = [];
      let _fn = 0;
      window.alert = msg => { window.__alerts.push(String(msg)); };
      window.fetch = function(){ _fn++; return _of.apply(this, arguments); };
      const el = document.getElementById('targetCount');
      const _saved = el.value;
      el.value = '';                             // 清空 → 强必填必须拦住
      start();                                   // 校验是同步的，立刻就弹了
      const _res = {alerts: window.__alerts.slice(), fetches: _fn};
      window.alert = _oa;                        // 立刻还回去，别影响后续轮询
      window.fetch = _of;
      el.value = _saved || '10';
      return JSON.stringify(_res);
    """))
    print('清空采集数量后点「开始搜索」：', blocked)
    assert len(blocked['alerts']) == 1 and '本次任务采集数量' in blocked['alerts'][0], \
        f'清空采集数量后点开始应被拦住并提示数量：{blocked}'
    assert blocked['fetches'] == 0, \
        f'被拦住时不该发出任何请求（拦截要在 fetch 之前）：{blocked}'
    assert m.STATE['running'] is False, '被拦住时不该把后端状态置成 running'
    print('  ✓ 清空采集数量 → 点「开始搜索」被拦下（有提示、零请求、后端未被唤起）')

    page.get_screenshot(path=PNG_TARGET, full_page=True)
    print('  截图：', PNG_TARGET, os.path.getsize(PNG_TARGET), 'bytes')

    print('\n✅ 预览 + 实时明细表 + 顶栏导航 + 自定义搜索词 + 国家限定 + 实时明细删除 + '
          '采集数量卡 真机校验全部通过')
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
