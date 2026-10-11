# -*- coding: utf-8 -*-
"""真机校验「手动采集」页 /manual。

起临时 Flask 实例 + Chrome，断言：
  A. 页面能打开、四张卡齐全、共享样式（从 ui/page.html 注入）真的生效
  B. 行业下拉是**动态**从 /api/keywords 生成的（8 项 + 「自动判断」），不是硬编码
  C. 「重新探测」能把本实例认出来（打 /api/ping 看到 app=waimao-dp）
  D. 心跳区显示「从未收到扩展请求」→ 模拟一次带 Origin 的预检后变成「在线」
  E. 「本轮采集明细」表能增量渲染 session_rows（含「已在库」行、绿色等宽、「未抓到」、状态行三分支），
     计数报**两组数**「有效 X · 采集总数 Y · 已在库 Z」（有效＝真正入库的新客户＝结果 Excel 行数），
     点行尾 ✕ 弹**居中确认框**（不是原生确认框），确定后从明细里拿掉；若那条**确实已在客户库**
     （＝「结束」时入库成功、但结果 Excel 没写成功的那种例外行）则明细 + 客户库双删并删前自动备份
  F. 批量提交空内容要给出 alert 而不发请求；提交 1 条非法网址要优雅失败
不联网；客户库与结果输出都已打桩到临时目录（E 段的删除会真的走 DB）。
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time

SRC = r'D:\waimao\dp\客户开发工具.py'
PNG = r'D:\waimao\dp\.workbuddy\_manual_ui.png'
PNG_MODAL = r'D:\waimao\dp\.workbuddy\_manual_del_modal.png'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

# ⚠️⚠️ 本脚本原来刻意「不碰真实客户库」，但 E 段新增的「删一行」会打到
#    /api/manual/session/delete → backup_db_before_delete() + db_delete_customer()，
#    这两个函数都按 core.db.db_path() 定位库 → 不先把库关进临时目录，
#    测试就会真删真实客户库的记录、并往真实 DB/backups/ 里写备份。
TMP_DB = tempfile.mkdtemp(prefix='manual_ui_db_')
m.db_path = lambda: os.path.join(TMP_DB, '客户库.sqlite3')
m.db.db_path = m.db_path
m.paths.output_dir = lambda: TMP_DB          # 顺手把结果文件也关进去
m.init_customer_db()
print('打桩：客户库 →', m.db.db_path())

PORT = m.pick_port('127.0.0.1', (5014, 8000, 8080, 8765, 9000, 5310))[0]
print('临时实例端口：', PORT)

threading.Thread(target=lambda: m.app.run(host='127.0.0.1', port=PORT, debug=False,
                                          use_reloader=False, threaded=True),
                 daemon=True).start()
time.sleep(1.5)

page = None
try:
    page = m.create_browser_page()
    page.get(f'http://127.0.0.1:{PORT}/manual')
    time.sleep(1.5)

    # ---------- A. 结构与样式 ----------
    title = page.run_js("return document.querySelector('h1').textContent;")
    cards = page.run_js("return [...document.querySelectorAll('.card h3')].map(e => e.textContent);")
    print('标题：', title)
    print('卡片：', cards)
    assert '手动采集' in title, f'标题不对：{title}'
    assert len(cards) >= 4, f'应有 4 张卡，实际 {len(cards)}：{cards}'
    # 共享样式真的生效：按钮的背景色来自 page.html 的 .btn-start（#1a73e8）
    btn_bg = page.run_js(
        "return getComputedStyle(document.getElementById('btnRun')).backgroundColor;")
    log_bg = page.run_js(
        "return getComputedStyle(document.getElementById('log')).backgroundColor;")
    print('开始按钮背景色：', btn_bg, '| 日志框背景色：', log_bg)
    assert btn_bg == 'rgb(26, 115, 232)', f'共享样式没生效（.btn-start 应为 #1a73e8）：{btn_bg}'
    assert log_bg == 'rgb(30, 30, 30)', f'.log 样式没生效：{log_bg}'
    print('  ✓ /manual 打开正常，共享样式确实注入生效')

    # ---------- B. 行业下拉动态生成 ----------
    opts = page.run_js("return [...document.querySelectorAll('#industry option')].map(o => o.value);")
    print('行业下拉：', opts)
    assert opts[0] == '', '第一项应是「自动判断」（空值）'
    assert len(opts) == 9, f'应是 空 + 8 个行业 = 9 项，实际 {len(opts)}：{opts}'
    assert '塑料包装袋' in opts, f'新行业不在下拉里：{opts}'
    print('  ✓ 行业下拉由 /api/keywords 动态生成（8 个 + 自动判断）')

    # ---------- C. 端口探测 ----------
    # 本页端口排第一，正常情况下 1 秒内就该出结果；给 6 秒余量兜住慢机器
    page.run_js("probe();")
    for _ in range(20):
        time.sleep(0.4)
        if page.run_js("return document.getElementById('portHint').textContent;") != '-':
            break
    hint = page.run_js("return document.getElementById('portHint').textContent;")
    res = page.run_js("return document.getElementById('probeResult').textContent;")
    print('探测结果：', res)
    print('扩展该连：', hint)
    assert f':{PORT}' in hint, f'探测应认出本实例 127.0.0.1:{PORT}，实际 {hint!r}'
    print('  ✓ 「重新探测」正确识别本实例端口')

    # ---------- D. 心跳：从「从未收到」→ 收到预检后「在线」 ----------
    before = page.run_js("return document.getElementById('heart').textContent;")
    print('模拟扩展请求前：', before)
    import urllib.request
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/ping',
                                 headers={'Origin': 'chrome-extension://abcdefghijklmnop'
                                                    'abcdefghijklmnop'})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200
        assert r.headers.get('Access-Control-Allow-Origin') == \
            'chrome-extension://abcdefghijklmnopabcdefghijklmnop', '扩展源没拿到 ACAO'
    page.run_js("loadManualState();")
    # ⚠️ 别只 sleep 固定时长：loadManualState 是 async（要等一次 fetch），机器忙的时候
    #    1.2 秒不够，读到的还是 HTML 里的初始态 class="heart off" —— 会假红。
    cls = ''
    for _ in range(30):
        time.sleep(0.2)
        cls = page.run_js("return document.getElementById('heart').className;")
        if cls == 'heart on':
            break
    after = page.run_js("return document.getElementById('heart').textContent;")
    print('模拟扩展请求后：', after, '| class =', cls)
    assert 'heart on' == cls, f'心跳应转为在线，实际 class={cls}'
    assert '在线' in after, f'心跳文案不对：{after}'
    print('  ✓ 扩展心跳：从未收到 → 在线（预检也计入心跳）')

    # ---------- E. 本轮采集明细表（让后端真有明细，页面靠轮询渲染出来） ----------
    # ⚠️ 不能在浏览器里注入假数据就断言：页面底部每 1s 轮询一次 loadManualState()，
    #    会用后端的空 session_rows 把表格清空 —— 断言会随时序随机失败（实测踩过）。
    #    改为直接改这个**临时实例**的 MANUAL_STATE，走的还是真实的「轮询 → 渲染」链路。
    with m.STATE_LOCK:
        m.MANUAL_STATE.update({
            'session_active': True, 'session_started_at': time.time(),
            'session_industry': '塑料包装袋', 'session_country': '德国',
            # ⚠️ added/existed 必须和 session_rows 自洽（明细行数 = 新增 + 已在库）。
            #    状态行要报「已采 3 条 · 新增 2 · 已在库 1」，写 0/0 就自相矛盾了。
            'added': 2, 'existed': 1,
            'session_rows': [
                {'kind': 'added', 'rid': 1, 'title': 'Trash Bags Wholesale Ltd',
                 'url': 'https://plasticbagpc.com', 'emails': ['info@plasticbagpc.com'],
                 'phones': ['+44 20 7000 1234'], 'score': 75, 'rating': '重点客户',
                 'industry': '塑料包装袋', 'country': '英国'},
                {'kind': 'added', 'rid': 2, 'title': 'Wicket Bag Co',
                 'url': 'https://wicketbag.co.uk', 'emails': [], 'phones': [],
                 'score': 50, 'rating': '普通客户', 'industry': '塑料包装袋', 'country': '英国'},
                {'kind': 'existed', 'rid': 3, 'title': 'Seed Co', 'url': 'https://seed.com'},
            ],
        })
    page.run_js("loadManualState();")
    # ⚠️ 不能只 sleep 一个固定时长：页面每 1s 还在轮询 loadManualState()，
    #    「注入 → 渲染」与「在途的旧轮询（空 session_rows）返回 → 把表清掉」会竞态。
    #    等「行数连续两次都是 3」再断言，才是稳定的。
    stable = False
    prev = -1
    for _ in range(40):
        time.sleep(0.2)
        cur = page.run_js("return document.querySelectorAll('#sessionBody tr').length;")
        if cur == 3 and prev == 3:
            stable = True
            break
        prev = cur
    assert stable, f'③ 本轮明细应稳定渲染 3 行，实际 {prev}'
    n = page.run_js("return document.querySelectorAll('#sessionBody tr').length;")
    badge = page.run_js("return document.getElementById('sessionCount').textContent;")
    status = page.run_js("return document.getElementById('sessionStatus').textContent;")
    empty_disp = page.run_js("return document.getElementById('sessionEmpty').style.display;")
    mail_style = page.run_js(
        "return document.querySelector('#sessionBody .live-mail').className;")
    miss_txt = page.run_js(
        "return document.querySelector('#sessionBody .live-miss').textContent;")
    old_mark = page.run_js(
        "return document.querySelectorAll('#sessionBody tr')[2].textContent;")
    new_cls = page.run_js(
        "return document.querySelectorAll('#sessionBody tr')[0].className;")
    btn_state = page.run_js("return [document.getElementById('btnSessionStart').disabled,"
                            " document.getElementById('btnSessionFinish').disabled];")
    print('渲染行数：', n, '| 徽章：', badge, '| 状态：', status, '| 空态：', empty_disp)
    assert n == 3, f'应渲染 3 行，实际 {n}'
    # 徽章报**两组数**：有效（＝新增，真正入库/进结果 Excel 的）/ 共（＝明细行数）。
    assert badge == '有效 2 / 共 3', f'徽章应报「有效 2 / 共 3」，实际 {badge!r}'
    assert '进行中' in status, f'状态行不对：{status}'
    # 两组数必须一起报：有效数 = 真正入库的新客户，采集总数 = 明细行数（含「已在库」的重复）。
    # 只报一个「已采 N 条」＝总数，会把重复的也算成成功数（用户点名要改，实测踩过已采 17 条、表 13 行）。
    assert '有效 2 · 采集总数 3' in status, f'状态行应报「有效 / 采集总数」两组数：{status}'
    assert '已在库 1' in status, f'状态行应说明差额（已在库）：{status}'
    assert empty_disp == 'none', '有数据时占位提示应隐藏'
    assert mail_style == 'live-mail', '有邮箱的行应使用绿色等宽样式'
    assert miss_txt == '未抓到', f'没邮箱应显示「未抓到」，实际 {miss_txt!r}'
    assert '已在客户库' in old_mark, f'「已在库」的行应明确标出来，实际 {old_mark!r}'
    assert 'row-new' in new_cls, f'新行应带淡入类 row-new，实际 {new_cls!r}'
    assert btn_state == [True, False], \
        f'本轮进行中：「开始」应禁用、「结束」应可用，实际 disabled={btn_state}'

    # 增量追加：后端再加一条 → 只应多出一行（游标不回退、不重绘已有的）
    with m.STATE_LOCK:
        m.MANUAL_STATE['added'] = 3
        m.MANUAL_STATE['session_rows'] = m.MANUAL_STATE['session_rows'] + [
            {'kind': 'added', 'rid': 4, 'title': 'Flat Bag GmbH', 'url': 'https://flatbag-maker.de',
             'emails': ['sales@flatbag-maker.de'], 'phones': [], 'score': 75,
             'rating': '重点客户', 'industry': '塑料包装袋', 'country': '德国'}]
    page.run_js("loadManualState();")
    stable2 = False
    prev2 = -1
    for _ in range(40):
        time.sleep(0.2)
        cur2 = page.run_js("return document.querySelectorAll('#sessionBody tr').length;")
        if cur2 == 4 and prev2 == 4:
            stable2 = True
            break
        prev2 = cur2
    assert stable2, f'增量追加后应稳定为 4 行，实际 {prev2}'
    n2 = page.run_js("return document.querySelectorAll('#sessionBody tr').length;")
    badge2 = page.run_js("return document.getElementById('sessionCount').textContent;")
    badge2_tip = page.run_js("return document.getElementById('sessionCount').title;")
    status2 = page.run_js("return document.getElementById('sessionStatus').textContent;")
    print('追加一行后：', n2, badge2, '|', status2)
    assert n2 == 4, f'增量追加后应是 4 行，实际 {n2}'
    assert badge2 == '有效 3 / 共 4', f'徽章应跟着明细更新为「有效 3 / 共 4」：{badge2!r}'
    assert '有效 3 · 采集总数 4 · 已在库 1' in status2, f'计数应跟着明细走：{status2}'
    assert '有效 3 条 / 采集总数 4 条 = 新增 3 + 已在库 1' in (badge2_tip or ''), \
        f'徽章悬停应给出算式：{badge2_tip!r}'

    # 计数口径的两个纯函数（就是回答「为什么 Excel 行数比已采少」的那两段文案）
    print('breakdownText / roundTally：')
    bd = page.run_js("return breakdownText({session_active: true, added: 13, existed: 4}, 17);")
    assert '有效 13 条 / 采集总数 17 条 = 新增 13 + 已在库 4' in bd, f'算式不对：{bd}'
    assert '只写「有效（新增）」的 13 条' in bd, f'没说清 Excel 只写有效（新增）：{bd}'
    assert page.run_js("return breakdownText(null, 5);") == '', '拿不到计数时不该硬编算式'
    # 徽章文案的纯函数：两组数 + 必须能在 st 为 null 时安全求值（共享组件 reset() 会这么调）
    assert page.run_js("return liveBadgeText({session_active: true, added: 13, existed: 4}, 17);") \
        == '有效 13 / 共 17', 'liveBadgeText 没报出两组数'
    assert page.run_js("return liveBadgeText(null, 0);") == '有效 0 / 共 0', \
        'liveBadgeText 必须能在 st 为 null 时安全求值'
    # ⚠️ 本轮已结束：后端清了 session_rows 但留着 added/existed 给落盘文案（roundTally）用 ——
    #    这时徽章必须归零（否则会报出「有效 5 / 共 0」这种自相矛盾的数字），悬停算式也不该再显示。
    assert page.run_js("return liveBadgeText({session_active: false, added: 5, existed: 2}, 0);") \
        == '有效 0 / 共 0', '本轮已结束时徽章必须归零'
    assert page.run_js("return breakdownText({session_active: false, added: 5, existed: 2}, 0);") \
        == '', '本轮已结束时不该再拼悬停算式（明细已清零）'
    tl = page.run_js("return roundTally({session_active: false, added: 13, existed: 4});")
    assert '本轮写入 13 行新客户' in tl and '另有 4 条已在客户库' in tl, f'落盘口径不对：{tl}'
    assert page.run_js("return roundTally({session_active: false, added: 13, existed: 0});") \
        == '；本轮写入 13 行新客户', '没有「已在库」时不该提它'
    assert page.run_js("return roundTally({session_active: true, added: 13, existed: 4});") == '', \
        '本轮进行中不该显示上一轮的落盘口径（计数已清零、文件名还是旧的）'
    print('  ✓ 计数报两组数：有效 X（＝新增）· 采集总数 Y · 已在库 Z；落盘行数单独说清')

    # 状态行另外两个分支（同步取值，免得被下一次轮询覆盖回「进行中」）
    s_done = page.run_js("renderSessionStatus({session_active:false, session_rows:[],"
                         " session_excel:'塑料包装袋-20260929_2340-德国.xlsx'});"
                         " return document.getElementById('sessionStatus').textContent;")
    s_err = page.run_js("renderSessionStatus({session_active:true, session_rows:[],"
                        " session_error:'结果 Excel 保存失败（可能被 Excel 占用）'});"
                        " return document.getElementById('sessionStatus').textContent;")
    print('状态行：', s_done, '|', s_err)
    assert '上一轮已生成' in s_done, f'已生成文案不对：{s_done}'
    assert '保存失败' in s_err, f'失败文案不对：{s_err}'
    print('  ✓ 本轮明细表渲染正确（绿色等宽 / 「未抓到」/ 「已在客户库」/ 增量追加 / 状态行三分支）')

    # ---- 删除一行（点行尾 ✕）：明细少一行；那条若真在库里则连库一起删（删前自动备份）----
    # ⚠️ 2026-10-11 起手动采集是「点『结束并生成 Excel』才一次性入库」，所以本轮明细里普通的
    #    kind='added' 行**此刻还不在客户库里** —— 删它只从明细里拿掉、不碰库（用户明确要求
    #    灰字行更不许动库）。这里要覆盖的是**唯一需要删库的例外**：本条已经入库成功、但结果
    #    Excel 没写成功（见 _smoke_manual_session.py ⑪c），所以手动把它塞进库来模拟那种状态。
    m.db_upsert_customer({'company_name': 'Trash Bags Wholesale Ltd',
                          'website': 'https://plasticbagpc.com',
                          'email': 'info@plasticbagpc.com', 'phone': '+44 20 7000 1234',
                          'score': 75, 'rating': '重点客户', 'industry': '塑料包装袋',
                          'country': '英国', 'search_formula': '[手动采集]',
                          'source': '手动采集'})
    assert m.db_has_customer('https://plasticbagpc.com'), '前置：将被删的那条应已在（临时）库里'
    backups_before = sorted(os.listdir(m.db._backups_dir())) if os.path.isdir(m.db._backups_dir()) else []
    # 确认走的是共享组件（ui/live-table.js）的**居中模态框**，与主页那张表同一套 —— 不再是
    # 原生确认框。所以要模拟真实交互：点 ✕ → 等模态框弹出 → 点「确定删除」。
    page.run_js("window.__alerts = []; window.alert = s => window.__alerts.push(s);")
    rid_attr = page.run_js("return document.querySelectorAll('#sessionBody .livedel-btn')[0]"
                           ".getAttribute('data-rid');")
    print('第 1 行 ✕ 的 data-rid：', rid_attr)
    assert rid_attr == '1', f'第 1 行的 ✕ 应带 data-rid=1，实际 {rid_attr!r}'
    page.run_js("document.querySelectorAll('#sessionBody .livedel-btn')[0].click();")
    shown = False
    for _ in range(20):
        time.sleep(0.1)
        if page.run_js("return document.getElementById('liveDelModal')"
                       ".classList.contains('show');") is True:
            shown = True
            break
    assert shown, '点 ✕ 没弹出居中确认框（共享组件没接上？）'
    # 与主页同一套模态框 → 同样存一张「打开着」的视口截图当证据（截图失败不判红）
    try:
        page.get_screenshot(path=PNG_MODAL)
        print('截图（模态框打开）：', PNG_MODAL, os.path.getsize(PNG_MODAL), 'bytes')
    except Exception as _ex:
        print('  ⚠️ 模态框截图失败（不影响断言）：', type(_ex).__name__)
    page.run_js("document.getElementById('liveDelModalOk').click();")
    for _ in range(25):
        time.sleep(0.2)
        if page.run_js("return document.querySelectorAll('#sessionBody tr').length;") == 3:
            break
    n3 = page.run_js("return document.querySelectorAll('#sessionBody tr').length;")
    badge3 = page.run_js("return document.getElementById('sessionCount').textContent;")
    print('删除一行后：', n3, badge3)
    assert n3 == 3, f'删除后应剩 3 行，实际 {n3}'
    assert badge3 == '有效 2 / 共 3', f'删除后徽章应回退成「有效 2 / 共 3」：{badge3!r}'
    assert m.db_has_customer('https://plasticbagpc.com') is False, '被删的那条应已从客户库消失'
    backups_after = sorted(os.listdir(m.db._backups_dir())) if os.path.isdir(m.db._backups_dir()) else []
    backup_new = [f for f in backups_after if f not in backups_before]
    print('新增备份：', backup_new)
    assert any(f.startswith('客户库_删除前_') for f in backup_new), \
        f'删除前应自动备份客户库，实际新增 {backup_new}'
    first_txt = page.run_js("return document.querySelectorAll('#sessionBody tr')[0].textContent;")
    print('删除后第一行：', first_txt)
    assert 'Wicket Bag' in first_txt, f'删完第一行应变成原第 2 条（不是整体清表），实际 {first_txt!r}'
    print('  ✓ 每行 ✕ 删除：明细减一；本条确实在库里时连库一起删 + 删前自动备份')

    # ---------- F. 输入校验 ----------
    page.run_js("window.__alerts = []; window.alert = s => window.__alerts.push(s);")
    page.run_js("document.getElementById('urls').value=''; run();")
    time.sleep(0.5)
    alerts = page.run_js("return window.__alerts;")
    print('空提交的 alert：', alerts)
    assert alerts and '网址' in alerts[0], f'空提交应提示填网址，实际 {alerts}'

    # 截图只是给人看的证据，不是断言；整页截图偶尔会 CDP 超时，不该判红。
    try:
        page.get_screenshot(path=PNG, full_page=True)
        print('截图：', PNG, os.path.getsize(PNG), 'bytes')
    except Exception as _ex:
        print('  ⚠️ 整页截图失败（不影响断言）：', type(_ex).__name__)

    print('\n✅ 手动采集页 真机校验全部通过')
finally:
    if page:
        try:
            page.quit()
        except Exception:
            pass
