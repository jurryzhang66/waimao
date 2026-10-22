# -*- coding: utf-8 -*-
"""停止链路离线检查（2026-10-21，M30）：点「停止」能不能在 1~2 秒内真正停下来。

背景：用户反馈「按停止要等好一会儿」。排查结论是**慢在读侧**，不在停止请求本身：
  · `api_stop()` 是毫秒级的（不持锁、不做 IO）；
  · 但 worker 真正在干的活（page.get / wait_results / enrich）**完全不看停止标志**，
    而 `page.get()` 又没传 timeout → 吃 DrissionPage 出厂默认 30s × 4 次尝试 = 126 秒/次。
    一个客户要开 3 个页面（首页 + 2 个联系页）→ 最坏能把停止压住 7 分钟。

本脚本不启动浏览器、不联网、不写库，纯离线断言。最值钱的两条：
  ① nav() 在「页面永远加载不完」的情况下也要能被停止打断（否则 30 秒预算的优化等于白做）；
  ② 将来谁再写一个裸 page.get()，ast 会直接抓出来（那等于把 126 秒又请回来）。
"""
import ast
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, '客户开发工具.py')
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

src = open(SRC, encoding='utf-8').read()
page_html = open(os.path.join(ROOT, 'ui', 'page.html'), encoding='utf-8').read()
manual_html = open(os.path.join(ROOT, 'ui', 'manual.html'), encoding='utf-8').read()


# ================= 假页面（duck typing，不开浏览器） =================
class _StatesSeq:
    """按「轮询次数」回放 (ready_state, is_loading)。

    nav() 每轮先读 ready_state 再读 is_loading，所以推进点放在 is_loading 上，
    ready_state 只反映当前这一格 —— 顺手模拟了 CDP 的时序。
    """

    def __init__(self, seq, on_read=None):
        self.seq = seq
        self.i = 0
        self.on_read = on_read

    def _cur(self):
        return self.seq[min(self.i, len(self.seq) - 1)]

    @property
    def ready_state(self):
        return self._cur()[0]

    @property
    def is_loading(self):
        v = self._cur()[1]
        self.i += 1
        if self.on_read:
            self.on_read(self.i)
        return v


class NavPage:
    """记录 CDP 调用；get() 一旦被调到就直接报错（那是 M31 的病根）。"""

    def __init__(self, states=None):
        self.states = states or _StatesSeq([('loading', True)])
        self.cdp_calls = []
        self.html_reads = 0

    def run_cdp(self, cmd, **kw):
        self.cdp_calls.append((cmd, kw))
        if cmd == 'DOM.getDocument':
            return {'root': {'nodeId': 1}}
        if cmd == 'DOM.getOuterHTML':
            self.html_reads += 1
            return {'outerHTML': '<html><body>shell</body></html>'}
        return {'frameId': 'F', 'loaderId': 'L'}

    def get(self, *a, **k):
        raise AssertionError('nav() 又调 page.get 了 —— 它超时会 Page.stopLoading() 掐死页面')


# ================= 1. 常量 =================
print('---- 1. NAV_* / ENRICH_* 常量 ----')
assert m.NAV_BUDGET >= 10, f'单站预算太小（{m.NAV_BUDGET}s），慢站会大面积失败'
assert m.NAV_FIRE <= 2.0, \
    f'NAV_FIRE={m.NAV_FIRE}s 太大 —— 它是 CDP 点火命令的等待上限，必须压到 1~2 秒内'
assert 0 < m.NAV_POLL <= 0.5, f'NAV_POLL={m.NAV_POLL}s 太粗，停止会一顿一顿的'
assert m.NAV_SOFT < m.NAV_BUDGET, '软预算必须小于总预算，否则软预算形同虚设'
assert m.ENRICH_WAIT >= 8.0, \
    f'ENRICH_WAIT={m.ENRICH_WAIT}s 太小 —— 实测 ecohound.co.uk 的邮箱要到第 8 秒才渲染出来'
assert 0 < m.ENRICH_POLL <= 0.6, 'ENRICH_POLL 太粗，等邮箱这段的停止延迟会变长'
print(f'  ✓ 总预算 {m.NAV_BUDGET:.0f}s / 点火 {m.NAV_FIRE}s / 软预算 {m.NAV_SOFT:.1f}s '
      f'/ 粒度 {m.NAV_POLL}s')
print(f'  ✓ 等邮箱最多 {m.ENRICH_WAIT:.0f}s（首页）/ {m.ENRICH_CONTACT_WAIT:.0f}s（联系页），'
      f'复查粒度 {m.ENRICH_POLL}s')


# ================= 2. nav()：点火用 CDP，绝不碰 page.get =================
print('\n---- 2. nav()：CDP 点火 + 加载事件到了就返回 ----')
_orig_budget, _orig_soft, _orig_poll = m.NAV_BUDGET, m.NAV_SOFT, m.NAV_POLL
try:
    # 先「正在加载」再「加载完成」→ 应当立刻返回
    p = NavPage(_StatesSeq([('loading', True), ('loading', True), ('complete', False)]))
    t0 = time.time()
    assert m.nav(p, 'https://example.com/') is True, 'load 事件到了却返回 False'
    fast = time.time() - t0
    assert fast < 1.2, f'load 事件已到还等了 {fast:.2f}s'
    cmd, kw = p.cdp_calls[0]
    assert cmd == 'Page.navigate', f'点火不是 Page.navigate 而是 {cmd}'
    assert kw.get('_timeout') == m.NAV_FIRE, \
        f'Page.navigate 的 _timeout 不是 NAV_FIRE：{kw}（CDP 命令会一直等下去）'
    assert kw.get('url') == 'https://example.com/'
    print(f'  ✓ load 事件到了就在 {fast * 1000:.0f}ms 返回；点火 = '
          f'Page.navigate(_timeout={m.NAV_FIRE})，全程没碰 page.get')

    # ---- 3. nav()：页面永远加载不完 —— 停止必须能打断 ----
    print('\n---- 3. nav()：加载不完成时也能被停止打断 ----')
    m.NAV_BUDGET = 30.0            # 故意给足预算：证明停止不靠预算耗尽
    p = NavPage(_StatesSeq([('loading', True)],
                           on_read=lambda i: m.STATE.__setitem__('stop', i >= 3)))
    t0 = time.time()
    assert m.nav(p, 'https://slow.example/') is False, '用户点了停止，nav 却返回了 True'
    cost = time.time() - t0
    assert cost < 1.5, f'停止花了 {cost:.2f}s（>1.5s 就又变成「按了没反应」）'
    print(f'  ✓ 页面一直转圈时，停止在 {cost:.2f}s 内生效（预算 30s 完全没拖后腿）')

    # ---- 4. nav()：软预算到点 ≠ 停止，要带着已有内容继续 ----
    print('\n---- 4. nav()：软预算到点按「超时继续」处理 ----')
    m.NAV_SOFT = 0.4
    m.NAV_POLL = 0.1
    p = NavPage(_StatesSeq([('loading', True)]))   # 永远加载不完，但没人点停止
    m.STATE['stop'] = False
    t0 = time.time()
    assert m.nav(p, 'https://hang.example/') is True, \
        '软预算到点却返回 False —— 会被上层当成「用户停止」，整轮任务被误杀'
    cost = time.time() - t0
    assert 0.3 <= cost < 2.0, f'软预算 0.4s 却用了 {cost:.2f}s'
    print(f'  ✓ 加载不完时按软预算 {cost:.1f}s 返回，继续解析已有内容（不当成停止）')
finally:
    m.NAV_BUDGET = _orig_budget
    m.NAV_SOFT = _orig_soft
    m.NAV_POLL = _orig_poll
    m.STATE['stop'] = False


# ================= 5. enrich()：停止时打标记、且不许白开标签页 =================
print('\n---- 5. enrich()：停止标记与半截数据 ----')


class _Tab:
    """只有 raw_html 走的那几条 CDP：DOM.getDocument / DOM.getOuterHTML。"""

    def __init__(self, html='<a href="mailto:sales@x.com">'):
        self.url = 'https://x.com/'
        self.html = html
        self.closed = 0
        self.states = _StatesSeq([('complete', False)])

    def close(self):
        self.closed += 1

    def run_cdp(self, cmd, **kw):
        if cmd == 'DOM.getDocument':
            return {'root': {'nodeId': 1}}
        if cmd == 'DOM.getOuterHTML':
            return {'outerHTML': self.html}
        return {'targetInfo': {'url': self.url}}

    def doc_loaded(self, timeout=None):
        raise AssertionError('enrich 不许再 wait.doc_loaded() —— 超时后它会 stopLoading 掐死页面')

    @property
    def wait(self):
        return self


class EnrichPage:
    def __init__(self):
        self.new_tab_calls = 0

    def new_tab(self, *a, **k):
        self.new_tab_calls += 1
        return _Tab()


_RealTime = m.time
_orig_nav = m.nav


class _FakeTime:
    """把 enrich 里那 0.5~1.5 秒的站间间隔变成 0（否则每次断言都要真睡）。"""
    @staticmethod
    def sleep(_s):
        pass

    @staticmethod
    def time():
        return _RealTime.time()


try:
    m.time = _FakeTime()

    # ① 进函数时就已停止 → 直接返回标记，且**一个标签页都不该开**
    m.STATE['stop'] = True
    try:
        ep = EnrichPage()
        info = m.enrich(ep, 'https://x.com/')
        assert info.get('stopped') is True, '已停止却返回了「正常结果」—— 半截数据会进客户库'
        assert ep.new_tab_calls == 0, '已经停止了还开了标签页去访问客户网站'
    finally:
        m.STATE['stop'] = False
    print('  ✓ 进去就停止：直接打 stopped 标记，不开标签页')

    # ② 导航途中被停止（nav 返回 False）→ 同样打标记
    m.nav = lambda *a, **k: False
    try:
        ep = EnrichPage()
        info = m.enrich(ep, 'https://x.com/')
        assert info.get('stopped') is True, 'nav 被停止后 enrich 没打 stopped 标记'
        assert ep.new_tab_calls == 1, 'nav 停止后不该再继续开下一个页面'
    finally:
        m.nav = _orig_nav
    print('  ✓ 导航途中停止：打标记并立刻收手（不再开联系页）')

    # ③ 正常情况：不许无端带 stopped 标记（否则每条都会被丢弃）
    m.nav = lambda *a, **k: True
    try:
        ep = EnrichPage()
        info = m.enrich(ep, 'https://x.com/')
        assert not info.get('stopped'), '正常补全也打了 stopped 标记 —— 会把所有记录丢光'
    finally:
        m.nav = _orig_nav
    print('  ✓ 正常补全不带 stopped 标记（只有真停止才丢行）')
finally:
    m.time = _RealTime
    m.STATE['stop'] = False


# ================= 6. 静态守卫：导航不许再散落各处 =================
print('\n---- 6. 静态守卫（ast）----')
tree = ast.parse(src)
get_calls, nav_calls = {}, {}


class _NavCallFinder(ast.NodeVisitor):
    def __init__(self):
        self.stack = []

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        cur = self.stack[-1] if self.stack else '<module>'
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr == 'get'
                and isinstance(f.value, ast.Name) and f.value.id in ('page', 'tab')):
            get_calls.setdefault(cur, []).append(node.lineno)
        if (isinstance(f, ast.Attribute) and f.attr == 'run_cdp'
                and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 'Page.navigate'):
            nav_calls.setdefault(cur, []).append(node.lineno)
        self.generic_visit(node)


_NavCallFinder().visit(tree)
assert not get_calls, (
    '⛔ 又出现 page.get/tab.get 了（M31 的病根：_wait_loaded 超时会 Page.stopLoading() '
    '把正在渲染的页面掐死）：' + '；'.join(f'{k}() 第 {v} 行' for k, v in get_calls.items()))
assert list(nav_calls) == ['nav'], \
    f'Page.navigate 只允许出现在 nav() 里，现在出现在：{nav_calls}'
print(f'  ✓ 全项目零 page.get（那是「邮箱抓不到」的病根）；{len(nav_calls["nav"])} 处 '
      f'Page.navigate 全部收归 nav()')

# 停止标志必须在 nav 的循环里被读到（只看一次是不够的）
nav_src = src[src.index('def nav('):]
nav_src = nav_src[:nav_src.index('def _serp_reset(')]
assert "STATE['stop']" in nav_src, 'nav() 里没有读 STATE[\'stop\']'
assert 'while True' in nav_src or 'while ' in nav_src, 'nav() 不是循环轮询 —— 停止延迟会跟着预算走'
assert 'is_loading' in nav_src, 'nav() 没有用 states.is_loading 判就绪'
print('  ✓ nav() 靠 is_loading/ready_state 轮询判就绪，循环里每轮读停止标志')

# 读 DOM 的三条铁律：不许 page.html / doc_loaded / run_js（按 ast 查真实调用，不看注释）
def _forbidden_uses(func_name, attrs=(), calls=()):
    """返回该函数体里真实用到的禁用属性/调用；注释与文档字符串不算。"""
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == func_name)
    hits = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr in attrs:
            hits.append((sub.attr, sub.lineno))
        elif isinstance(sub, ast.Call):
            f = sub.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')
            if name in calls:
                hits.append((name, sub.lineno))
    return hits


assert 'DOM.getOuterHTML' in src[src.index('def raw_html('):src.index('def nav(page')], \
    'raw_html 没用 DOM.getOuterHTML'
bad = _forbidden_uses('raw_html', attrs=('html', 'url'), calls=('doc_loaded', 'run_js'))
assert not bad, f'raw_html 里用了会阻塞/掐加载的写法：{bad}'
bad = _forbidden_uses('enrich', attrs=('html', 'url'), calls=('doc_loaded', 'wait_loaded'))
assert not bad, f'enrich 里又用回 tab.html / doc_loaded 了：{bad}'
print('  ✓ 读 DOM 只用 raw_html（DOM.getOuterHTML）；enrich 不再碰 tab.html / doc_loaded')

en_src = src[src.index('def enrich(page, url):'):]
en_src = en_src[:en_src.index('def _back_to_search(')]
assert '_grab_html' in en_src, 'enrich 没有走「边等边看」的 _grab_html —— 只读一次会漏掉晚渲染的邮箱'

gh_src = src[src.index('def _grab_html('):]
gh_src = gh_src[:gh_src.index('CONTACT_LINK_RE =')]
assert 'while' in gh_src and 'ENRICH_POLL' in gh_src, '_grab_html 不是轮询实现'
assert "STATE['stop']" in gh_src, '_grab_html 里没有停止检查（等邮箱最长 10 秒）'
assert 'clean_emails' in gh_src, '_grab_html 不是以「抓到邮箱」为退出条件'
print('  ✓ enrich 走 _grab_html 轮询等邮箱（抓到即走、可被停止打断）')

# wait_results 必须是四态，且循环里能感知停止
wr_src = src[src.index('def wait_results('):]
wr_src = wr_src[:wr_src.index('def type_search(')]
assert "'stopped'" in wr_src, 'wait_results 里没有 stopped 态'
assert "STATE['stop']" in wr_src, 'wait_results 循环里没有读停止标志（最长会干等 12 秒）'
print('  ✓ wait_results 四态 + 循环内停止检查')

# 两个调用方都必须丢弃 stopped 的那条
for name in ('def run_search(', 'def run_maps('):
    seg = src[src.index(name):]
    assert "info.get('stopped')" in seg, f'{name} 没有处理 enrich 的 stopped 标记（半截数据会入库）'
print('  ✓ run_search / run_maps 都丢弃「没抓完的那一条」')

# 停止三字段 / 状态回传 / 超时兜底
stop_api = src[src.index("def api_stop():"):]
stop_api = stop_api[:stop_api.index("@app.route('/api/status')")]
for key in ("STATE['stop']", "STATE['stopping']", "STATE['stopped']"):
    assert key in stop_api, f'api_stop 少了 {key}'
assert 'with STATE_LOCK' not in stop_api, \
    'api_stop 持锁了 —— 一旦 worker 正在写日志，停止请求会被挡住（这就是「按了没反应」）'
payload = src[src.index("def api_status():"):]
payload = payload[:payload.index('db_total')]
assert "'stopping'" in payload and "'stopped'" in payload, '/api/status 没回传 stopping / stopped'
cbp = src[src.index('def create_browser_page('):]
cbp = cbp[:cbp.index('def is_blocked(')]
assert 'retry_times' in cbp and 'timeouts' in cbp, \
    'create_browser_page 没设全局超时/重试兜底 —— 任何漏网的 page.get 又回到 126 秒'
print('  ✓ api_stop 三字段且不持锁；/api/status 回传 stopping/stopped；浏览器层有超时兜底')

# ================= 7. 前端：点了必须立刻看得见 =================
print('\n---- 7. 前端即时反馈 ----')
assert page_html.count('\nlet pollStopping = false;') == 1, \
    'pollStopping 必须是一处顶格声明（跨 script 重名会整段不执行）'
stop_js = page_html[page_html.index('async function stop()'):]
stop_js = stop_js[:stop_js.index('async function openFolder()')]
for need, why in (("disabled = true", '没有把停止键压灰（可以连点，每点都发一个 POST）'),
                  ('正在停止', '状态行没有立刻变成「正在停止…」'),
                  ('kickPoll()', '没有立刻补拉一帧（要等下一个整拍才更新）')):
    assert need in stop_js, f'stop()：{why}'
assert 'pollStopping = true' in stop_js, 'stop() 没有置 pollStopping'
setb = page_html[page_html.index('function setButtons(running)'):]
setb = setb[:setb.index('async function start()')]
assert 'pollStopping' in setb, 'setButtons 没考虑「正在停止」—— 收尾那 1~2 秒里按钮会被重新点亮'
assert "pollStopping = !!d.stopping" in page_html, 'poll() 没有从后端读 stopping'
assert 'd.stopped' in page_html, '结束文案没有区分「被用户停掉」和「自然跑完」'
assert '正在停止…' in page_html, '页面没有「正在停止…」这行文案'
print('  ✓ 点停止：压灰 + 立刻改文案 + 补拉一帧；收尾期间按钮不会再被点亮')

assert 'stopPending' in manual_html, '/manual 没有防连点的 stopPending'
assert '正在停止' in manual_html, '/manual 状态行没有「正在停止…」'
print('  ✓ /manual 同款防连点与中间态')

print('\n✅ 停止链路检查全部通过')
