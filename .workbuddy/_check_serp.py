# -*- coding: utf-8 -*-
"""反爬链路离线检查（2026-10-21，M29）：验证码识别 / 请求节奏 / 三态返回 / 静态守卫。

背景：用户反馈「太容易触发谷歌验证码」。排查结论是「不是提交频率高」（默认参数只发 4~6 次），
而是 ① 每次任务全新空白 profile（无 cookie）② 认不出外语拦截页 → 被当「没渲染」→ 15s 内重发 3 次
③ 撞码后不减速、无熔断。

本脚本不启动浏览器、不联网、不写真实客户库，纯离线断言。
最关键的两条是「正常页不许被误判成验证码」和「wait_results 不许再按 bool 用」—— 两者出错都不报错。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, '客户开发工具.py')
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

src = open(SRC, encoding='utf-8').read()


# ================= 假页面（duck typing，不开浏览器） =================
class _States:
    def __init__(self, loading=False):
        self.is_loading = loading


class FakePage:
    """只实现 has_captcha / wait_results 真正用到的那几个属性。"""

    def __init__(self, url='', html='', hit=(), loading=False):
        self._url = url
        self._html = html
        self._hit = set(hit)
        self.states = _States(loading)
        self.url_reads = 0
        self.html_reads = 0

    @property
    def url(self):
        self.url_reads += 1
        return self._url

    @property
    def html(self):
        self.html_reads += 1
        return self._html

    def ele(self, locator, timeout=None):
        return object() if locator in self._hit else None


# ================= 1. 验证码识别：命中要准，误报要零 =================
print('---- 1. has_captcha 三级判据 ----')

# ① URL 判据（语言无关，命中率最高；新版拦截都落在 /sorry/）
for u in ('https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Dx',
          'https://www.google.de/sorry/index',
          'https://www.google.com/recaptcha/challenge'):
    assert m.has_captcha(FakePage(url=u)) is True, f'URL 判据没认出拦截页：{u}'
print('  ✓ /sorry/ 与 /recaptcha/ 这类 URL 一律判为拦截（外语国家也认得出）')

# ② 选择器判据
for css in m.CAPTCHA_CSS:
    assert m.has_captcha(FakePage(url='https://www.google.fr/search?q=x', hit=[css])) is True, \
        f'选择器判据没生效：{css}'
print(f'  ✓ {len(m.CAPTCHA_CSS)} 个选择器（旧式表单 / 新式 reCAPTCHA）都能认')

# ③ 文案判据只在 deep=True 时取 html —— 浅查绝对不能读整页（很贵）
p = FakePage(url='https://x.com/a', html='our systems have detected unusual traffic')
assert m.has_captcha(p) is False, '浅查读了 html 就判定拦截（wait_results 每秒查一次，负担不起）'
assert p.html_reads == 0, f'浅查竟然读了整页 html（{p.html_reads} 次）'
assert m.has_captcha(FakePage(url='https://x.com/a', html='unusual traffic'), deep=True) is True, \
    'deep=True 时英文文案没认出来'
for txt in ('trafic inhabituel', 'ungewöhnlicher datenverkehr', 'tráfico inusual',
            'traffico insolito', 'ongebruikelijk verkeer'):
    assert m.has_captcha(FakePage(url='https://x.com/a', html=txt), deep=True) is True, \
        f'外语文案没认出来：{txt}'
print('  ✓ 文案判据只在 deep=True 取 html，且覆盖英/法/德/西/意/荷 6 种语言')

# ⛔ 最值钱的一条：正常页加载 reCAPTCHA 资源不许误报
normal = '<script src="https://www.google.com/recaptcha/api.js"></script><div class="g-recaptcha-x">'
assert m.has_captcha(FakePage(url='https://buyer.com/contact', html=normal), deep=True) is False, \
    '正常网页加载了 reCAPTCHA 资源就被判成验证码 —— 会白等 240 秒再把整轮停掉'
assert 'recaptcha' not in ''.join(m.CAPTCHA_TEXTS), \
    'CAPTCHA_TEXTS 里混进了 "recaptcha" 这种泛词（正常页也会命中）'
print('  ✓ 正常页加载 reCAPTCHA 资源不误报（CAPTCHA_TEXTS 不含泛词）')

# ⛔ 加载中不许读 page.url（它内部 doc_loaded，能把 12 秒预算一次吃光）
loading = FakePage(url='https://www.google.com/sorry/index', loading=True)
m.has_captcha(loading)
assert loading.url_reads == 0, \
    '页面加载中就读了 page.url —— 会阻塞在 doc_loaded（最长 30s），把 wait_results 的预算吃光'
print('  ✓ 页面加载中不触碰 page.url（states.is_loading 门禁生效）')


# ================= 2. wait_results 四态 =================
print('\n---- 2. wait_results 返回 ok / empty / blocked / stopped ----')
_orig_count, _orig_cap = m.count_results, m.has_captcha
try:
    m.count_results = lambda page: 0
    m.has_captcha = lambda page, deep=False: True
    assert m.wait_results(FakePage(), min_items=3, timeout=1) == 'blocked', \
        '有验证码却没返回 blocked —— 会被 open_search 当成「壳页面」再连发 3 次'

    m.has_captcha = lambda page, deep=False: False
    assert m.wait_results(FakePage(), min_items=3, timeout=1) == 'empty', \
        '既无结果也无验证码应返回 empty（可重开）'

    m.count_results = lambda page: 5
    assert m.wait_results(FakePage(), min_items=3, timeout=3) == 'ok', '有结果却没返回 ok'

    # 第四态（M30）：用户点了停止 → 必须立刻返回 'stopped'，不能等到 12 秒窗口走完，
    # 更不能被当成 'empty' 又去重开一次。
    m.STATE['stop'] = True
    try:
        assert m.wait_results(FakePage(), min_items=3, timeout=12) == 'stopped', \
            '用户点了停止却没返回 stopped —— 会白等满 12 秒窗口再当成「壳页面」重开一次'
    finally:
        m.STATE['stop'] = False
finally:
    m.count_results, m.has_captcha = _orig_count, _orig_cap
print('  ✓ 四态齐全：blocked（必须退避）/ empty（可重开）/ ok（可解析）/ stopped（立刻退出）')


# ================= 3. serp_pace 节奏与长休息 =================
print('\n---- 3. serp_pace：偏态短等待 + 每 8 次长休息 ----')
_orig_sleep, _orig_log = m.sleep_check, m.log
sleeps = []
try:
    m.log = lambda *a, **k: None
    m.sleep_check = lambda s: (sleeps.append(float(s)), True)[1]
    m._serp_reset()
    for _ in range(9):
        m._serp_tick()
        assert m.serp_pace('page') is True, 'serp_pace 在未停止时应返回 True'

    short = [s for s in sleeps if s <= m.SERP_PAGE_MAX + 0.01]
    long_ = [s for s in sleeps if s >= m.SERP_LONG_REST_MIN - 0.01]
    assert len(sleeps) == 10, f'9 次请求应产生 10 段等待（9 短 + 1 长），实际 {len(sleeps)}：{sleeps}'
    assert len(long_) == 1, f'第 8 次请求后没有触发长休息：{sleeps}'
    assert all(m.SERP_PAGE_MIN - 0.01 <= s <= m.SERP_PAGE_MAX + 0.01 for s in short), \
        f'短等待超出 {m.SERP_PAGE_MIN}~{m.SERP_PAGE_MAX}：{short}'
    assert all(m.SERP_LONG_REST_MIN - 0.01 <= s <= m.SERP_LONG_REST_MAX + 0.01 for s in long_), \
        f'长休息超出 {m.SERP_LONG_REST_MIN}~{m.SERP_LONG_REST_MAX}：{long_}'
    print(f'  ✓ 9 次请求 = 9 段短等待 + 1 次长休息（{long_[0]:.0f}s）')

    # 偏态：同区间内应该出现明显低于中点的值（uniform 也有，这里只验证不越界 + 不是常量）
    assert len(set(round(s, 2) for s in short)) > 1, '短等待是常量 —— 少了随机性，机器特征依旧'

    # 停止信号必须能打断（长休息最长 2 分钟，不能失灵）
    m.sleep_check = lambda s: False
    m._serp_reset()
    assert m.serp_pace('query') is False, 'sleep_check 返回 False 时 serp_pace 必须返回 False'

    # query 档位比 page 档位慢
    slow = []
    m.sleep_check = lambda s: (slow.append(float(s)), True)[1]
    m._serp_reset()
    m.serp_pace('query')
    assert m.SERP_QUERY_MIN - 0.01 <= slow[0] <= m.SERP_QUERY_MAX + 0.01, \
        f'query 档位不落在 {m.SERP_QUERY_MIN}~{m.SERP_QUERY_MAX}：{slow}'
finally:
    m.sleep_check, m.log = _orig_sleep, _orig_log
print('  ✓ 停止信号可打断；query 档位（20~50s）与 page 档位（6~14s）分离')


# ================= 4. 静态守卫（防回退） =================
print('\n---- 4. 静态守卫 ----')
# ⛔ 三态之后不许再有人按 bool 用 wait_results（'empty'/'blocked' 都是真值 → 失败当成功）
assert 'if wait_results(page' not in src, \
    'wait_results 已是三态字符串，不能再写 `if wait_results(...)` —— 空壳页会被当成成功'
assert "== 'ok'" in src, 'open_search 没有按三态比较'
assert "'stopped'" in src, 'wait_results 的第四态 stopped 没有任何调用方处理'
# 旧的固定区间延时必须彻底退场（固定区间是最明显的脚本特征）
for pat in ('random.uniform(2, 4)', 'random.uniform(4, 8)', 'random.uniform(1.0, 2.5)'):
    assert pat not in src, f'旧的固定延时还在：{pat}'
assert "serp_pace('query')" in src, '每条查询跑完后没有走 serp_pace(query)'
# 反自动化开关只能出现一次（--disable-blink-features 是整串覆盖语义）
assert src.count('--disable-blink-features=AutomationControlled') == 1, \
    '--disable-blink-features 出现了不止一次（后一条会整串覆盖前一条）'
# 持久 profile 只给自动链路用；手动采集 / 补历史欠账必须保持临时 profile
assert src.count('create_browser_page(persistent=True)') == 2, \
    'persistent=True 只该出现在 run_search 与 run_maps 两处（手动采集共用会抢 profile）'
print('  ✓ 三态用法 / 旧固定延时 / 反自动化开关唯一性 / persistent 只两处')

# profile 目录必须在 DB 下，且必须被 git 忽略（public 仓库，里面是谷歌 cookie）
prof = m.chrome_profile_dir()
assert prof and os.path.normpath(prof).endswith(os.path.join('DB', '_chrome_profile')), \
    f'持久 profile 没落在 DB/_chrome_profile：{prof}'
gi = open(os.path.join(ROOT, '.gitignore'), encoding='utf-8').read()
assert 'DB/_chrome_profile/' in gi, \
    'DB/_chrome_profile/ 没进 .gitignore —— 公开仓库会把谷歌 cookie 提交上去'
gi_rules = [ln.strip() for ln in gi.splitlines()
            if ln.strip() and not ln.strip().startswith('#')]
assert 'DB/*' not in gi_rules, \
    '.gitignore 用了 DB/* 规则 —— 会把客户库与 ui_prefs.json 一起排掉'
print('  ✓ 持久 profile 落在 DB/_chrome_profile 且已被 .gitignore 排除')

# 锁清理清单不许包含目录级的 Default（那等于删 cookie）
assert 'Default' not in m._PROFILE_LOCKS, \
    '_PROFILE_LOCKS 里混进了 Default —— 清锁会把 cookie 一起删掉'
assert 'DevToolsActivePort' in m._PROFILE_LOCKS, '锁清单缺少 DevToolsActivePort'
print('  ✓ 锁清理只碰 5 个确切文件名（不含 Default）')

# 撞码置 stop 必须在锁内、log 在锁外（STATE_LOCK 非可重入，log 自己会抢同一把锁）
_wc = src[src.index('def wait_captcha('):]
_wc = _wc[:_wc.index('def sleep_check(')]
assert 'with STATE_LOCK:' in _wc and "STATE['stop'] = True" in _wc, '撞码两轮未通过时没有置 stop'
_seg = _wc[_wc.index('with STATE_LOCK:'):]
assert 'log(' not in _seg.split('\n')[1], '置 stop 的同一行里调了 log（锁内抢占会死锁）'
print('  ✓ 撞码熔断：锁内改标志、锁外记日志')

print('\n✅ 反爬链路检查全部通过')
