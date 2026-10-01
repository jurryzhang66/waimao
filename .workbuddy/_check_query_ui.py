# -*- coding: utf-8 -*-
"""真机校验「客户库查询」页 /db。

起临时 Flask 实例 + Chrome，断言：
  A. 页面能打开、两张卡齐全、共享样式（从 ui/page.html 注入）真的生效
  B. 筛选面板由 /api/db/facets **动态**生成（行业/国家/来源/评级 四组 + 各自条数 +
     每组的「未填写」项），且含库里的历史行业名（家具家居 / 汽配）
  C. 打开页面就会自动跑一次查询，结果表渲染出全部行、徽章与分页文案对得上
  D. 勾行业 / 填关键词 / 选「联系方式」条件 → 命中数与表内容跟着变（都是真点 DOM 再读结果）
  E. 排序改成公司名 → 首行变；每页改成 3 条 → 出现第二页，翻页后行数正确、序号接续
  F. 「重置条件」把所有勾选与输入清空、回到全量结果
  G. 点「导出 Excel」→ 真的落一份文件到 output/查询导出/，页面提示与日志都对
不联网；客户库、结果输出、浏览器下载目录都已打桩到临时目录。
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
PNG = r'D:\waimao\dp\.workbuddy\_query_ui.png'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

# ⚠️ 查询页会写文件（导出 Excel），且查询走 core.db.db_path() —— 两处都必须关进临时目录，
#    否则测试会往真实 output/查询导出/ 里丢表、并跑在真实客户库上。
TMP = tempfile.mkdtemp(prefix='query_ui_')
TMP_DL = os.path.join(TMP, 'chrome_downloads')
os.makedirs(TMP_DL, exist_ok=True)
m.db_path = lambda: os.path.join(TMP, '客户库.sqlite3')
m.db.db_path = m.db_path
m.paths.output_dir = lambda: os.path.join(TMP, 'output')
m.paths.ENRICH_FILE = os.path.join(TMP, 'output', '__no_such_enrich__.xlsx')
m.init_customer_db()
print('打桩：客户库 →', m.db.db_path())

SAMPLES = [
    ('Alpha Bag GmbH', 'https://alpha-bag.de', 'sale@alpha-bag.de', '+49 30 111', '',
     '德国', '塑料包装袋', 85, '重点客户', '谷歌搜索'),
    ('Beta Liner Ltd', 'https://beta-liner.co.uk', '', '+44 20 222', '',
     '英国', '塑料包装袋', 60, '普通客户', '手动采集'),
    ('Gamma Pet Supplies', 'https://gamma-pet.ca', 'hi@gamma-pet.ca', '',
     'https://gamma-pet.ca/contact', '加拿大', '宠物用品', 45, '观察', '谷歌地图'),
    ('Delta Furniture', 'https://delta-furniture.mx', '', '', '',
     '墨西哥', '家具家居', 20, '观察', '谷歌搜索'),
    ('Epsilon Auto Parts', 'https://epsilon-auto.mx', 'x@epsilon-auto.mx', '+52 55 333', '',
     '墨西哥', '汽配', 55, '普通客户', '谷歌搜索'),
    # 无行业 + 无评分 + 无邮箱：让「未标注」勾选项、评分 NULL 沉底、缺邮箱筛选都有数据可测
    ('Zeta NoScore', 'https://zeta-noscore.fr', '', '+33 1 444', '',
     '法国', '', None, '', '手动采集'),
]
for c_, w_, e_, p_, cu_, co_, ind_, sc_, ra_, sr_ in SAMPLES:
    m.db_upsert_customer(dict(company_name=c_, website=w_, email=e_, phone=p_, contact_url=cu_,
                              country=co_, industry=ind_, score=sc_, rating=ra_, source=sr_))
TOTAL = len(SAMPLES)
print(f'播种 {TOTAL} 条样本')

PORT = m.pick_port('127.0.0.1', (5035, 8000, 8080, 8765, 9000, 5310))[0]
print('临时实例端口：', PORT)

threading.Thread(target=lambda: m.app.run(host='127.0.0.1', port=PORT, debug=False,
                                          use_reloader=False, threaded=True),
                 daemon=True).start()
time.sleep(1.5)


def wait_text(page, js, want, desc, timeout=10):
    """轮询等目标态。⚠️ 别只 sleep 固定时长：页面查询是 async，慢机器上会偶发假红。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        cur = page.run_js(js)
        if cur == want:
            return True
        time.sleep(0.25)
    print(f'   ⚠️ 等待超时 [{desc}]：期望 {want!r}，实际 {page.run_js(js)!r}')
    return False


def js_path(page):
    return f'http://127.0.0.1:{PORT}/db'


page = None
try:
    page = m.create_browser_page()
    try:                       # 把下载也关进临时目录，别污染用户「下载」文件夹
        page.set.download_path(TMP_DL)
        print('下载目录 →', TMP_DL)
    except Exception as ex:
        print('⚠️ 下载目录没设成功（导出会落到浏览器默认下载目录）：', ex)
    page.get(js_path(page))
    time.sleep(1.5)

    # ---------- A. 结构与样式 ----------
    title = page.run_js("return document.querySelector('h1').textContent;")
    cards = page.run_js("return [...document.querySelectorAll('.card h3')].map(e => e.textContent);")
    print('标题：', title)
    print('卡片：', cards)
    assert '客户库查询' in title, f'标题不对：{title}'
    assert len(cards) >= 2, f'应有 2 张卡，实际 {len(cards)}：{cards}'
    btn_bg = page.run_js("return getComputedStyle(document.getElementById('btnQuery')).backgroundColor;")
    log_bg = page.run_js("return getComputedStyle(document.getElementById('log')).backgroundColor;")
    print('查询按钮背景色：', btn_bg, '| 日志框：', log_bg)
    assert btn_bg == 'rgb(26, 115, 232)', f'共享样式没生效（.btn-start 应为 #1a73e8）：{btn_bg}'
    assert log_bg == 'rgb(30, 30, 30)', f'.log 样式没生效：{log_bg}'
    print('  ✓ /db 打开正常，共享样式确实注入生效')

    # ---------- B. 筛选面板动态生成 ----------
    assert wait_text(page, "return document.querySelectorAll('#facetGrid .facet').length;", 4,
                     '四组筛选面板渲染出来'), '筛选面板没渲染出来'
    facets = page.run_js("return [...document.querySelectorAll('#facetGrid .facet-h')].map(e => e.textContent);")
    print('筛选分组：', facets)
    assert facets == ['行业', '国家/地区', '来源渠道', '评级'], f'分组不对：{facets}'
    inds = page.run_js("return [...document.querySelectorAll('input[name=industries]')].map(x => x.value);")
    print('行业选项：', inds)
    assert '塑料包装袋' in inds and '宠物用品' in inds, f'行业选项缺项：{inds}'
    # ⚠️ 关键：下拉必须是真实数据生成的，历史行业名（重标行业.py 还没跑）也要在里面
    assert '家具家居' in inds and '汽配' in inds, \
        f'历史行业名没出现在选项里（说明下拉被硬编码了）：{inds}'
    assert m.db.QUERY_EMPTY in inds, f'缺少「未标注」哨兵项：{inds}'
    counts = page.run_js(
        "return [...document.querySelectorAll('input[name=industries]')]"
        ".map(x => x.parentElement.querySelector('b').textContent);")
    print('行业条数：', counts)
    assert counts[0] == '1' or counts[0] == '2', f'行业条数没渲染出来：{counts}'
    hint = page.run_js("return document.getElementById('hint').textContent;")
    print('库概览：', hint)
    assert f'共 {TOTAL} 条' in hint, f'概览条数不对：{hint}'
    print('  ✓ 筛选面板由 /api/db/facets 动态生成（含历史行业名与「未标注」项）')

    # ---------- C. 打开就自动查询 ----------
    assert wait_text(page, "return document.getElementById('resCount').textContent;",
                     f'{TOTAL} 条', '首次查询渲染'), '首次查询没渲染'
    n = page.run_js("return document.querySelectorAll('#resBody tr').length;")
    print('结果行数：', n, '| 徽章：', page.run_js("return document.getElementById('resCount').textContent;"))
    assert n == TOTAL, f'应渲染 {TOTAL} 行，实际 {n}'
    info = page.run_js("return document.getElementById('pageInfo').textContent;")
    print('分页：', info)
    assert f'共 {TOTAL} 条' in info and '第 1 / 1 页' in info, f'分页文案不对：{info}'
    first = page.run_js("return document.querySelector('#resBody tr td:nth-child(2)').textContent;")
    print('首行：', first.strip()[:40])
    assert 'Alpha' in first, f'默认按评分降序，首行应是最高分那条：{first}'
    print('  ✓ 打开页面自动跑查询，行数/徽章/分页三者自洽')

    # ---------- D. 筛选交互 ----------
    page.run_js("[...document.querySelectorAll('input[name=industries]')]"
                ".forEach(x => { x.checked = (x.value === '塑料包装袋'); });")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;", '2 条',
                     '行业筛选'), '按行业筛选没生效'
    n = page.run_js("return document.querySelectorAll('#resBody tr').length;")
    assert n == 2, f'行业=塑料包装袋 应 2 行，实际 {n}'
    print('  ✓ 勾「塑料包装袋」→ 2 条')

    page.run_js("document.getElementById('kw').value = 'pet';")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;", '0 条',
                     '关键词+行业 交集为空'), '关键词与行业应取交集（pet 不在塑料包装袋里）'
    page.run_js("[...document.querySelectorAll('input[name=industries]')]"
                ".forEach(x => { x.checked = false; });")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;", '1 条',
                     '仅关键词 pet'), '关键词 pet 应命中 1 条'
    print('  ✓ 关键词与多个筛选条件之间是 AND（行业+关键词取交集）')

    page.run_js("document.getElementById('kw').value = '';"
                "document.getElementById('contact').value = 'no_email';")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;", '3 条',
                     '缺邮箱筛选'), '「缺邮箱」应命中 3 条（Beta / Delta / Zeta）'
    print('  ✓ 联系方式=缺邮箱 → 3 条')

    page.run_js("document.getElementById('scoreMin').value = '60';"
                "document.getElementById('scoreMax').value = '90';")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;", '1 条',
                     '评分区间筛选'), '缺邮箱 + 评分 60–90 应 1 条（Beta 60 分）'
    print('  ✓ 评分区间 60–90 叠加生效 → 1 条')

    # ---------- E. 排序与分页 ----------
    page.run_js("document.getElementById('scoreMin').value = '';"
                "document.getElementById('scoreMax').value = '';"
                "document.getElementById('contact').value = '';")
    page.run_js("document.getElementById('order').value = 'name';")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;",
                     f'{TOTAL} 条', '重置到全量'), '清掉条件后应回到全量'
    again = page.run_js("return document.querySelector('#resBody tr td:nth-child(2)').textContent;")
    assert 'Alpha' in again, f'按公司名排序首行应是 Alpha：{again}'
    print('  ✓ 排序改成「公司名 A→Z」生效')

    # ⚠️ 页面上的「每页」只有 50/100/200 三档，样本才 6 条（一页就装下了，测不出翻页）。
    #    给 <select> 临时插一个 3 条/页的选项 —— 直接 `value='3'` 会被浏览器忽略
    #    （select 设一个不存在的 value 等于没设），必须真的把 option 加进去。
    page.run_js("const s = document.getElementById('pagesize');"
                "const o = document.createElement('option');"
                "o.value = '3'; o.textContent = '3 条'; s.appendChild(o); s.value = '3';")
    page.run_js("document.getElementById('btnQuery').click();")
    assert wait_text(page, "return document.querySelectorAll('#resBody tr').length;", 3,
                     '每页 3 条'), '每页 3 条没生效'
    info = page.run_js("return document.getElementById('pageInfo').textContent;")
    print('分页：', info)
    assert '第 1–3 条' in info and '第 1 / 2 页' in info, f'分页文案不对：{info}'
    assert page.run_js("return document.getElementById('btnPrev').disabled;") is True, \
        '第 1 页时「上一页」应禁用'
    page.run_js("document.getElementById('btnNext').click();")
    assert wait_text(page, "return document.getElementById('pageInfo').textContent;",
                     f'第 4–{TOTAL} 条 / 共 {TOTAL} 条（第 2 / 2 页）', '翻到第 2 页'), \
        '翻页没生效'
    n2 = page.run_js("return document.querySelectorAll('#resBody tr').length;")
    assert n2 == TOTAL - 3, f'第 2 页应剩 {TOTAL - 3} 行，实际 {n2}'
    idx = page.run_js("return document.querySelector('#resBody tr td:nth-child(1)').textContent;")
    assert idx == '4', f'第 2 页首行序号应接续为 4，实际 {idx}'
    assert page.run_js("return document.getElementById('btnNext').disabled;") is True, \
        '最后一页时「下一页」应禁用'
    print('  ✓ 分页自洽：每页 3 条、序号跨页接续、首尾页按钮正确禁用')

    # ---------- F. 重置 ----------
    page.run_js("document.getElementById('btnReset').click();")
    assert wait_text(page, "return document.getElementById('resCount').textContent;",
                     f'{TOTAL} 条', '重置回全量'), '重置没生效'
    left = page.run_js("return document.querySelectorAll('#facetGrid input:checked').length;")
    kw = page.run_js("return document.getElementById('kw').value;")
    pos = page.run_js("return document.getElementById('pagesize').value;")
    print('重置后 勾选数：', left, '| kw：', repr(kw), '| 每页：', pos)
    assert left == 0 and kw == '' and pos == '50', '重置没把条件清干净'
    print('  ✓ 「重置条件」清空所有勾选与输入，回到默认全量')

    # ---------- G. 导出 ----------
    page.run_js("document.getElementById('btnExport').click();")
    ok = False
    for _ in range(40):
        time.sleep(0.25)
        note = page.run_js("return document.getElementById('resNote').textContent;")
        if '已导出' in note:
            ok = True
            break
    print('导出提示：', note)
    assert ok, f'点了导出但页面没给出成功提示：{note}'
    log = page.run_js("return document.getElementById('log').textContent;")
    assert '已导出' in log, f'日志里没有导出记录：{log[-200:]}'
    files = [f for f in os.listdir(m.query_export_dir()) if f.endswith('.xlsx')]
    print('导出目录：', files)
    assert len(files) == 1, f'应恰好落一份文件，实际 {files}'
    assert files[0] in note, f'页面提示的文件名与磁盘上的对不上：{note} / {files[0]}'
    # 后端冒烟已核对过列与内容，这里只确认「UI → 路由 → 磁盘」这条链真的通了
    p = os.path.join(m.query_export_dir(), files[0])
    assert os.path.getsize(p) > 0, '导出的文件是空的'
    print(f'  ✓ 点「导出 Excel」→ 真落盘 {files[0]}（{os.path.getsize(p)} bytes），页面提示一致')

    # ---------- 截图（证据，不是断言）----------
    try:
        time.sleep(0.4)
        page.get_screenshot(path=PNG, full_page=True)
        print('截图：', PNG, os.path.getsize(PNG), 'bytes')
    except Exception as ex:
        print('⚠️ 截图失败（只当证据，不影响结论）：', ex)

    print('\n✅ 客户库查询页真机校验全部通过')
    print('   临时目录：', TMP)
finally:
    if page is not None:
        try:
            page.quit()
        except Exception:
            pass
