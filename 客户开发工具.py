# -*- coding: utf-8 -*-
"""
谷歌客户开发网页工具（本地运行）
在浏览器里填产品词、勾选搜索条件、选国家，点"开始搜索"自动执行。
搜索与补全已合并为一个闭环：每搜到一个新网站，立刻访问它抓邮箱/电话并评分，
然后再去搜下一个；凑够目标数量就停，最后写出带邮箱/电话/评分的客户名单。
（批量清理客户库历史欠账的能力保留在命令行脚本「补历史欠账.py」里，界面上没有按钮。）

启动方法：python 客户开发工具.py  （会自动打开浏览器页面）
依赖：Flask、DrissionPage、openpyxl
"""
import threading
import time
import random
import re
import os
import glob
import json
import subprocess
import sqlite3
import atexit
from collections import Counter
from contextlib import closing
from datetime import datetime
import webbrowser
import tempfile
import socket
import sys
from urllib.parse import quote, parse_qs, urlparse, urljoin

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.common import Keys
from openpyxl import Workbook, load_workbook
from flask import Flask, request, jsonify, send_file
# requests 是 DrissionPage 的依赖，实际一定装得上；但仍软导入并留降级路径，
# 免得万一缺了它整个工具都起不来（手动采集的第②级会跳过，直接走 Chromium 升级）。
try:
    import requests
except ImportError:                      # pragma: no cover
    requests = None

# ---- sys.path 自举 ----
# .workbuddy/ 下的回归脚本用 importlib.util.spec_from_file_location + exec_module 加载本文件，
# 那时 sys.path[0] 是 .workbuddy/ 而不是项目根，`import core` 会失败；这里显式把项目根插进来。
# 同时它也保证「双击 .bat / 命令行直接 python 客户开发工具.py」之外的调用方式同样能用。
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ================= 从 core/ 包引入被拆出去的实现 =================
# ⚠️ 必须用**绝对导入**：项目根的「补历史欠账.py」用
# importlib.util.spec_from_file_location('kf', SRC) + exec_module 加载本文件，
# 本文件没有包上下文，相对导入会抛 "attempted relative import with no known parent package"。
# ⚠️ 这里是「同名 re-export」：外部脚本与 .workbuddy/ 回归脚本都按 `模块名.<名字>` 读取，
# 所以被搬走的名字必须在这里原样再导出一遍。
from core.config import (CONDITIONS, COND_TEMPLATE, COND_ROLES, COND_LANGS, cond_template,
                         KEYWORD_LIB, COUNTRIES, COUNTRY_CENTERS, COUNTRY_LIMITS,
                         COUNTRY_LIMIT_MODES, COUNTRY_LIMIT_DEFAULT, MAPS_CENTER_DEFAULT,
                         EXCLUDE_OPTIONS, EXCLUDE_DEFAULT, CHINA_FILTER_OPTIONS,
                         CHINA_FILTER_DEFAULTS, BLOCK_DOMAINS, BLOCK_SUBSTR,
                         SEARCH_ENGINE_PREFIX)
from core.paths import (LEGACY_RESULT_FILES, RESULT_DATE_RE, OUTPUT_DIRNAME, MAPS_PLACE_ID_RE,
                        _app_dir, output_dir, _safe_name_part, build_result_name,
                        ts_result_path, _result_time_key, find_latest_result,
                        query_export_dir, ts_query_export_path, QUERY_EXPORT_DIRNAME,
                        DB_DIR, DB_FILE)
# ⚠️ 刻意**不**写 `from core.paths import ENRICH_FILE` —— 它是会被重新赋值的活变量，
#    那样导入只能拿到快照。读写一律走 `paths.ENRICH_FILE`。
from core import paths       # 模块对象：_save_enrich_excel 要靠它写 paths.ENRICH_FILE
from core.state import (BASE_TOKEN, TABLE_ID, LARK_CLI, IMPORT_JSON, COUNTRY_STANDARD,
                        STATE, STATE_LOCK, MANUAL_STATE, log)
from core.db import (db_path, maps_place_key, normalize_domain, normalize_email,
                     db_connect, init_customer_db, db_upsert_customer, db_stats,
                     backup_db_before_delete, db_delete_customer, db_fix_website_keys,
                     db_query_customers, db_facet_counts, QUERY_MAX_LIMIT,
                     db_delete_customers_by_ids, QUERY_DELETE_MAX)
from core import db          # 模块对象：回归脚本要靠 m.db.db_path 才能把打桩打到 core.db 内部
# 页面模板本体在独立文件 ui/page.html（改样式/文案不用再碰 Python），
# 这里只把构建结果与构建函数拉回来：路由 `return PAGE_HTML` 与老脚本 `kf._build_page()` 都靠它。
# 手动采集页同理在 ui/manual.html（它复用 page.html 的样式块，样式只维护一份）。
from core.ui import PAGE_HTML, _build_page, MANUAL_HTML, _build_manual_page
# 第三页：客户库查询 /db（同样复用 page.html 的样式块）。
from core.ui import QUERY_HTML, _build_query_page


def __getattr__(name):
    """PEP 562 模块级属性兜底：把搬进 core/* 的「动态变量」实时转发出去。

    目前唯一需要它的是 `ENRICH_FILE`：它会被 `_save_enrich_excel()` 重新赋值，而项目根的
    「补历史欠账.py」第 58 行是在跑完 `enrich_core()` **之后**才读 `kf.ENRICH_FILE` 的，
    必须拿到最新值。`from core.paths import ENRICH_FILE` 只能拿到 import 那一刻的快照，
    所以改用本函数在属性访问时实时取。

    ⚠️ 只对「属性访问」生效（`kf.ENRICH_FILE`、`from kf import ENRICH_FILE`）。
       本模块**内部函数里的裸名 `ENRICH_FILE` 不走这里**（会 NameError），
       所以入口内部一律显式写 `paths.ENRICH_FILE`。
    ⚠️ 本模块一旦出现任何模块级 `ENRICH_FILE = ...` 赋值、或
       `from core.paths import ENRICH_FILE`，模块字典里就有了这个名字，本函数永久失效。
    """
    if not name.startswith('_'):        # 不碰 dunder，免得干扰导入机制
        from core import config, paths as _paths, state as _state, db as _db, ui as _ui
        for _mod in (config, _paths, _state, _db, _ui):
            if hasattr(_mod, name):
                return getattr(_mod, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')








def create_browser_page():
    """启动独立的 Chrome 调试实例，避免依赖用户手工开启 9222 端口。"""
    profile_dir = tempfile.mkdtemp(prefix='waimao_dp_chrome_')
    # 先向系统申请一个空闲端口，避免固定 9222 被其它 Chrome 占用。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        debug_port = sock.getsockname()[1]
    options = ChromiumOptions().set_local_port(debug_port)
    chrome_candidates = [
        # Playwright 自带的 Chromium 不受用户现有 Chrome 进程和配置影响。
        r'C:\Users\admin\AppData\Local\ms-playwright\chromium-1200\chrome-win64\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    ]
    chrome_path = next((p for p in chrome_candidates if os.path.exists(p)), '')
    if chrome_path:
        options.set_browser_path(chrome_path)
    options.set_user_data_path(profile_dir)
    options.set_argument('--remote-allow-origins=*')
    options.set_argument('--no-sandbox')
    options.set_argument('--disable-gpu')
    options.set_argument('--disable-popup-blocking')
    log('启动独立浏览器实例（自动分配调试端口）...')
    return ChromiumPage(options)


# ================= 搜索核心（复用原脚本） =================
def is_blocked(href):
    if not href or not href.startswith('http'):
        return True
    netloc = urlparse(href).netloc.lower().split(':', 1)[0].removeprefix('www.')
    if any(s in netloc for s in BLOCK_SUBSTR):
        return True
    if netloc.startswith(SEARCH_ENGINE_PREFIX):     # google.com.hk / google.de 等区域域名
        return True
    return any(netloc == d or netloc.endswith('.' + d) for d in BLOCK_DOMAINS)


def china_filter_terms(enabled_keys):
    """返回当前勾选的、需要追加到 Google 公式的排除词。"""
    enabled = set(enabled_keys or ())
    return ' '.join(query for key, query, _, _ in CHINA_FILTER_OPTIONS
                    if key in enabled and query).strip()


def china_filter_reasons(title, url, snippet='', emails=None, phones=None,
                         html_text='', enabled_keys=None):
    """按勾选项返回明确的中国供应商过滤原因。

    单独出现 China/中文/中国进口不会触发过滤；只有和供应商、工厂、联系方式或
    中国平台等明确信号组合时才过滤，避免误删真实海外进口商。
    """
    enabled = set(enabled_keys or ())
    if not enabled:
        return []
    emails = emails or []
    phones = phones or []
    text = ' '.join(str(x or '') for x in (title, url, snippet, html_text)).lower()
    host = normalize_domain(url)
    reasons = []

    platform_hosts = {
        'alibaba': ('alibaba.com',),
        'made-in-china': ('made-in-china.com',),
        'globalsources': ('globalsources.com',),
        '1688': ('1688.com',),
        'taobao': ('taobao.com', 'tmall.com'),
    }
    for key, hosts in platform_hosts.items():
        if key in enabled and any(host == h or host.endswith('.' + h) for h in hosts):
            reasons.append(f'命中{key}平台')

    if 'cn' in enabled and (host.endswith('.cn') or host == 'cn'):
        reasons.append('网站域名为 .cn')

    supplier_signal = bool(re.search(
        r'china\s+(?:manufacturer|supplier|factory|wholesaler)|'
        r'chinese\s+(?:manufacturer|supplier|factory)|'
        r'中国(?:供应商|厂家|工厂|制造商)', text, re.I))
    factory_signal = bool(re.search(
        r'(?:factory|manufacturer|supplier)\s+(?:in|from)\s+china|'
        r'(?:china|chinese)\s+(?:factory|manufacturer|supplier)', text, re.I))
    made_signal = bool(re.search(r'(?:made|manufactured)\s+in\s+china|中国制造', text, re.I))
    chinese_signal = bool(re.search(r'[\u4e00-\u9fff]', text))

    if 'supplier_words' in enabled and supplier_signal:
        reasons.append('标题/摘要命中中国供应商关键词')
    if 'factory_words' in enabled and factory_signal:
        reasons.append('标题/摘要命中中国工厂关键词')
    if 'made_in_china_words' in enabled and made_signal:
        reasons.append('标题/摘要命中中国制造关键词')

    platform_signal = bool(re.search(
        r'(?:supplier|manufacturer|factory)\s+(?:directory|platform|marketplace)|'
        r'b2b\s+(?:platform|marketplace)|供应商平台|供应商名录|厂家直销', text, re.I))
    if 'platform_words' in enabled and platform_signal and (supplier_signal or chinese_signal):
        reasons.append('命中中国供应商平台关键词')

    if 'phone_86' in enabled and (re.search(r'\+\s*86(?:[\s().-]*\d){6,}', text)
                                  or any(re.search(r'\+\s*86(?:[\s().-]*\d){6,}', str(p)) for p in phones)):
        reasons.append('联系方式含 +86 中国电话')
    if 'wechat' in enabled and re.search(r'\bwechat\b|\bweixin\b|微信', text, re.I):
        reasons.append('页面含微信/WeChat')
    if 'qq' in enabled and re.search(r'\bqq\b|腾讯', text, re.I):
        reasons.append('页面含 QQ')

    address_signal = bool(re.search(
        r'(?:中国|china|广东|浙江|江苏|福建|山东|深圳|广州|东莞|义乌|宁波|佛山)'
        r'.{0,40}(?:地址|工厂|厂家|制造|supplier|factory|manufacturer|road|street|road)', text, re.I))
    if 'address_cn' in enabled and address_signal:
        reasons.append('页面含明显中国地址/工厂信息')

    if 'email_cn' in enabled and any(str(e).lower().split('@')[-1].endswith('.cn') for e in emails):
        reasons.append('邮箱域名为 .cn')

    if 'competitor_cn' in enabled and (supplier_signal or factory_signal or (made_signal and chinese_signal)):
        reasons.append('命中明显中国同行/工厂信号')

    directory_signal = any(x in host for x in ('1688.com', 'alibaba.com', 'made-in-china.com',
                                                'globalsources.com', 'taobao.com', 'tmall.com'))
    if 'directory_cn' in enabled and directory_signal:
        reasons.append('命中中国 B2B 名录/供应商聚合站')
    return list(dict.fromkeys(reasons))


def url_key(href):
    p = urlparse(href)
    return p.netloc + p.path.rstrip('/')


def has_captcha(page):
    try:
        return 'unusual traffic' in page.html or bool(page.ele('#captcha-form', timeout=1))
    except Exception:
        return False


def wait_captcha(page, max_wait=180):
    if not has_captcha(page):
        return True
    log('⚠️ 检测到谷歌人机验证，请在浏览器窗口手动完成（脚本每3秒检测，最多等3分钟）')
    waited = 0
    while waited < max_wait and not STATE['stop']:
        time.sleep(3)
        waited += 3
        if not has_captcha(page):
            log('✅ 验证完成，继续')
            return True
    return False


def sleep_check(seconds):
    """可被停止标志打断的睡眠；正常睡完返回 True，被停止则 False"""
    end = time.time() + seconds
    while time.time() < end:
        if STATE['stop']:
            return False
        time.sleep(min(0.5, max(0, end - time.time())))
    return True


RESULT_LINK_CSS = 'css:a:has(h3)'      # 自然结果的标题链接


def search_url(formula, country_params='', start=0):
    """直连搜索 URL。实测向搜索框打字会先落到首页的 "Updating location..." 中间态，
    结果迟迟不渲染（a:has(h3) 抓到 0 条）；直连 /search?q= 则立刻有 9~10 条结果。"""
    url = 'https://www.google.com/search?q=' + quote(formula) + country_params
    if start:
        url += f'&start={start}'
    return url


def maps_search_url(query, country_code=MAPS_CENTER_DEFAULT, gl='', hl='en', city=''):
    """谷歌地图搜索 URL（路径式，非官方 api=1 形态 —— 路径式批量名录更稳）。

    定位靠两层：① 城市名直接进查询词（Google 官方推荐的位置限定方式，比 gl 硬）；
    ② @lat,lng,zoom 把地图视野锁到该国中心，影响返回的商家范围。
    hl/gl 与网页搜索是同一套参数语义。
    """
    q = ' '.join(x for x in ((query or '').strip(), (city or '').strip()) if x).strip()
    lat, lng = COUNTRY_CENTERS.get(country_code, COUNTRY_CENTERS[MAPS_CENTER_DEFAULT])
    url = f'https://www.google.com/maps/search/{quote(q)}/@{lat},{lng},11z'
    extra = []
    if hl:
        extra.append(f'hl={hl}')
    if gl:
        extra.append(f'gl={gl}')
    return url + (('?' + '&'.join(extra)) if extra else '')


def count_results(page):
    try:
        return len(page.eles(RESULT_LINK_CSS, timeout=1))
    except Exception:
        return 0


def wait_results(page, min_items=3, timeout=12):
    """等结果真正渲染出来再抓。旧版判断 div#search 已失效（新版谷歌页面没有 #search/#rso），
    改为数「标题链接」条数，并等它稳定两轮。返回 True 表示已就绪。"""
    end = time.time() + timeout
    last, stable, tick = -1, 0, 0
    while time.time() < end:
        n = count_results(page)
        if n >= min_items:
            if n == last:
                stable += 1
                if stable >= 1:
                    return True
            else:
                stable = 0
            last = n
        else:
            tick += 1
            if tick % 5 == 0 and has_captcha(page):     # page.html 较贵，每 5 秒才查一次
                if not wait_captcha(page):
                    return False
        time.sleep(1)
    return False


def type_search(page, formula):
    """兜底策略：向搜索框输入关键词并回车。返回是否成功发出。"""
    try:
        box = page.ele('textarea[name=q]', timeout=8) or page.ele('input[name=q]', timeout=5)
    except Exception:
        box = None
    if not box:
        return False
    try:
        box.click()
        time.sleep(random.uniform(0.3, 0.8))
        box.input(formula, clear=True)
        time.sleep(random.uniform(0.5, 1.2))
        box.input(Keys.ENTER)
        return True
    except Exception:
        return False


def open_search(page, formula, country_params, start=0, min_items=3, attempts=3):
    """打开搜索结果页，并确认结果真的渲染出来。
    实测谷歌偶尔只返回一个「壳页面」：搜索框在、结果区是空的（同时混着
    "Updating location" / 地区选择），此时 page.refresh() 无效，**重新导航一次即可恢复**。
    所以这里做多轮重开，最后一轮换成搜索框输入兜底。"""
    for i in range(attempts):
        if i:
            if not sleep_check(random.uniform(1.0, 2.5)):
                return False
        try:
            if i == attempts - 1:
                type_search(page, formula)              # 最后一轮换策略
            else:
                page.get(search_url(formula, country_params, start))
        except Exception as e:
            log(f'   打开搜索页失败（第 {i + 1} 次）：{type(e).__name__}: {e}')
            continue
        if wait_results(page, min_items=min_items, timeout=12):
            if i:
                log(f'   ↻ 第 {i + 1} 次重新打开后结果才渲染出来')
            return True
        if i < attempts - 1:
            log(f'   ↻ 结果没渲染出来（第 {i + 1} 次），重新打开搜索页…')
    log(f'   ⚠️ 连续 {attempts} 次都没取到结果，跳过本页')
    return False


def _is_search_engine_url(href):
    """是否落在搜索引擎自己的域名上（含 google.com.hk / google.de 这类区域站）。"""
    try:
        host = urlparse(href).netloc.lower().split(':', 1)[0].removeprefix('www.')
    except Exception:
        return False
    return host.startswith(SEARCH_ENGINE_PREFIX)


def _cite_domain(card):
    """结果卡片里的 <cite> 写着客户真实网址（形如「https://www.x.com › 路径」）。
    谷歌 /goto?url=<加密串> 没法直接解析，而 cite 是零成本的真域名来源（实测与真实跳转同域）。"""
    node = card
    for _ in range(4):
        try:
            node = node.parent()
        except Exception:
            break
        if node is None:
            break
        try:
            c = node.ele('css:cite', timeout=0)
        except Exception:
            c = None
        if not c:
            continue
        try:
            txt = (c.text or '').strip()
        except Exception:
            continue
        mm = re.search(r'https?://[^\s›]+', txt)
        if mm:
            return mm.group(0).rstrip('/')
        mm = re.match(r'([\w.-]+\.[a-z]{2,})', txt)
        if mm:
            return 'https://' + mm.group(1)
    return ''


def resolve_goto(page, href, card=None):
    """把结果链接换成客户真实网址，三种形态依次处理：
      ① 已经是目标站地址     → 原样返回
      ② /url?q=<明文地址>    → 直接解析（免联网）
      ③ /goto?url=<加密串>   → 无法解析：先用卡片里的 <cite>（真实域名、零成本），
                               再不行才真开一个标签让谷歌 302 跳过去。
    ⚠️ 区域域名（google.com.hk / google.de）同样算谷歌跳转链。原来只认 'google.com/goto'，
    在区域站下整条结果会被当成谷歌自己的链接、遭黑名单丢弃（实测一页 10 条全丢光）。"""
    href = (href or '').strip()
    if not href:
        return href
    if not _is_search_engine_url(href):
        return href
    try:
        q = parse_qs(urlparse(href).query).get('q', [''])[0]
    except Exception:
        q = ''
    if q.startswith('http'):
        return q
    dom = _cite_domain(card) if card is not None else ''
    if dom:
        return dom
    tab = None
    try:
        tab = page.new_tab(href)
        tab.wait.doc_loaded(timeout=15)
        time.sleep(0.4)
        return tab.url
    except Exception:
        return None
    finally:
        if tab:
            try:
                tab.close()
            except Exception:
                pass


def _closest_snippet(node):
    """往上找摘要容器；取不到就返回空字符串（绝不为此抛异常打断整轮搜索）。"""
    cur = node
    for _ in range(4):
        try:
            cur = cur.parent()
        except Exception:
            return ''
        if cur is None:
            return ''
        for css in ('css:.VwiC3b', 'css:[data-sncf]', 'css:span.aCOpRe',
                    'css:div[style*="line-clamp"]'):
            try:
                s = cur.ele(css, timeout=0)
            except Exception:
                s = None
            if s:
                try:
                    return (s.text or '').strip()
                except Exception:
                    return ''
    return ''


def extract_results(page, seen_titles, china_filters=None):
    """抓取一页自然结果。返回 (结果列表, 被黑名单过滤的条数)。
    seen_titles 只在确认保留后才写入，避免被过滤掉的标题污染去重集合。
    DrissionPage 4.1 的 parent() 找不到元素会抛异常而不是返回 None，故一律包 try。"""
    results, blocked = [], 0
    china_reasons = Counter()
    try:
        anchors = page.eles(RESULT_LINK_CSS, timeout=10)
    except Exception:
        anchors = []
    for a in anchors:
        try:
            h3 = a.ele('tag:h3', timeout=0)
            title = (h3.text or '').strip() if h3 else ''
        except Exception:
            title = ''
        if not title or title.startswith('AI Mode'):
            continue
        if title in seen_titles:
            continue
        try:
            raw = (a.attr('href') or '').strip()
        except Exception:
            raw = ''
        real = resolve_goto(page, raw, a)      # 传 a 是为了能从卡片 <cite> 兜底取真域名
        if not real or is_blocked(real):
            blocked += 1
            continue
        snippet = _closest_snippet(h3)
        reasons = china_filter_reasons(title, real, snippet=snippet,
                                       enabled_keys=china_filters)
        if reasons:
            blocked += 1
            for reason in reasons:
                china_reasons[reason] += 1
            continue
        seen_titles.add(title)
        results.append({'title': title, 'url': real, 'snippet': snippet})
    return results, blocked, dict(china_reasons)


# ================= 补全评分（复用原脚本） =================
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
EMAIL_OK = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$')
PHONE_RE = re.compile(r'(?:\+\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}')
NOISE_EMAIL = ['wixpress.com', 'shopify.com', 'squarespace.com', 'wix.com',
               'example.com', 'example.org', 'schema.org', 'google.com',
               'wordpress.org', 'myshopify.com']
CONTACT_PATHS = ['/contact', '/contact-us', '/pages/contact-us', '/contactus']
CTYPE_WORDS = ['wholesale', 'distributor', 'importer', 'trading', 'dealer', 'supplier', 'bulk']
PRODUCT_WORDS = ['litter', 'liner', 'cat', 'pet']
BLOG_WORDS = ['blog', 'news', 'article', 'tips-and-advice']

# ================= 手动采集（Chrome 扩展送 HTML 过来）=================
# 扩展把当前页的 outerHTML 一起送过来，我们直接在字符串上抽邮箱/电话 —— 不用再开浏览器，
# 且是**用户浏览器渲染后**的真实页面（不怕反爬、JS 异步渲染的邮箱也在）。
MAX_PAGE_HTML = 500_000                     # 清洗后最多留 500KB 交给正则
_STRIP_BLOCK_RE = re.compile(
    r'<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>', re.S | re.I)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name\s*=\s*["\']description["\'][^>]*content\s*=\s*["\'](.*?)["\']',
    re.S | re.I)
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def _sanitize_page_html(html):
    """把扩展送来的整页 HTML 压到能安全跑正则的规模。

    ⚠️ 先粗截再跑正则：outerHTML 可能好几 MB，直接把 `.*?` 丢上去会退化（甚至卡死）。
    ⚠️ 剥掉 script/style/noscript/svg/template：邮箱多为 `mailto:` 或可见文本，剥完照样能抽到，
       而这几类块里塞的噪声（base64、内联 JSON）却是主要误报来源。
    """
    s = (html or '')[:4 * MAX_PAGE_HTML]
    s = _STRIP_BLOCK_RE.sub(' ', s)
    return s[:MAX_PAGE_HTML]


def _meta_description(html):
    """抽 <meta name="description"> 当摘要；抽不到就交给调用方回退标题。"""
    m = _META_DESC_RE.search((html or '')[:200_000])
    if not m:
        return ''
    return re.sub(r'\s+', ' ', m.group(1)).strip()[:300]


def _find_contact_url(html, base_url):
    """从页面里找一个「联系页」链接（比盲猜 /contact 准得多）。
    找不到返回空串，由调用方按 CONTACT_PATHS 兜底。"""
    base = urlparse(base_url)
    for m in re.finditer(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         (html or '')[:200_000], re.S | re.I):
        href, text = m.group(1), re.sub(r'<[^>]+>', '', m.group(2)).lower()
        if not re.search(r'contact|联系|about|contacto|kontakt', href + ' ' + text, re.I):
            continue
        if re.search(r'\.(png|jpe?g|gif|svg|css|js)$', href, re.I) or href.startswith(('mailto:', 'tel:', '#')):
            continue
        full = urljoin(f'{base.scheme}://{base.netloc}/', href)
        # 只认同站链接，避免跳到社交平台
        if urlparse(full).netloc == base.netloc:
            return full
    return ''


def clean_emails(html):
    out = []
    for m in EMAIL_RE.findall(html):
        dom = m.split('@')[1].lower()
        if any(n in dom for n in NOISE_EMAIL):
            continue
        if m.lower() not in out:
            out.append(m.lower())
    return out[:3]


def clean_phones(html):
    out = []
    for m in PHONE_RE.findall(html):
        m = m.strip()
        if m and m not in out:
            out.append(m)
    return out[:3]


def enrich(page, url):
    info = {'emails': [], 'phones': [], 'contact_url': '', 'china_signal_text': ''}
    signal_parts = []
    tab = None
    try:
        tab = page.new_tab(url)
        tab.wait.doc_loaded(timeout=10)
        html = tab.html or ''
        signal_parts.append(html[:80000])
        info['emails'] = clean_emails(html)
        info['phones'] = clean_phones(html)
        if not info['emails']:
            p = urlparse(url)
            base = f'{p.scheme}://{p.netloc}/'
            for path in CONTACT_PATHS[:2]:
                try:
                    tab.get(urljoin(base, path.lstrip('/')))
                    tab.wait.doc_loaded(timeout=8)
                except Exception:
                    continue
                contact_html = tab.html or ''
                signal_parts.append(contact_html[:80000])
                e = clean_emails(contact_html)
                if e:
                    info['emails'] = e
                    info['phones'] = info['phones'] or clean_phones(contact_html)
                    info['contact_url'] = tab.url
                    break
    except Exception as ex:
        log(f'   访问失败: {url[:50]} {type(ex).__name__}')
    finally:
        if tab:
            try:
                tab.close()
            except Exception:
                pass
    info['china_signal_text'] = '\n'.join(signal_parts)
    return info


def _back_to_search(page, tab_id):
    """补全时会新开临时标签页去访问客户网站，抓完把活动标签切回搜索主标签，
    避免下一步 open_search 的导航落到客户网站上。
    即使切不回去也不致命（enrich 自己会关掉临时标签），所以吞掉异常。"""
    if not tab_id:
        return
    try:
        page.activate_tab(tab_id)
    except Exception:
        pass


def score_item(title, url, info, product_words=None):
    """给一条线索打分（满分 90）。

    ⚠️ `PRODUCT_WORDS` 是**写死的猫砂垫词表**（['litter','liner','cat','pet']），换行业后就
       名不副实 —— 塑料包装袋的客户永远吃不到那 +10，会从「重点客户」掉到「普通客户」。
       所以这里开一个可选入参：传了就按传进来的产品词算，不传仍是原来的行为（零回归）。
       自动链路暂时不传（保持既有评分口径不变）；手动采集会带上你自己的产品词。
    """
    s = 0
    text = (title + ' ' + url).lower()
    if info['emails']:
        s += 30
    if info['phones']:
        s += 15
    if info['contact_url']:
        s += 10
    if any(w in text for w in CTYPE_WORDS):
        s += 25
    words = [w for w in (product_words or PRODUCT_WORDS) if w]
    if any(w.lower() in text for w in words):
        s += 10
    if not any(w in text for w in BLOG_WORDS):
        s += 10
    return s


def rating(s):
    if s >= 70:
        return '重点客户'
    if s >= 50:
        return '普通客户'
    return '观察'


# ================= 谷歌地图名录采集（与网页搜索并列的第二条链路） =================
# 地图与网页搜索是两条独立链路：run_search 一行不动，这里自成一套。
# 三条与网页搜索不同的硬事实：
#   ① 电话/官网/完整地址只存在于「左侧详情面板」，列表卡片层拿不到 → 必须逐条点开；
#   ② 单次搜索硬上限约 120 条，滚到底会出「…the end of the list」→ 到末尾就收手，不硬凑；
#   ③ 定位靠「城市名进查询词 + @lat,lng 视野」，且结果受出口 IP 所在地影响。
MAPS_FEED_CSS = 'css:div[role="feed"]'
MAPS_CARD_CSS = 'css:div[role="feed"] a[href*="/maps/place/"]'
# 详情面板就绪判据：这三个 data-item-id 锚点因无障碍依赖而比混淆 class 稳得多
MAPS_DETAIL_READY = (
    'css:button[data-item-id="address"]',
    'css:button[data-item-id^="phone:tel:"]',
    'css:a[data-item-id="authority"]',
)
# 列表末尾提示（hl 会让文案本地化，所以多语言都要认）
MAPS_END_HINTS = ('reached the end of the list', 'fin de la liste', 'ende der liste',
                  'final de la lista', 'fine dell', 'einde van de lijst',
                  'listenin sonuna', 'نهاية القائمة')


def db_has_customer(website):
    """库里是否已有这个网站（只查不写）。用来在「点开详情 + 访问官网」之前就跳过老客户，
    省掉最贵的那两步 —— 比 run_search 里「先插一条再判断」的做法省事。"""
    key = normalize_domain(website)
    if not key:
        return False
    with closing(db_connect()) as conn:
        return conn.execute('SELECT 1 FROM customers WHERE website_key=? LIMIT 1',
                            (key,)).fetchone() is not None


# ================= 手动采集：公共落库尾段 + 行业自动判定 =================
_UNLOADED = object()          # 懒加载哨兵：区分「还没试过」与「试过但失败了(None)」
_BFHY = _UNLOADED             # 缓存「回填行业」模块


def _guess_industry(title, url):
    """用「回填行业.py」的规则从标题/网址猜行业（8 个规范值之一），猜不出返回空串。

    ⚠️ 刻意**不**把规则复制进 core/：行业口径只能有一份（原来就是因为「回填行业.py 用
      家具家居/汽配、词库用家具/机械零部件」而对不上）。这里复用同一个模块，口径天然一致。
       该模块除 `__main__` 外没有模块级副作用（只编译正则），导入安全。
    """
    global _BFHY
    if _BFHY is _UNLOADED:                 # 懒加载：首次用到才 import，避免影响启动
        try:
            import 回填行业 as _mod
        except Exception as ex:            # 缺文件/语法错都不该拖垮手动采集
            log(f'⚠️ 行业规则加载失败（将留空行业）：{type(ex).__name__}: {ex}')
            _mod = None
        _BFHY = _mod
    if _BFHY is None:
        return ''
    try:
        return _BFHY.guess_industry(title, url) or ''
    except Exception:
        return ''


def _commit_candidate(title, url, info, *, snippet, formula, country,
                      industry='', source='谷歌搜索', product_words=None):
    """手动采集的公共尾段：评分 → 写库 → 返回规范化行（供 10 列 Excel 用）。

    `product_words` 一路透传给 `score_item`（不传=沿用原有的写死词表，行为不变）。

    ⚠️ 刻意**没**让 run_search / run_maps 改用它：那两条链路已经跑通、且有回归脚本守着，
       项目既有约定是「不动跑通的链路」。run_maps 更特殊 —— 它在 china_filter_reasons()
       之前就把「地图电话并入官网电话」了，合并时机一旦挪动，中国过滤的入参就变了，
       smoke 可能仍绿而真机行为已改。待手动链路真机跑顺后再择机迁移。
    """
    s = score_item(title, url, info, product_words=product_words)
    db_upsert_customer({
        'company_name': title, 'website': url,
        'email': ' / '.join(info['emails']),
        'phone': ' / '.join(info['phones']),
        'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
        'snippet': snippet, 'search_formula': formula,
        'country': country, 'industry': industry, 'source': source,
    })
    return {'title': title, 'url': url, 'emails': info['emails'], 'phones': info['phones'],
            'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
            'snippet': snippet, 'formula': formula, 'country': country, 'industry': industry}


# ================= 手动采集：常驻浏览器 =================
# 自动链路（run_search / run_maps / enrich_core）都是「任务开头建、finally 里 quit」，
# 手动采集是「点一下采一条」，每次重建一个 Chrome 要 3–5 秒，所以这里做成**惰性常驻**。
# ⚠️ 与自动链路互不干扰：`create_browser_page()` 每次都给独立临时 profile + 独立调试端口，
#    是各自独立的 Chrome 实例，谁 quit 都影响不到对方。
_MANUAL_PAGE = None
_BROWSER_LOCK = threading.Lock()


def _manual_browser():
    """拿到常驻的采集浏览器（首次调用才创建）。"""
    global _MANUAL_PAGE
    with _BROWSER_LOCK:
        if _MANUAL_PAGE is not None:
            try:
                if _MANUAL_PAGE.states.is_alive:       # 用户手动关掉了浏览器的话要重建
                    return _MANUAL_PAGE
            except Exception:
                pass
            try:
                _MANUAL_PAGE.quit()
            except Exception:
                pass
            _MANUAL_PAGE = None
        log('启动采集浏览器（首次较慢，之后复用）...')
        _MANUAL_PAGE = create_browser_page()
        return _MANUAL_PAGE


def close_manual_browser():
    """关掉常驻采集浏览器（页面上有按钮，进程退出时也会自动调）。"""
    global _MANUAL_PAGE
    with _BROWSER_LOCK:
        if _MANUAL_PAGE is None:
            return False
        try:
            _MANUAL_PAGE.quit()
        except Exception:
            pass
        _MANUAL_PAGE = None
    log('采集浏览器已关闭')
    return True


# 进程退出兜底：常驻浏览器不像自动链路那样有 finally，不注册的话会留下一个孤儿 Chrome
atexit.register(close_manual_browser)


def _ensure_manual_session(industry='', country=''):
    """确保「本轮手动采集」已开始；还没开始就自动开一轮。

    为什么需要「自动开轮」：扩展是在任意网页上点一下采集的，用户不可能每次都先切回
    /manual 页点「开始本轮」。所以第一条进来时替他把轮开起来。
    本轮口径（行业/国家）**只在开轮那一刻记下**，后续条目不覆盖 —— 否则同一轮 Excel 的
    文件名会随最后一条变来变去（也避免中途改表单意外改名）。

    ⚠️ 锁纪律：本函数只在 STATE_LOCK 内改内存状态，不碰文件 IO。
    """
    with STATE_LOCK:
        if MANUAL_STATE.get('session_active'):
            return
        MANUAL_STATE.update({
            'session_active': True, 'session_started_at': time.time(),
            'session_rows': [], 'session_rid_seq': 0,
            'session_excel': '', 'session_error': '',
            'session_finish_pending': False,
            'added': 0, 'existed': 0, 'failed': 0, 'upgraded': 0,
            'session_industry': (industry or '').strip(),
            'session_country': (country or '').strip(),
        })
    log('====== 已开始本轮手动采集 ======')


def _next_rid():
    """发一个本轮内唯一、单调递增的行号，给 session_rows 的每一行当稳定主键。

    为什么明细行需要它：同一个 url 在同一轮里可能既有一条 'added' 又有一条 'existed'
    （第二轮采被去重跳过），按 url 删会一次删掉两条。rid 才能精确指认「哪一行」。
    ⚠️ 必须在 `with STATE_LOCK` 块内调用（本函数只改内存，不自带加锁）。"""
    MANUAL_STATE['session_rid_seq'] = MANUAL_STATE.get('session_rid_seq', 0) + 1
    return MANUAL_STATE['session_rid_seq']


def collect_from_html(url, title, html, industry='', country='',
                      source='手动采集', allow_upgrade=True, product_words=None):
    """手动采集一个网址：三级抓取 → 评分 → 入库 → 计入本轮明细。

    三级抓取（前一级拿不到邮箱才进下一级）：
      ① 秒级   ：扩展送来的当前页 HTML，直接正则抽邮箱/电话（不开浏览器，<0.1s）
      ② 联系页 ：用 requests 抓 /contact（约 1–2s）
      ③ 升级   ：开 Chromium 跑完整的 enrich()（3–10s，含 JS 渲染与反爬绕过）
    `product_words` 是本轮的产品词（用于评分里的 +10）；不传则沿用原有的写死词表。
    返回统一结果 dict，直接回给扩展 popup / 前端。

    ⚠️ 这里**不落盘**：采到的行只进 `MANUAL_STATE['session_rows']`，等用户点
       「🏁 结束并生成 Excel」时由 `_flush_manual_session()` 一次性写成结果 Excel
       （对齐自动搜索的「整轮结束才落盘」，也避免把手动采集的条目混进上一轮自动搜索的 Excel）。
    """
    init_customer_db()
    url = (url or '').strip()
    title = (title or '').strip()
    if not url.lower().startswith(('http://', 'https://')):
        url = 'https://' + url.lstrip('/') if url else ''
    key = normalize_domain(url)
    if not key:
        return {'ok': False, 'added': False, 'msg': f'网址无效：{url[:60]}'}

    # 网址有效就往本轮攒 —— 放在 db_has_customer 之前，保证「已在库跳过」的条目也计入本轮，
    # 也让本轮口径（行业/国家）从第一条就定下来（第③级升级可能要跑好几秒，不能等它）。
    _ensure_manual_session(industry, country)

    # 老客户直接跳过 —— 在「升级抓取」之前就省掉最贵的那一步（与 run_maps 的老客户策略一致）
    if db_has_customer(url):
        with STATE_LOCK:
            MANUAL_STATE['existed'] += 1
            # 也记一条轻量明细：用户要靠它回答「我刚点的那条去哪了」
            MANUAL_STATE.setdefault('session_rows', []).append(
                {'kind': 'existed', 'title': title or key, 'url': url, 'rid': _next_rid()})
        log(f'   · 已在客户库，跳过：{key}')
        return {'ok': True, 'added': False, 'existed': True, 'upgraded': False,
                'row': {'url': url, 'title': title or key}, 'msg': '已在客户库，跳过'}

    clean = _sanitize_page_html(html)
    tier = 0

    # ---- ① 秒级：优先用扩展送来的当前页 HTML（已渲染、最准）----
    if clean.strip():
        tier = 1
    elif requests is not None:
        # 没有 HTML：这是「/manual 页批量粘贴网址」的场景，先用 requests 抓一次首页
        # （不抓就会跳过首页直奔 /contact，把首页上写着的邮箱漏掉）
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': _UA},
                             allow_redirects=True)
            if r.status_code < 400 and r.text:
                clean = _sanitize_page_html(r.text)
                tier = 1
        except Exception:
            pass

    info = {'emails': clean_emails(clean), 'phones': clean_phones(clean),
            'contact_url': '', 'china_signal_text': clean[:80000]}
    upgraded = False

    # ---- ② 联系页：优先用页面里自己写的联系链接；没有才按 CONTACT_PATHS 猜 ----
    if not info['emails'] and requests is not None:
        own = _find_contact_url(clean, url)
        if own:
            candidates = [own]          # 找到自带链接就只用它，别再盲猜（省请求也更准）
        else:
            p = urlparse(url)
            base = f'{p.scheme}://{p.netloc}/'
            candidates = [urljoin(base, c.lstrip('/')) for c in CONTACT_PATHS[:2]]
        for cand in candidates:
            try:
                r = requests.get(cand, timeout=8, headers={'User-Agent': _UA},
                                 allow_redirects=True)
                if r.status_code >= 400 or not r.text:
                    continue
            except Exception:
                continue
            e = clean_emails(r.text)
            if e:
                # 与 enrich() 的语义保持一致：只有联系页真的抽到邮箱才认这个 contact_url
                info['emails'] = e
                info['phones'] = info['phones'] or clean_phones(r.text)
                info['contact_url'] = str(r.url)
                info['china_signal_text'] = (info['china_signal_text'] + '\n' + r.text[:80000])[:160000]
                tier = 2
                break

    # ---- ③ 升级：开 Chromium 跑完整 enrich() ----
    if not info['emails'] and allow_upgrade:
        with STATE_LOCK:
            busy = STATE['running']
        if busy:
            log('   · 自动任务运行中，本次不升级抓取（只登记已抓到的字段）')
        else:
            info = enrich(_manual_browser(), url)
            upgraded = True
            tier = 3

    if upgraded:
        with STATE_LOCK:
            MANUAL_STATE['upgraded'] += 1

    industry = (industry or '').strip() or _guess_industry(title, url)
    snippet = _meta_description(html) or title or url
    row = _commit_candidate(title or key, url, info, snippet=snippet,
                            formula=f'[手动采集] {url}', country=country,
                            industry=industry, source=source,
                            product_words=product_words)

    with STATE_LOCK:
        MANUAL_STATE['added'] += 1
        # kind='added' 只加进本轮明细，**不加进返回给扩展的 row**（/api/collect 响应结构不变）
        # dict(row, ...) 是副本，所以加的 kind / rid 不会污染下面 return 的那个 row
        MANUAL_STATE.setdefault('session_rows', []).append(
            dict(row, kind='added', rid=_next_rid()))
    log(f'   + 手动采集 [{tier}级] {row["title"][:38]} '
        f'邮箱{len(row["emails"])} 电话{len(row["phones"])} 评分{row["score"]} {row["rating"]}'
        + (f' 行业={industry}' if industry else ''))

    return {'ok': True, 'added': True, 'existed': False, 'upgraded': upgraded,
            'tier': tier, 'row': row}


def _maps_attr(page, css, attr=None, timeout=1):
    """读一个元素的属性/文本/绝对链接；找不到或读失败都返回空串。
    地图 DOM 会小幅改版，这里全程容错，宁可字段留空也不要整轮崩掉。"""
    try:
        el = page.ele(css, timeout=timeout)
    except Exception:
        el = None
    if not el:
        return ''
    try:
        if attr == 'link':
            return (el.link or '').strip()
        if attr:
            return (el.attr(attr) or '').strip()
        return (el.text or '').strip()
    except Exception:
        return ''


def maps_consent_wall(page):
    """谷歌地图首访可能弹 Cookie 同意墙，挡住列表与详情面板。"""
    try:
        if 'consent.google' in (page.url or '').lower():
            return True
        return bool(page.ele('css:form[action*="consent"]', timeout=0.5))
    except Exception:
        return False


def maps_open(page, url, attempts=2):
    """打开地图搜索页并等结果列表出现。返回 True 表示有列表。
    注意地图**没有**网页搜索那种「零结果页」，判据就是 feed 在不在。"""
    for i in range(attempts):
        if STATE['stop']:
            return False
        try:
            page.get(url)
            page.wait.doc_loaded(timeout=15)
        except Exception as e:
            log(f'⚠️ 地图页打开失败（第 {i + 1} 次）：{type(e).__name__}')
            continue
        if maps_consent_wall(page):
            log('⚠️ 谷歌地图弹出 Cookie 同意墙：请在浏览器窗口点「全部接受」，脚本最多等 60 秒')
            for _ in range(30):
                if STATE['stop']:
                    return False
                time.sleep(2)
                if not maps_consent_wall(page):
                    break
        if not wait_captcha(page):
            return False
        if page.ele(MAPS_FEED_CSS, timeout=12):
            return True
        log(f'↻ 地图结果列表没渲染出来（第 {i + 1} 次），重新打开…')
        if not sleep_check(2):
            return False
    return False


def maps_cards(page):
    """当前 feed 里的商家卡片链接（列表层只有名称/评分/类目，拿不到电话官网）。"""
    try:
        return page.eles(MAPS_CARD_CSS, timeout=5) or []
    except Exception:
        return []


def maps_reached_end(feed):
    """feed 里出现「已到列表末尾」提示就该停止滚动。"""
    if feed is None:
        return False
    try:
        text = (feed.text or '').lower()
    except Exception:
        return False
    return any(h in text for h in MAPS_END_HINTS)


def maps_feed_scroll(page, want, max_rounds=16):
    """滚动结果面板加载更多商家，返回卡片列表。
    ⚠️ 必须滚 feed 元素本身 —— 滚 window 在地图上完全无效（实测）。
    退出条件三条：够 want 条 / 连续两轮不增长 / 命中列表末尾提示。"""
    cards = maps_cards(page)
    if not cards:
        return []
    try:
        feed = page.ele(MAPS_FEED_CSS, timeout=5)
    except Exception:
        feed = None
    stalled = 0
    for _ in range(max_rounds):
        if STATE['stop'] or len(cards) >= want:
            break
        try:
            if feed:
                feed.scroll.to_bottom()
            else:
                page.scroll.down(2000)
        except Exception:
            try:
                page.run_js('const f=document.querySelector(\'div[role="feed"]\');'
                            'if(f){f.scrollTop=f.scrollHeight;}')
            except Exception:
                pass
        if not sleep_check(random.uniform(1.5, 2.5)):
            break
        new_cards = maps_cards(page)
        if len(new_cards) > len(cards):
            cards = new_cards
            stalled = 0
            try:
                feed = page.ele(MAPS_FEED_CSS, timeout=3)
            except Exception:
                pass
        else:
            stalled += 1
        if stalled >= 2 or maps_reached_end(feed):
            break
    return cards


def maps_collect_hrefs(page, want, max_rounds=16):
    """滚列表 → 把商家链接取成字符串列表。
    刻意转成字符串再返回：元素句柄在页面导航后会失效，字符串不会。"""
    cards = maps_feed_scroll(page, want, max_rounds)
    hrefs, seen_h = [], set()
    for c in cards:
        try:
            h = (c.link or c.attr('href') or '').strip()
        except Exception:
            continue
        if h and h not in seen_h:
            seen_h.add(h)
            hrefs.append(h)
    return hrefs


def maps_detail(page, place_url):
    """导航到某个商家的 place 页面并读左侧详情面板。读不到返回 None。

    ⚠️ 不要改成「逐个点列表卡片」：真机实测点开第一条后，搜索结果列表就被详情页替换掉，
    剩下的卡片元素立刻全部失效（NoRectError）。所以直接导航到卡片 href 指向的 place URL ——
    每条多一次页面加载（约 2~3 秒），但彻底摆脱 SPA 元素失效问题。
    面板里各字段都可能合法缺失（有的商家就是没电话、没官网），缺了就留空，不算失败。
    """
    try:
        page.get(place_url)
        page.wait.doc_loaded(timeout=15)
    except Exception as e:
        log(f'     · 打开商家页失败：{type(e).__name__}')
        return None
    ready = False
    for _ in range(10):
        if STATE['stop']:
            return None
        for css in MAPS_DETAIL_READY:
            try:
                if page.ele(css, timeout=0.8):
                    ready = True
                    break
            except Exception:
                continue
        if ready:
            break
        time.sleep(0.3)
    if not ready:
        return None
    # 电话：data-item-id 形如 phone:tel:+3347889xxxx —— 与界面语言无关，最稳
    phone = ''
    try:
        el = page.ele('css:button[data-item-id^="phone:tel:"]', timeout=1)
        if el:
            phone = (el.attr('data-item-id') or '').split('phone:tel:', 1)[-1].strip()
            if not phone:
                phone = (el.attr('aria-label') or '').split(':', 1)[-1].strip()
    except Exception:
        phone = ''
    website = _maps_attr(page, 'css:a[data-item-id="authority"]', attr='link', timeout=1)
    address = ''
    try:
        el = page.ele('css:button[data-item-id="address"]', timeout=1)
        if el:
            address = (el.attr('aria-label') or '').split(':', 1)[-1].strip() \
                or (el.text or '').strip()
    except Exception:
        address = ''
    category = _maps_attr(page, 'css:button[jsaction*="category"]', timeout=0.6) \
        or _maps_attr(page, 'css:button.DkEaL', timeout=0.6)
    return {
        'name': _maps_attr(page, 'css:h1', timeout=1),
        'phone': phone,
        'website': website,
        'address': address,
        'category': category,
        'place_url': (page.url or place_url),
    }


# ================= 后台任务 =================
def run_search(products, cond_keys, countries, pages, exclude, match='or', target_count=10, industry='',
               auto_enrich=True, lang='', china_filters=None, raw_queries=None,
               country_limit=COUNTRY_LIMIT_DEFAULT):
    """搜索 + 补全一体化闭环：每搜到一个新网站，立刻访问它抓邮箱/电话并评分、回写客户库，
    然后再去搜下一个；凑够 target_count 个新增网站就停。
    lang = 条件词的搜索语言（如 fr），留空则按所搜国家的 hl 自动取，取不到用 en。
    auto_enrich=False 时退化为「只收集网站线索」（邮箱电话留空、评分按无联系方式算），便于快速铺量。
    目标数量按「本轮新增网站数」计算。整轮结束（含中途停止）写出唯一一份结果 Excel。

    raw_queries 非空 = **自定义模式**（用户 2026-10-02 拍板）：每条原样当一条查询发给谷歌 ——
    不套条件模板、不自动加引号、不拼产品词、不拼排除词；并且**强制关掉中国商家过滤**
    （china_filters 置空）。与产品词/条件/match 互斥，那些参数在自定义模式下全部忽略。
    目标国家照旧只走 URL 的 gl/hl 并写进结果行的 country，**不写进搜索词**。
    ⚠️ 注意：「中国商家过滤」与 is_blocked() 的平台黑名单是两层 —— 自定义模式只关前者，
    亚马逊/维基/领英这类黑名单域名照样会被挡（那是另一个开关，本次不做）。

    country_limit = **国家限定**（可选，默认 'none' 什么都不加）：'cr' 只加 &cr=countryXX（挂 URL，
    按主机托管国硬过滤）、'site' 只加 site:.xx（拼进搜索词）、'both' 都加。**只对标准网页模式生效** ——
    自定义模式与地图模式一律不加。⚠️ 2026-09-28 实测：法国加 cr 后条数 10→7、真客户反被挤掉，
    所以默认关；具体值见 core/config.py 的 COUNTRY_LIMITS。"""
    page = None
    raw_queries = [str(q).strip() for q in (raw_queries or []) if str(q).strip()]
    custom_mode = bool(raw_queries)
    if country_limit not in COUNTRY_LIMIT_MODES:
        country_limit = COUNTRY_LIMIT_DEFAULT     # 非法值静默回落「不改」，与其它参数一致
    if custom_mode:
        china_filters = set()          # 用户拍板：自定义模式下完全不做中国商家过滤
        country_limit = 'none'         # 同一纪律：自定义模式也不叠加国家限定
    else:
        china_filters = set(CHINA_FILTER_DEFAULTS if china_filters is None else china_filters)
    search_tab_id = None      # 搜索主标签 id：补全会开临时标签，抓完要切回来
    all_rows = []             # 本轮结果（已就地补全），在 finally 里落盘
    search_ok = True
    try:
        init_customer_db()
        STATE['phase'] = 'search'
        if custom_mode:
            log(f'启动浏览器... 自定义查询 {len(raw_queries)} 条 × 国家 {len(countries)} 个（原样搜索，不拼任何词）')
        else:
            log(f'启动浏览器... 产品 {len(products)} 个 × 条件 {len(cond_keys)} 个 × 国家 {len(countries)} 个')
        page = create_browser_page()
        try:
            search_tab_id = page.tab_id    # 记下搜索主标签，补全用临时标签时才好切回来
        except Exception:
            search_tab_id = None
        # 不再先开首页预热：实测「先开首页再搜」更容易触发谷歌的地区识别中间态
        # （Updating location…），导致结果页只渲染出搜索框。每个搜索 URL 自带 gl/hl，预热没必要。

        # 条件数只用于估算总查询数；真正的公式模板按国家语言在下面逐个组装
        if custom_mode:
            # 自定义模式：每条自定义词本身就是一条完整查询，不套模板、不加引号、不拼产品词
            pq_list = list(raw_queries)
            cond_count = 1
            total = len(pq_list) * len(countries)
        else:
            cond_count = sum(1 for k, _ in CONDITIONS if k in cond_keys)
            pwords = ['"' + p.strip().strip('"') + '"' for p in products]
            if match == 'and':
                pq_list = [' '.join(pwords)]
            elif match == 'each':
                pq_list = pwords
            else:
                # 把产品词 OR 组整体括起来，避免 Google 把角色词只应用到最后一个产品词。
                pq = ' OR '.join(pwords)
                pq_list = ['(' + pq + ')' if len(pwords) > 1 else pq]
            total = len(pq_list) * cond_count * len(countries)
        q_index = 0
        seen = set()
        seen_titles = set()
        reached_target = False
        # 整轮汇总统计：让「到底有没有写进客户库」一眼可见
        total_stat = {'cand': 0, 'blocked': 0, 'dup': 0, 'existing': 0, 'added': 0,
                      'mail': 0, 'empty': 0, 'china': Counter()}

        for code, cname, gl, hl in countries:
            # 国家限定（可选）：cr 挂 URL（与 gl/hl 并列）、site: 拼搜索词。
            # 仅标准模式 —— 自定义模式已在上方整体置 none；地图模式根本不走这个函数。
            cr_val, site_val = COUNTRY_LIMITS.get(code, ('', ''))
            cr_param  = f'&cr={cr_val}' if (country_limit in ('cr', 'both') and cr_val) else ''
            site_term = site_val        if (country_limit in ('site', 'both') and site_val) else ''
            country_params = f'&gl={gl}&hl={hl}{cr_param}'
            # 条件词按「搜索语言」本地化：法国站用 grossiste/importateur 这类本地词，
            # 否则就是在法语页面里找英文词，命中的多是非目标站。语言优先级：前端传入 → 该国 hl → en。
            lang = (lang or '').strip() or hl or 'en'
            if custom_mode:
                # 占位模板：{p} 原样替换 → 让下面「产品 × 条件」的双层循环照跑，不必另写一套循环
                cond_list = [('自定义', '{p}')]
                log(f'========== 国家：{cname}（gl={gl} hl={hl} · 自定义查询原样搜索） ==========')
            else:
                cond_list = [(name, cond_template(k, lang)) for k, name in CONDITIONS if k in cond_keys]
                log(f'========== 国家：{cname}（gl={gl} hl={hl} · 条件词语言 {lang}） ==========')
            for pq in pq_list:
                for cname2, tmpl in cond_list:
                    if STATE['stop']:
                        log('已停止')
                        return
                    q_index += 1
                    if custom_mode:
                        # 原样：不加引号、不拼排除词、不拼中国过滤词（用户拍板「搜索词一个字符都不加」）
                        formula = pq
                    else:
                        china_exclude = china_filter_terms(china_filters)
                        core = tmpl.replace('{p}', pq)
                        if site_term:
                            # site: 位置 = 条件模板之后、排除词之前（前端预览必须同位置，否则对不上）
                            core = f'{core} {site_term}'
                        formula = f'{core} {exclude} {china_exclude}'.strip()
                    log(f'[{q_index}/{total}] 搜索({cname}·{cname2})：{pq}')
                    # 打开并确认结果已渲染（内置多次重开，专治谷歌的「壳页面」）
                    open_search(page, formula, country_params)
                    if search_tab_id is None:
                        try:
                            search_tab_id = page.tab_id   # 首次导航后标签一定就绪，补取一次兜底
                        except Exception:
                            pass
                    if not wait_captcha(page):
                        continue
                    stat = {'cand': 0, 'blocked': 0, 'dup': 0, 'existing': 0, 'added': 0,
                            'mail': 0, 'china': Counter()}
                    for pg in range(pages):
                        if pg > 0:
                            if not open_search(page, formula, country_params, pg * 10):
                                break
                            if not wait_captcha(page):
                                break
                        items, blocked_n, china_reasons = extract_results(page, seen_titles, china_filters)
                        stat['cand'] += len(items) + blocked_n
                        stat['blocked'] += blocked_n
                        stat['china'].update(china_reasons)
                        for item in items:
                            key = url_key(item['url'])
                            if key in seen:
                                stat['dup'] += 1
                                continue
                            seen.add(key)
                            item['formula'] = formula
                            item['country'] = cname
                            # ① 就地补全这一个网站；联系方式信号过滤必须发生在入库之前。
                            info = {'emails': [], 'phones': [], 'contact_url': ''}
                            if auto_enrich and not STATE['stop']:
                                info = enrich(page, item['url'])
                                _back_to_search(page, search_tab_id)
                            contact_reasons = china_filter_reasons(
                                item['title'], item['url'], item['snippet'],
                                emails=info.get('emails'), phones=info.get('phones'),
                                html_text=info.get('china_signal_text', ''),
                                enabled_keys=china_filters)
                            if contact_reasons:
                                stat['blocked'] += 1
                                stat['china'].update(contact_reasons)
                                log(f'   过滤：{item["title"][:40]}（{"；".join(contact_reasons)}）')
                                continue
                            # ② 登记线索：已在客户库中的公司不再作为新线索重复展示。
                            existed = not db_upsert_customer({
                                'company_name': item['title'], 'website': item['url'],
                                'snippet': item['snippet'], 'search_formula': formula,
                                'country': cname, 'industry': industry,
                            })
                            if existed:
                                stat['existing'] += 1
                                log(f'   ↩ 已存在，跳过重复客户：{item["title"][:45]}')
                                continue
                            # ③ 用补全结果更新刚才的线索记录。
                            s = score_item(item['title'], item['url'], info)
                            if auto_enrich:
                                # 用补全结果覆盖刚才的线索记录（空值不会冲掉库里已有的有效值）
                                db_upsert_customer({
                                    'company_name': item['title'], 'website': item['url'],
                                    'email': ' / '.join(info['emails']),
                                    'phone': ' / '.join(info['phones']),
                                    'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                                    'snippet': item['snippet'], 'search_formula': formula,
                                    'country': cname, 'industry': industry,
                                })
                            all_rows.append({**item, **info, 'score': s, 'rating': rating(s),
                                             'industry': industry})
                            stat['added'] += 1
                            if info['emails']:
                                stat['mail'] += 1
                            STATE['result_count'] = len(all_rows)
                            # 实时明细：前端表格每秒轮询 STATE['rows']，边搜边显示入库内容
                            with STATE_LOCK:
                                STATE['rows'].append({
                                    'n': len(all_rows),
                                    'title': item['title'],
                                    'url': item['url'],
                                    'emails': info['emails'],
                                    'phones': info['phones'],
                                    'contact_url': info['contact_url'],
                                    'score': s,
                                    'rating': rating(s),
                                    'industry': industry,
                                    'country': cname,
                                })
                            log(f'   + [{len(all_rows)}/{target_count}] {item["title"][:38]} '
                                f'邮箱{len(info["emails"])} 电话{len(info["phones"])} 评分{s} {rating(s)}')
                            if len(all_rows) >= target_count:
                                reached_target = True
                                log(f'🎯 已达到本次目标 {target_count} 个新增网站，停止继续搜索')
                                break
                        if reached_target:
                            break
                        if not sleep_check(random.uniform(2, 4)):
                            log('已停止')
                            return
                    # 一个查询跑完（含翻页），打印它的账目
                    for k in stat:
                        total_stat[k] += stat[k]
                    if stat['cand'] == 0:
                        total_stat['empty'] += 1
                    for reason, count in stat['china'].items():
                        total_stat['china'][reason] += count
                    reason_text = '；'.join(f'{k} {v}' for k, v in stat['china'].items()) or '无'
                    log(f'📊 [{q_index}/{total}] {cname}·{cname2} → 页面候选 {stat["cand"]} 条 | '
                        f'黑名单过滤 {stat["blocked"]} | 本页重复 {stat["dup"]} | '
                        f'客户库已有 {stat["existing"]} | 新增 {stat["added"]}（其中 {stat["mail"]} 个抓到邮箱） | '
                        f'中国商家过滤：{reason_text}')
                    if reached_target:
                        break
                    if not sleep_check(random.uniform(4, 8)):
                        log('已停止')
                        return
                if reached_target:
                    break
            if reached_target:
                break

        log(f'✅ 搜索完成！本轮新增 {len(all_rows)} 个网站'
            + ('，联系方式已就地抓取并写入客户库' if auto_enrich else '（本次未抓取联系方式）'))
        china_total = '；'.join(f'{k} {v}' for k, v in total_stat['china'].items()) or '无'
        log(f'📈 本轮总账：页面候选 {total_stat["cand"]} 条 | 黑名单过滤 {total_stat["blocked"]} | '
            f'本页重复 {total_stat["dup"]} | 客户库已有 {total_stat["existing"]} | '
            f'新增 {total_stat["added"]}（带邮箱 {total_stat["mail"]}） | 中国商家过滤：{china_total}')
        if not reached_target:
            if total_stat['cand'] == 0:
                log('⚠️ 一条候选都没抓到：多半是搜索结果页没渲染出来（或被谷歌拦截），建议先手动在浏览器里搜一次确认')
            else:
                log(f'⚠️ 未能凑够目标 {target_count} 条新增：候选里大多是库里已有的客户。'
                    f'说明该关键词已被搜尽，建议换关键词、加页数或换国家')
        if not auto_enrich:
            log('（本次未勾选同步抓取联系方式：只收集了网站线索，邮箱电话留空，'
                '可稍后双击「补历史欠账.py」批量补）')
        log('正在写出结果 Excel…')
    except Exception as e:
        search_ok = False
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 落盘放在 finally：中途「停止」在 try 内部是 return，只有这里能保证已抓到的结果不白跑。
        # 浏览器关掉后再写文件，确保客户网站标签页已释放、不会和 Excel 抢资源。
        if all_rows:
            try:
                _save_enrich_excel(all_rows, industry=industry)
            except Exception as e:
                log(f'❌ 结果 Excel 写出失败：{type(e).__name__}: {e}')
        elif search_ok:
            log('本轮没有新增网站，未产出结果文件（客户库未变化）')
        STATE['done'] = True
        STATE['running'] = False


def maps_role_word(cond_keys, lang='en'):
    """地图模式下把「身份词」拼进查询词。

    ⚠️ 这一步不是可选优化，是必需：真机实测搜「nouilles」+ 里昂返回的全是
    「Restaurant chinois」餐馆；加上 grossiste 后才出现「Grossiste alimentaire」
    （食品批发商）和进口杂货商 —— 那才是买家。
    取第一个勾选条件的第一个角色词（如 fr → grossiste）。
    """
    for k in (cond_keys or []):
        roles = COND_ROLES.get(k) or {}
        word = roles.get(lang) or roles.get('en') or ''
        if word:
            return word.split(' OR ')[0].strip().strip('"')
    return ''


def run_maps(products, cond_keys, countries, city='', target_count=10, industry='', auto_enrich=True,
             lang='', china_filters=None):
    """谷歌地图名录采集 + 就地补全：与 run_search 并列的第二条链路，互不干扰。

    地图的独特价值：名录里只有「有实体地址的真实商家」，所以 B2B 名录站、新闻站、
    菜谱站这类非买家根本不会出现；而且电话/地址是结构化字段，不用再从官网里猜。
    代价：单次搜索上限约 120 条，且电话/官网必须逐条点开详情面板才有。
    auto_enrich=False 时只取地图给的字段（电话/地址），不访问官网补邮箱。
    """
    page = None
    maps_tab_id = None
    all_rows = []
    run_ok = True
    china_filters = set(CHINA_FILTER_DEFAULTS if china_filters is None else china_filters)
    try:
        init_customer_db()
        STATE['phase'] = 'search'
        log(f'谷歌地图采集：关键词 {len(products)} 个 × 国家 {len(countries)} 个'
            + (f' · 城市「{city}」' if city else '（未指定城市，只用国家中心视野）'))
        log('⚠️ 地图结果会受出口 IP 所在地影响，比网页搜索更明显；指定城市可显著提高精度')
        page = create_browser_page()
        try:
            maps_tab_id = page.tab_id
        except Exception:
            maps_tab_id = None

        seen = set()
        seen_names = set()
        reached_target = False
        # 整轮汇总统计：让「到底有没有写进客户库」一眼可见
        total_stat = {'cards': 0, 'detail': 0, 'end': 0, 'dup': 0, 'existing': 0,
                      'added': 0, 'mail': 0, 'no_web': 0, 'china': Counter()}

        for code, cname, gl, hl in countries:
            if reached_target or STATE['stop']:
                break
            lang = (lang or '').strip() or hl or 'en'
            role = maps_role_word(cond_keys, lang)
            if role:
                log(f'   （地图查询拼上身份词「{role}」—— 不带身份词只会返回餐馆/零售店）')
            for kw in products:
                if reached_target or STATE['stop']:
                    break
                want = target_count - len(all_rows)
                query = f'{kw} {role}'.strip()
                url = maps_search_url(query, code, gl, hl, city)
                log(f'========== {cname} · 地图搜「{query}」'
                    + (f' + {city}' if city else '') + f'（hl={hl} gl={gl}） ==========')
                log(f'   {url}')
                stat = {'cards': 0, 'detail': 0, 'end': 0, 'dup': 0,
                        'existing': 0, 'added': 0, 'mail': 0, 'no_web': 0, 'china': Counter()}
                if not maps_open(page, url):
                    log('⚠️ 地图页没打开或没结果列表，跳过这个关键词')
                    continue
                try:
                    maps_tab_id = page.tab_id or maps_tab_id
                except Exception:
                    pass
                # 链接一次收够：按目标数 3 倍收（去重/过滤会消耗掉一部分），
                # 上限 120 是谷歌地图单次搜索的硬上限，滚到底就停。
                collect = min(max(want * 3, want + 5), 120)
                hrefs = maps_collect_hrefs(page, collect)
                stat['cards'] = len(hrefs)
                if len(hrefs) < collect:
                    stat['end'] = 1                    # 没滚满 = 已经到列表末尾
                log(f'   列表滚出 {len(hrefs)} 条商家链接'
                    + ('（已到列表末尾）' if stat['end'] else f'（目标还需 {want} 条）'))
                if not hrefs:
                    log('   这个关键词在当前城市没滚出任何商家，换城市或换个词')
                for href in hrefs:
                    if reached_target or STATE['stop']:
                        break
                    key = maps_place_key(href) or url_key(href)
                    if not key or key in seen:
                        stat['dup'] += 1
                        continue
                    seen.add(key)
                    # ① 导航到商家页读详情面板（列表层拿不到电话/官网/地址）
                    det = maps_detail(page, href)
                    if not det:
                        log('     · 商家页没读通，跳过这条')
                        continue
                    stat['detail'] += 1
                    name = det['name'] or '(地图未给名称)'
                    if name and name in seen_names:
                        stat['dup'] += 1
                        continue
                    seen_names.add(name)
                    place_url = det['place_url'] if '/maps/place/' in det['place_url'] else href
                    website = det['website']
                    # 没有官网时用 place 链接占位，靠 normalize_domain 的 maps 分支保持唯一
                    target_url = website or place_url
                    phones = [det['phone']] if det['phone'] else []
                    snippet = ' · '.join(x for x in (det['category'], det['address']) if x) or name
                    formula = f'[谷歌地图] {query}' + (f' @{city}' if city else '')
                    if not website:
                        stat['no_web'] += 1
                    # ② 中国商家过滤（地图没有查询公式，只能走结果/联系方式阶段判据）
                    pre_reasons = china_filter_reasons(
                        name, target_url, snippet, phones=phones, enabled_keys=china_filters)
                    if pre_reasons:
                        stat['china'].update(pre_reasons)
                        log(f'   过滤：{name[:40]}（{"；".join(pre_reasons)}）')
                        continue
                    # ③ 已经在库里的老客户，跳过最贵的那两步（点详情已经花掉，这里省访问官网）
                    if db_has_customer(target_url):
                        stat['existing'] += 1
                        log(f'   ↩ 已存在，跳过重复客户：{name[:45]}')
                        continue
                    # ④ 就地补全：地图已经给了电话，官网只补邮箱
                    info = {'emails': [], 'phones': [], 'contact_url': '', 'china_signal_text': ''}
                    if auto_enrich and website and not STATE['stop']:
                        info = enrich(page, website)
                        _back_to_search(page, maps_tab_id)
                    for p in info['phones']:
                        if p not in phones:
                            phones.append(p)
                    info['phones'] = phones[:3]
                    post_reasons = china_filter_reasons(
                        name, target_url, snippet, emails=info['emails'], phones=info['phones'],
                        html_text=info.get('china_signal_text', ''), enabled_keys=china_filters)
                    if post_reasons:
                        stat['china'].update(post_reasons)
                        log(f'   过滤：{name[:40]}（{"；".join(post_reasons)}）')
                        continue
                    # ⑤ 一次性入库（地图字段 + 官网补到的邮箱），地图来源单独标记
                    s = score_item(name, target_url, info)
                    db_upsert_customer({
                        'company_name': name, 'website': target_url,
                        'email': ' / '.join(info['emails']),
                        'phone': ' / '.join(info['phones']),
                        'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                        'snippet': snippet, 'search_formula': formula,
                        'country': cname, 'industry': industry, 'source': '谷歌地图',
                    })
                    all_rows.append({
                        'title': name, 'url': target_url, 'emails': info['emails'],
                        'phones': info['phones'], 'contact_url': info['contact_url'],
                        'score': s, 'rating': rating(s), 'snippet': snippet,
                        'formula': formula, 'country': cname, 'industry': industry,
                    })
                    stat['added'] += 1
                    if info['emails']:
                        stat['mail'] += 1
                    STATE['result_count'] = len(all_rows)
                    # 实时明细：前端表格每秒轮询 STATE['rows']，边采边显示入库内容
                    with STATE_LOCK:
                        STATE['rows'].append({
                            'n': len(all_rows), 'title': name, 'url': target_url,
                            'emails': info['emails'], 'phones': info['phones'],
                            'contact_url': info['contact_url'], 'score': s,
                            'rating': rating(s), 'industry': industry, 'country': cname,
                        })
                    log(f'   + [{len(all_rows)}/{target_count}] {name[:38]} '
                        f'邮箱{len(info["emails"])} 电话{len(info["phones"])} 评分{s} {rating(s)}')
                    if len(all_rows) >= target_count:
                        reached_target = True
                        log(f'🎯 已达到本次目标 {target_count} 个新增商家，停止继续采集')
                        break
                    if not sleep_check(random.uniform(1.5, 3)):
                        log('已停止')
                        return

                # 一个关键词跑完，打印它的账目
                for k in stat:
                    if k == 'china':
                        for reason, count in stat['china'].items():
                            total_stat['china'][reason] += count
                    else:
                        total_stat[k] += stat[k]
                reason_text = '；'.join(f'{k} {v}' for k, v in stat['china'].items()) or '无'
                log(f'📊 {cname}·地图 {query} → 列表卡片 {stat["cards"]} 条 | '
                    f'详情读通 {stat["detail"]} 条 | 重复 {stat["dup"]} | '
                    f'客户库已有 {stat["existing"]} | 新增 {stat["added"]}'
                    f'（其中 {stat["mail"]} 个抓到邮箱） | 中国商家过滤：{reason_text}')
                if reached_target:
                    break
                if not sleep_check(random.uniform(3, 6)):
                    log('已停止')
                    return
            if reached_target:
                break

        log(f'✅ 地图采集完成！本轮新增 {len(all_rows)} 个商家'
            + ('，联系方式已就地抓取并写入客户库' if auto_enrich else '（本次未抓取联系方式）'))
        china_total = '；'.join(f'{k} {v}' for k, v in total_stat['china'].items()) or '无'
        log(f'📈 本轮总账：列表卡片 {total_stat["cards"]} 条 | 详情读通 {total_stat["detail"]} 条 | '
            f'已滚到底 {total_stat["end"]} 次 | 重复 {total_stat["dup"]} | '
            f'客户库已有 {total_stat["existing"]} | 新增 {total_stat["added"]}'
            f'（带邮箱 {total_stat["mail"]}） | 中国商家过滤：{china_total}')
        if total_stat['no_web']:
            log(f'   （其中 {total_stat["no_web"]} 条商家没登记官网，只拿到电话/地址，'
                f'所以没有邮箱；可后续用电话直接联系）')
        if not reached_target:
            log(f'⚠️ 未凑够目标 {target_count} 条：地图单次搜索的上限约 120 条，'
                f'多数关键词滚到底也就几十条。建议换城市、换关键词，或把目标数调小')
        log('正在写出结果 Excel…')
    except Exception as e:
        run_ok = False
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 落盘放 finally：中途「停止」在 try 内部是 return，只有这里能保证已采到的结果不白跑。
        if all_rows:
            try:
                _save_enrich_excel(all_rows, industry=industry)
            except Exception as e:
                log(f'❌ 结果 Excel 写出失败：{type(e).__name__}: {e}')
        elif run_ok:
            log('本轮没有新增商家，未产出结果文件（客户库未变化）')
        STATE['done'] = True
        STATE['running'] = False


def _enrich_worklist():
    """待补全清单：客户库里「邮箱和电话都为空」的记录。
    搜索现在会就地抓联系方式，所以这里捞出来的基本是历史欠账
    （老版本搜到、但没抓到邮箱电话的记录，或抓空后未再补的站）。
    已有邮箱或电话的不会被选出（跳过重复访问）；平台类黑名单域名也跳过。"""
    init_customer_db()
    with closing(db_connect()) as conn:
        rows = conn.execute('''
            SELECT company_name, website, country, industry, snippet, search_formula
            FROM customers
            WHERE website IS NOT NULL AND website <> ''
              AND COALESCE(email, '') = '' AND COALESCE(phone, '') = ''
            ORDER BY datetime(last_seen_at) DESC
        ''').fetchall()
    items, seen, blocked = [], set(), 0
    for r in rows:
        url = (r['website'] or '').strip()
        if not url.startswith('http'):
            url = 'https://' + url
        key = normalize_domain(url)
        if not key or key in seen:
            continue
        seen.add(key)
        if is_blocked(url):
            blocked += 1
            continue
        items.append({
            'title': r['company_name'] or url, 'url': url,
            'snippet': r['snippet'] or '', 'formula': r['search_formula'] or '',
            'country': r['country'] or '', 'industry': r['industry'] or '',
        })
    if blocked:
        log(f'（已跳过 {blocked} 个平台类/黑名单域名）')
    return items


def _pick_industry(explicit, results):
    """行业：优先用本轮搜索时选的；补全单独跑（没有搜索上下文）时取结果里出现最多的。"""
    if (explicit or '').strip():
        return explicit.strip()
    counter = Counter((r.get('industry') or '').strip()
                      for r in results if (r.get('industry') or '').strip())
    return counter.most_common(1)[0][0] if counter else ''


def _pick_country(results):
    """主国家：结果里条数最多的那个（多国同跑时以它命名，历史欠账混入也能收拢）。"""
    counter = Counter((r.get('country') or '').strip()
                      for r in results if (r.get('country') or '').strip())
    return counter.most_common(1)[0][0] if counter else ''


EXCEL_HEADER_10 = ['公司/页面标题', '网站网址', '邮箱', '电话', '联系页',
                   '评分', '评级', '摘要', '搜索公式', '国家']
EXCEL_WIDTHS_10 = (50, 50, 40, 20, 40, 8, 10, 60, 50, 10)
EXCEL_LOCK = threading.Lock()      # 手动采集可能并发点，追加写必须串行


def _row10(row):
    """把内部行（11 键）映射成结果 Excel 的 10 列 —— 顺序必须与 _save_enrich_excel 一致。"""
    return [row['title'], row['url'], ' / '.join(row['emails']), ' / '.join(row['phones']),
            row['contact_url'], row['score'], row['rating'], row['snippet'],
            row['formula'], row.get('country', '')]


def _append_result_row(row):
    """把一条手动采集的结果**追加**到当前结果 Excel，并按评分重排整表。

    ⚠️ 已被「本轮会话」模式取代（本轮结束才落盘，见 `_flush_manual_session`，2026-09-29），
       **当前无调用方**。保留而不删：它是经过回归验证的实现，删除只会扩大 diff；
       将来若又要「点一下即时落盘」可以再挂回去。

    ⚠️ 为什么当初不用现成的 `_save_enrich_excel`：那个函数每次 `Workbook()` 新开一个文件、
       按 `ts_result_path()` 重新命名，还会把 `paths.ENRICH_FILE` 改指过去 ——
       手动采集是「点一下加一条」，用它就会每点一次产出一个只含 1 行的 xlsx，
       并把「最新结果」污染成那份。所以当年改成原地追加。
    三种异常各自退避（都不丢数据）：
      · 文件被 Excel 打开着 → 重试 3 次后另存为新的时间戳文件
      · 文件不存在/路径为空 → 退回 `_save_enrich_excel` 新建
      · 列头不符（拿到别的 xlsx）→ 不追加，改为新建（护住 10 列硬契约）
    """
    with EXCEL_LOCK:
        path = paths.ENRICH_FILE or find_latest_result()
        if path and os.path.exists(path):
            for attempt in range(3):
                wb = None
                try:
                    wb = load_workbook(path)
                    ws = wb.active
                    head = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
                    if not head or list(head)[:10] != EXCEL_HEADER_10:
                        log('⚠️ 当前结果文件列头不是本工具的 10 列契约，改为另存新文件')
                        wb.close()
                        wb = None
                        break
                    data = [r for r in ws.iter_rows(min_row=2, values_only=True) if r and r[1]]
                    data.append(tuple(_row10(row)))
                    # 与搜索产出一致：整表按评分降序，方便一眼看到重点客户
                    data.sort(key=lambda r: -(r[5] if isinstance(r[5], (int, float)) else 0))
                    ws.delete_rows(2, ws.max_row)
                    for r in data:
                        ws.append(list(r))
                    for col, w in zip('ABCDEFGHIJ', EXCEL_WIDTHS_10):
                        ws.column_dimensions[col].width = w
                    wb.save(path)
                    wb.close()
                    STATE['output'] = f'{OUTPUT_DIRNAME}/{os.path.basename(path)}'
                    log(f'💾 已追加到结果文件：{STATE["output"]}（现 {len(data)} 行）')
                    return True
                except PermissionError:
                    if wb:
                        try:
                            wb.close()
                        except Exception:
                            pass
                    if attempt < 2:
                        log('⚠️ 结果 Excel 正被 Excel 打开，稍后重试…')
                        time.sleep(0.6)
                    else:
                        log('⚠️ 结果 Excel 一直被占用，本次另存为新文件（数据没丢）')
                except Exception as e:
                    log(f'⚠️ 结果 Excel 追加失败：{type(e).__name__}: {e}（另存新文件）')
                    if wb:
                        try:
                            wb.close()
                        except Exception:
                            pass
                    break
        return _save_enrich_excel([row], industry=row.get('industry', ''))


def _save_enrich_excel(results, industry='', country=''):
    """写出本轮结果。固定 10 列——飞书导出与启动迁移都按下标读取，列名与顺序不可改。
    文件名：行业-日期_时间-主国家.xlsx（如 宠物用品-20260928_0145-加拿大.xlsx），
    统一写到 output/ 子目录，每轮一份便于留档。

    `industry` / `country` 都留空时行为与以前完全一致（行业从行里推、国家取条数最多的）。
    手动采集的「本轮会话」会显式传入开轮时定下的行业/国家，这样同一轮 Excel 的名字
    不会因为批次里混了其它国家而改变。同名文件由 `ts_result_path()` 自动加 `_2`/`_3` 后缀。
    """
    # ⚠️ 这里原来是 `global ENRICH_FILE`。ENRICH_FILE 已搬进 core/paths.py，
    # 且是全项目唯一会被重新赋值的模块级变量 —— 必须按属性写 `paths.ENRICH_FILE`，
    # 否则只会在本模块里新建一个同名全局，core/db.py 与飞书导出读到的仍是旧路径。
    out = Workbook()
    ows = out.active
    ows.title = '客户名单'
    ows.append(['公司/页面标题', '网站网址', '邮箱', '电话', '联系页',
                '评分', '评级', '摘要', '搜索公式', '国家'])
    for r in sorted(results, key=lambda x: -x['score']):
        ows.append([r['title'], r['url'], ' / '.join(r['emails']), ' / '.join(r['phones']),
                    r['contact_url'], r['score'], r['rating'], r['snippet'], r['formula'],
                    r.get('country', '')])
    for col, w in zip('ABCDEFGHIJ', (50, 50, 40, 20, 40, 8, 10, 60, 50, 10)):
        ows.column_dimensions[col].width = w
    path = ts_result_path(_pick_industry(industry, results),
                          (country or '').strip() or _pick_country(results))
    try:
        out.save(path)
        paths.ENRICH_FILE = path                # 后续飞书导出读这份最新结果
        STATE['output'] = f'{OUTPUT_DIRNAME}/{os.path.basename(path)}'
        log(f'💾 结果已保存：{STATE["output"]}')
        return True
    except Exception as e:
        log(f'⚠️ 结果 Excel 保存失败（可能被 Excel 占用）：{type(e).__name__}: {e}')
        return False


def _flush_manual_session():
    """结束「本轮手动采集」：把本轮明细落成一份结果 Excel，并把它设为「最新结果文件」。

    与自动搜索的 `finally` 落盘对齐 —— 一轮一份文件，而不是采一条追加一次。

    三处刻意设计：
      · **空轮不落盘**：本轮只有「已在库」的跳过期（或压根没采到），就不产出一份 0 行的表，
        也不会动 `paths.ENRICH_FILE` / `STATE['output']`。
      · **只写新客户**：`kind='existed'` 的行只是给人看「这条之前就有」，不进 Excel。
      · **失败不清数据**：保存失败时保留 `session_rows` 且 `session_active` 仍为 True，
        页面红字提示、用户可以直接再点一次「结束」（数据最坏也还在 SQLite 客户库里）。
    """
    with STATE_LOCK:
        snap = list(MANUAL_STATE.get('session_rows') or [])          # 锁内快照，出锁再做 IO
        industry = (MANUAL_STATE.get('session_industry') or '').strip()
        country = (MANUAL_STATE.get('session_country') or '').strip()
        rows = [r for r in snap if r.get('kind') != 'existed']
        empty = not rows
        if empty:
            MANUAL_STATE.update({'session_active': False, 'session_finish_pending': False,
                                 'session_rows': [], 'session_excel': '', 'session_error': ''})
        else:
            MANUAL_STATE['session_finish_pending'] = False

    # ⚠️ log() 内部也要抢 STATE_LOCK（非可重入的 Lock），所以任何 log 都必须在**锁外**调，
    #    否则自己把自己锁死 —— 这个坑在本函数和 _manual_batch_worker 里都踩过。
    if empty:
        log('本轮没有采到新客户，未生成结果文件')
        return {'ok': True, 'saved': False, 'msg': '本轮没有采到新客户，未生成结果文件'}

    log(f'====== 结束本轮手动采集：新客户 {len(rows)} 条，正在生成 Excel ======')
    with EXCEL_LOCK:                       # 与自动搜索的落盘互斥；Excel 写盘一律在 STATE_LOCK 外
        ok = _save_enrich_excel(rows, industry=industry, country=country)
        if not ok:                         # 多半是被 Excel 打开着 —— 退避一秒再试一次
            time.sleep(0.8)
            ok = _save_enrich_excel(rows, industry=industry, country=country)

    with STATE_LOCK:
        if ok:
            MANUAL_STATE.update({'session_active': False, 'session_rows': [], 'session_error': '',
                                 'session_excel': os.path.basename(paths.ENRICH_FILE or '')})
            out = STATE.get('output', '')
        else:
            MANUAL_STATE['session_error'] = ('结果 Excel 保存失败（可能被 Excel 占用），'
                                             '本轮数据已保留，可直接重试')
            out = ''
    if ok:
        log(f'====== 本轮结果已保存：{out} ======')
        return {'ok': True, 'saved': True, 'file': out, 'rows': len(rows)}
    return {'ok': False, 'saved': False, 'msg': MANUAL_STATE['session_error']}


def enrich_core(industry=''):
    """批量补全主体：逐个访问客户官网抓邮箱/电话并评分，回写客户库。
    专用于收拾客户库里的历史欠账（搜索过程本身已经就地抓取），入口是命令行脚本「补历史欠账.py」。
    industry 用于结果文件命名；留空时自动从结果推断。
    不负责 STATE['running'] / ['done']，由调用方统一管理。返回本次实际处理条数。"""
    page = None
    results = []
    saved = False
    items = _enrich_worklist()
    if not items:
        log('无需补全：客户库里没有「邮箱和电话都为空」的记录')
        return 0
    eta = max(1, len(items) * 20 // 60)
    log(f'待补全 {len(items)} 个网站（历史欠账），预计约 {eta} 分钟；可随时点「停止」。'
        f'注意：本次仍抓不到邮箱和电话的站点，下次还会再被访问一次')
    try:
        page = create_browser_page()
        for i, item in enumerate(items, 1):
            if STATE['stop']:
                log('已停止补全')
                break
            info = enrich(page, item['url'])
            s = score_item(item['title'], item['url'], info)
            enriched = {**item, **info, 'score': s, 'rating': rating(s)}
            db_upsert_customer({
                'company_name': item['title'], 'website': item['url'],
                'email': ' / '.join(info['emails']), 'phone': ' / '.join(info['phones']),
                'contact_url': info['contact_url'], 'score': s, 'rating': rating(s),
                'snippet': item['snippet'], 'search_formula': item['formula'],
                'country': item.get('country', ''),
            })
            results.append(enriched)
            STATE['result_count'] = len(results)
            log(f'[{i}/{len(items)}] {item["url"][:55]} 邮箱{len(info["emails"])}个 评分{s}')
            time.sleep(1)
    except Exception as e:
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
        # 中途停止也把已抓到的结果落盘，避免白跑一场
        if results:
            saved = _save_enrich_excel(results, industry=industry)
    if results:
        key_count = sum(1 for r in results if r['score'] >= 70)
        mail_count = sum(1 for r in results if r['emails'])
        tail = (f'已保存 {os.path.basename(paths.ENRICH_FILE)}' if saved
                else '结果 Excel 未写出（客户库已更新，不影响飞书导出以外的用途）')
        log(f'✅ 补全完成！共 {len(results)} 个：{mail_count} 个有邮箱，'
            f'{key_count} 个重点客户(≥70分)。{tail}')
    return len(results)


# ================= 导出到飞书 =================
# 「来源渠道」是飞书的**单选**字段，取值必须是表里已有的选项，否则整条记录会被拒。
# 客户库 customers.source 目前只有这三个取值（谷歌搜索 / 谷歌地图由两条自动链路写，
# 手动采集由 collect_from_html 写）。⚠️ 在飞书「客户信息」表里给「来源渠道」加选项时，
# 记得同步改这里。
FEISHU_SOURCES = ('谷歌搜索', '谷歌地图', '手动采集')


def build_feishu_records():
    """读取最近一份结果 Excel，生成待导入飞书的记录。

    · 评分门槛：**≥50 分**才导出 —— 但 `[手动采集]` 的行豁免，理由见下面循环里的注释。
    · 来源渠道：结果 Excel 的 10 列里**没有**这一列（列契约一个都不能改），所以按网址
      回客户库查真实的 source。一次性查成 map，不在循环里逐条开连接。
    """
    path = paths.ENRICH_FILE or find_latest_result()
    if not path or not os.path.exists(path):
        log('⚠️ 没找到结果 Excel（形如 行业-日期_时间-国家.xlsx），请先运行「开始搜索」')
        return []
    log(f'读取结果文件：{os.path.basename(path)}')

    src_map = {}
    try:
        with closing(db_connect()) as conn:
            for k, s in conn.execute('SELECT website_key, source FROM customers'):
                if k and s:
                    src_map[k] = s
    except Exception as e:
        log(f'⚠️ 读取客户库来源失败（本行统一按「谷歌搜索」写）：{type(e).__name__}: {e}')

    wb = load_workbook(path)
    ws = wb.active
    records = []
    warned_src = set()
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not (r and r[1]):
            continue
        # 列：0标题 1网址 2邮箱 3电话 4联系页 5评分 6评级 7摘要 8公式 9国家
        title, url = r[0], r[1]
        emails = r[2] or ''
        phones = r[3] or ''
        score = r[5]
        rating = r[6] or ''
        formula = r[8] if len(r) > 8 else ''
        country = r[9] if len(r) > 9 and r[9] else ''
        manual = str(formula or '').startswith('[手动采集]')
        # ⚠️ 50 分门槛是用来拦「自动搜索捞进来的无关垃圾站」的；手动采集是用户自己
        #    认定「这个网站就是我的目标客户」才动手点的，低分不该被静默丢掉 —— 豁免它。
        if not manual and (not isinstance(score, (int, float)) or score < 50):
            continue
        mails = [m.strip() for m in emails.split(' / ') if EMAIL_OK.match(m.strip())]
        note = '脚本评分%d分（%s），待人工核实' % (int(score) if isinstance(score, (int, float)) else 0, rating)
        if manual:
            note += '；手动采集'
        if len(mails) > 1:
            note += '；其他邮箱：' + ' / '.join(mails[1:])
        src = src_map.get(normalize_domain(url), '谷歌搜索')
        if src not in FEISHU_SOURCES:
            if src not in warned_src:
                warned_src.add(src)
                log(f'⚠️ 客户库里的来源渠道取值「{src}」不在飞书单选选项里，本行按「谷歌搜索」写入')
            src = '谷歌搜索'
        rec = {
            '公司名称': title,
            '官网': url,
            '电话': phones,
            '来源渠道': [src],
            '使用的搜索公式': formula,
            '跟进状态': ['未联系'],
            '备注': note,
        }
        if country:
            rec['国家/地区'] = [COUNTRY_STANDARD.get(country, country)]
        if mails:
            rec['邮箱'] = mails[0]
        records.append(rec)
    wb.close()
    return records


def run_export_feishu():
    """后台任务：把评分结果导出到飞书多维表格"""
    try:
        STATE['phase'] = 'export'
        log('准备导出到飞书...')
        records = build_feishu_records()
        if not records:
            log('没有可导出的记录（需要评分≥50分的客户，请先运行「开始搜索」完成抓取与评分）')
            return
        log(f'共 {len(records)} 条记录待导出')
        base_dir = _app_dir()          # 程序根（原来是内联的 dirname(abspath(__file__))）
        tmp_path = os.path.join(base_dir, IMPORT_JSON)
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({'create_records': records}, f, ensure_ascii=False)
        env = os.environ.copy()
        env.pop('HERMES_HOME', None)   # 清除该变量，否则 lark-cli 返回异常
        cmd = [LARK_CLI, 'base', '+record-batch-create',
               '--base-token', BASE_TOKEN, '--table-id', TABLE_ID,
               '--json', '@' + IMPORT_JSON, '--as', 'user']
        log('正在写入飞书...')
        r = subprocess.run(cmd, env=env, capture_output=True, cwd=base_dir)
        out = ''
        for raw in (r.stdout, r.stderr):
            if not raw:
                continue
            for enc in ('utf-8', 'gbk'):
                try:
                    out += raw.decode(enc)
                    break
                except Exception:
                    continue
        ok = False
        try:
            ok = bool(json.loads(r.stdout.decode('utf-8')).get('ok'))
        except Exception:
            pass
        if ok:
            log(f'✅ 导出成功！已写入飞书 {len(records)} 条客户记录。')
        else:
            log(f'❌ 导出失败：{out.strip()[:500]}')
    except Exception as e:
        log(f'❌ 出错：{type(e).__name__}: {e}')
    finally:
        STATE['done'] = True
        STATE['running'] = False


# ================= Flask 应用 =================
app = Flask(__name__)
# 兜住超大请求体：Chrome 扩展会把当前页 HTML 一起送过来（正常 ≤500KB），
# 这里给个 2MB 上限，超了直接 413，不进入业务逻辑。全站没有任何文件上传，设它安全。
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

# 实际监听端口（由 __main__ 里 pick_port() 决定后回填），只用于 /api/ping 告诉扩展连哪个端口。
# ⚠️ 端口仍是运行时决定的，不落文件、不写死 —— 保留段每次开机漂移，见 pick_port() 的说明。
_RUN_PORT = 0


@app.before_request
def _cors_preflight():
    """让浏览器扩展的预检请求过关。

    扩展发的是 `Content-Type: application/json` + 自定义头 `X-DP-Ext`，属于「非简单请求」，
    浏览器会**先发 OPTIONS 预检**。这里直接放行 OPTIONS，真正的来源校验在 after_request 里做
    （只有 chrome-extension:// 才会拿到 Access-Control-Allow-Origin）。
    """
    if request.method == 'OPTIONS':
        return ('', 204)


@app.after_request
def _cors_headers(resp):
    """CORS：**只**回显 chrome-extension:// 来源，绝不返回 `*`。

    这样能挡住「你正在浏览别的网站时，那个页面偷偷调本工具接口」：
      ① 恶意页面带 json/自定义头 → 浏览器先发预检 → 我们不给它 ACAO → 浏览器判定失败
         → **真正的 POST 根本不会发出**（不是发了再拦响应）；
      ② 不给 `*`、不给 Allow-Credentials → 任意站点读不到响应内容；
      ③ `Vary: Origin` 防止中间缓存把带 ACAO 的响应串给别的源。
    残余风险（已接受并写在 extension/README.md）：加载前拿不到本扩展的 ID，所以只能按
    「只要是 chrome-extension:// 就回显」，本机其它扩展理论上也能调 —— 已被「只绑 127.0.0.1」
    收敛在本机可信域内。
    """
    origin = request.headers.get('Origin', '')
    if origin.startswith('chrome-extension://'):
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-DP-Ext'
        resp.headers['Access-Control-Max-Age'] = '600'
        with STATE_LOCK:                     # 顺手当扩展心跳：/manual 页据此显示「扩展在线」
            MANUAL_STATE['ext_last_seen'] = time.time()
    resp.headers['Vary'] = 'Origin'
    return resp


@app.route('/')
def index():
    return PAGE_HTML


@app.route('/manual')
def manual_page():
    """手动采集页：扩展连接状态 + 批量粘贴 + 最近记录 + 关闭采集浏览器。

    ⚠️ 首页顶栏有指向本页的导航（V1.5 加，见 `ui/page.html` 的 `.nav`）。
       改主页那两个链接会连带改 page.html 的 sha256 → 必须同步重算 `_check_page.py`
       R5 的 `_TMPL_SHA` / `_BUILT_SHA`：前者 = 文本模式读 page.html 的 sha256，
       后者 = `core.ui._build_page()` 结果的 sha256。
    """
    return MANUAL_HTML


@app.route('/api/ping')
def api_ping():
    """扩展用它「发现端口 + 确认这就是本工具」。
    app 字段是身份标记：扩展只在 `ok && app == 'waimao-dp'` 时才认，避免误连到本机别的服务。"""
    with STATE_LOCK:
        running = STATE['running']
        manual_running = MANUAL_STATE['running']
    return jsonify({
        'ok': True,
        'app': 'waimao-dp',
        'name': '谷歌客户开发工具',
        'port': _RUN_PORT,
        'running': running,
        'manual_running': manual_running,
        'enrich_file': os.path.basename(paths.ENRICH_FILE or ''),
    })


# ================= 手动采集：接口 =================
@app.route('/api/collect', methods=['POST', 'OPTIONS'])
def api_collect():
    """Chrome 扩展点一下「采集」就走这里（同步返回，popup 直接显示结果）。

    ⚠️ 两道门缺一不可：
      ① 自定义头 `X-DP-Ext` —— 自定义头必然触发 CORS 预检，而我们的 after_request 只给
         chrome-extension:// 来源发 ACAO，所以网页里的恶意 fetch 连预检都过不去；
      ② `request.get_json()` —— 非 application/json 拿不到数据，堵掉「简单请求」直发。
    """
    if request.headers.get('X-DP-Ext') != '1':
        return jsonify({'ok': False, 'msg': 'unauthorized'}), 403
    d = request.get_json(silent=True) or {}
    if not (d.get('url') or '').strip():
        return jsonify({'ok': False, 'msg': '没有拿到网址'})
    words = d.get('product_words') or None
    if isinstance(words, str):
        words = [w.strip() for w in re.split(r'[\n,;，；]+', words) if w.strip()]
    return jsonify(collect_from_html(
        d.get('url'), d.get('title'), d.get('html'),
        industry=(d.get('industry') or '').strip(),
        country=(d.get('country') or '').strip(),
        allow_upgrade=bool(d.get('upgrade', True)),
        product_words=words))


def _manual_batch_worker(urls, industry, country, allow_upgrade, product_words):
    """批量粘贴采集：**单线程串行**跑。

    为什么串行：① 本轮结束时的落盘要串行（EXCEL_LOCK）；② 「升级抓取」共用同一个
    常驻浏览器；③ 避免日志交错不可读、以及本地资源被并发打爆。

    本函数只负责「批量子过程」；采到的行由 `collect_from_html` 攒进本轮明细，
    落盘由用户点「🏁 结束并生成 Excel」触发（或下方 finally 里的挂起收尾）。
    """
    log(f'====== 开始手动采集：{len(urls)} 条 ======')
    try:
        for i, u in enumerate(urls, 1):
            with STATE_LOCK:
                stopped = MANUAL_STATE['stop']
                if not stopped:
                    MANUAL_STATE['current'] = u
            # ⚠️ log() 自己要抢 STATE_LOCK，只能在锁外调（原来这里写在 with 块里，是个死锁）
            if stopped:
                log('已停止手动采集')
                break
            try:
                collect_from_html(u, '', '', industry=industry, country=country,
                                  allow_upgrade=allow_upgrade, product_words=product_words)
            except Exception as e:
                with STATE_LOCK:
                    MANUAL_STATE['failed'] += 1
                log(f'   ❌ 采集失败 {u[:60]}：{type(e).__name__}: {e}')
            with STATE_LOCK:
                MANUAL_STATE['done'] = i
            if i < len(urls):
                time.sleep(1)
    finally:
        with STATE_LOCK:
            MANUAL_STATE['running'] = False
            MANUAL_STATE['current'] = ''
            pending = MANUAL_STATE.get('session_finish_pending')
        log(f'====== 手动采集结束：成功 {MANUAL_STATE["added"]} / 已有 {MANUAL_STATE["existed"]} '
            f'/ 失败 {MANUAL_STATE["failed"]} ======')
        if pending:
            # 用户在批量还在跑的时候点了「结束并生成 Excel」—— 替他把本轮落盘。
            # 放在锁外（落盘是慢 IO），且此时 running 已置 False、循环已退出，不会再有新行进来。
            log('收到「结束本轮」请求（批量收尾中），现在生成 Excel…')
            _flush_manual_session()


@app.route('/api/manual/batch', methods=['POST'])
def api_manual_batch():
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '自动搜索/采集正在运行，请先等它结束'})
    with STATE_LOCK:
        if MANUAL_STATE['running']:
            return jsonify({'ok': False, 'msg': '手动采集已在运行'})
    d = request.get_json(silent=True) or {}
    raw = d.get('urls') or ''
    urls = [u.strip() for u in re.split(r'[\s]+', raw) if u.strip()]
    if not urls:
        return jsonify({'ok': False, 'msg': '请至少粘贴一个网址（一行一个）'})
    urls = urls[:200]                       # 手滑粘几千行的话给个上限
    words = d.get('product_words') or None
    if isinstance(words, str):
        words = [w.strip() for w in re.split(r'[\n,;，；]+', words) if w.strip()]
    ind = (d.get('industry') or '').strip()
    cty = (d.get('country') or '').strip()
    # 批量属于「本轮」的一部分：本轮没开始就先开起来（表单里的行业/国家即本轮口径）
    _ensure_manual_session(ind, cty)
    with STATE_LOCK:
        # ⚠️ 只重置「批量子过程」的字段；added/existed/failed/upgraded 是**本轮**计数，
        #    这里清零会把本轮先前（比如扩展单点）的成果抹掉。
        MANUAL_STATE.update({'running': True, 'stop': False, 'total': len(urls),
                             'done': 0, 'current': ''})
    threading.Thread(target=_manual_batch_worker,
                     args=(urls, ind, cty, bool(d.get('upgrade', True)), words),
                     daemon=True).start()
    return jsonify({'ok': True, 'total': len(urls)})


@app.route('/api/manual/session/start', methods=['POST'])
def api_manual_session_start():
    """显式开一轮手动采集（页面上的「🟢 开始本轮采集」）。

    ⚠️ 本轮已有内容时**拒绝**而不是覆盖：覆盖会静默丢掉刚采到的行。
       要重来的话正确姿势是先「结束并生成 Excel」（落盘留档）再开新一轮。
    """
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '自动搜索/采集正在运行，请先等它结束'})
    d = request.get_json(silent=True) or {}
    with STATE_LOCK:
        if MANUAL_STATE['running']:
            return jsonify({'ok': False, 'msg': '批量采集正在运行，本轮已在进行中'})
        if MANUAL_STATE.get('session_active') and MANUAL_STATE.get('session_rows'):
            return jsonify({'ok': False,
                            'msg': '本轮还在进行中，请先「🏁 结束并生成 Excel」再开新一轮'})
        MANUAL_STATE.update({
            'session_active': True, 'session_started_at': time.time(),
            'session_rows': [], 'session_rid_seq': 0,
            'session_excel': '', 'session_error': '',
            'session_finish_pending': False,
            'added': 0, 'existed': 0, 'failed': 0, 'upgraded': 0,
            'session_industry': (d.get('industry') or '').strip(),
            'session_country': (d.get('country') or '').strip(),
        })
    log('====== 已开始本轮手动采集 ======')
    return jsonify({'ok': True})


@app.route('/api/manual/session/finish', methods=['POST'])
def api_manual_session_finish():
    """结束本轮：落盘成一份结果 Excel，并设为「最新结果文件」。

    批量还在跑时不阻塞这个请求 —— 只置 `stop` + 挂起标志，由 worker 的 finally 落盘
    （当前那条可能正卡在 3–10s 的升级抓取里，在这里 join 会把 HTTP 请求拖死）。
    """
    with STATE_LOCK:
        if not MANUAL_STATE.get('session_active'):
            return jsonify({'ok': False, 'msg': '当前没有进行中的本轮采集，无需结束'})
        if MANUAL_STATE['running']:
            MANUAL_STATE['stop'] = True
            MANUAL_STATE['session_finish_pending'] = True
            return jsonify({'ok': True, 'pending': True,
                            'msg': '正在停止批量并收尾，稍候会自动生成 Excel…'})
    return jsonify(_flush_manual_session())


@app.route('/api/manual/session/delete', methods=['POST'])
def api_manual_session_delete():
    """把本轮明细里的某一条删掉，**并同时从客户库删掉它**（删除前自动备份客户库）。

    为什么要删库：采集那一刻记录就已经写进 SQLite 了（`_commit_candidate` → `db_upsert_customer`）。
    只删明细是假删除 —— 库里那条还在，下次再采到同一个站会被 db_has_customer 判「已在客户库」
    直接跳过、永远采不回来，飞书导出也仍会带它。

    ⚠️ 锁纪律（STATE_LOCK 非可重入，且 log() 自己也要抢同一把锁）：
       ① 锁内定位  ② 锁外做备份与 DB 删除（慢 IO）  ③ 锁内改内存  ④ 锁外 log。
    ⚠️ 定位用 rid 而不是 url：同一 url 在同一轮里可能既有一条 added 又有一条 existed，
       按 url 删会一次删两条。无 rid 的条目（老数据/测试造的假行）一律拒绝，不误删。
    """
    d = request.get_json(silent=True) or {}
    rid = d.get('rid')
    with STATE_LOCK:
        rows = MANUAL_STATE.get('session_rows') or []
        hit = next((r for r in rows if r.get('rid') == rid), None) if rid is not None else None
        if hit is None:
            return jsonify({'ok': False,
                            'msg': '这条已不在本轮明细里（可能已被删除，或本轮已结束）'})
        url = hit.get('url') or ''
        kind = hit.get('kind')

    backup = backup_db_before_delete()      # 锁外：先备份（失败不阻断，返回 ''）
    deleted = db_delete_customer(url)       # 锁外：真删库

    with STATE_LOCK:
        rows = MANUAL_STATE.get('session_rows') or []
        idx = next((i for i, r in enumerate(rows) if r.get('rid') == rid), -1)
        if idx >= 0:
            rows.pop(idx)
        # 计数跟着回退，否则状态行的「已采 N 条」会与实际行数对不上。
        # upgraded/failed 不动：它们是「本轮发生过几次」的事件计数，不指涉某一行。
        ckey = 'existed' if kind == 'existed' else 'added'
        MANUAL_STATE[ckey] = max(0, (MANUAL_STATE.get(ckey) or 0) - 1)
        n = len(rows)

    log(f'🗑️ 已从本轮明细删除：{url[:60]}（客户库删除 {deleted} 条）')
    return jsonify({'ok': True, 'deleted': deleted, 'rows': n,
                    'backup': os.path.basename(backup) if backup else ''})


@app.route('/api/manual/stop', methods=['POST'])
def api_manual_stop():
    with STATE_LOCK:
        MANUAL_STATE['stop'] = True       # ⚠️ 只停手动队列，不动 STATE['stop']（那会误杀自动搜索）
    return jsonify({'ok': True})


@app.route('/api/manual/state')
def api_manual_state():
    with STATE_LOCK:
        st = dict(MANUAL_STATE)
        # ⚠️ `dict()` 是浅拷贝：session_rows 必须换成独立快照，否则 jsonify 遍历列表期间
        #    worker 线程又 append，会撞上「遍历中容器被修改」。
        st['session_rows'] = list(MANUAL_STATE.get('session_rows') or [])
    st['now'] = time.time()               # 让前端能自己算「扩展心跳是几秒前」
    try:
        with closing(db_connect()) as conn:
            conn.row_factory = sqlite3.Row
            st['recent'] = [dict(r) for r in conn.execute(
                "SELECT company_name,website,email,phone,score,rating,industry,country,"
                "last_seen_at FROM customers WHERE source='手动采集' "
                "ORDER BY datetime(last_seen_at) DESC, id DESC LIMIT 50")]
    except Exception:
        st['recent'] = []
    return jsonify(st)


@app.route('/api/manual/close_browser', methods=['POST'])
def api_manual_close_browser():
    return jsonify({'ok': True, 'closed': close_manual_browser()})


# 自定义搜索词（主页第 6 卡）单轮条数上限：一条 × 每条抓 pages 页 × 每页约 10 条，
# 20 条已足够撑满一次 100 条的目标；再多大概率触发谷歌限流（限流要等 90 秒才恢复）。
RAW_QUERY_MAX = 20


@app.route('/api/start', methods=['POST'])
def api_start():
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '任务正在运行'})
    data = request.get_json()
    # 自定义搜索词（主页第 6 卡）：一行一条，**原样**当一条查询用。
    # 空行/纯空白丢弃、去重保序；硬上限防「误粘一大段文本」把整轮拖成几小时（谷歌还会限流）。
    raw_in = data.get('custom_queries')
    raw_queries = []
    if isinstance(raw_in, list):
        for q in raw_in:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if q and q not in raw_queries:
                raw_queries.append(q)
    if len(raw_queries) > RAW_QUERY_MAX:
        return jsonify({'ok': False, 'msg': f'自定义搜索词一次最多 {RAW_QUERY_MAX} 条'})
    products = [p.strip() for p in data.get('products', '').splitlines() if p.strip()]
    if not products and not raw_queries:
        return jsonify({'ok': False, 'msg': '请填写至少一个产品关键词，或填一条自定义搜索词'})
    cond_keys = data.get('conditions', [])
    countries = [c for c in COUNTRIES if c[0] in data.get('countries', [])]
    if not countries:
        countries = [COUNTRIES[0]]
    pages = int(data.get('pages', 2) or 2)
    try:
        target_count = int(data.get('target_count', 10))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'msg': '目标客户数量必须是 10-100 的整数'})
    if not 10 <= target_count <= 100:
        return jsonify({'ok': False, 'msg': '目标客户数量只能设置为 10-100'})
    with STATE_LOCK:
        STATE.update(running=True, done=False, logs=[], result_count=0, rows=[],
                     output='', stop=False, phase='search')
    exclude = data.get('exclude', EXCLUDE_DEFAULT)
    china_filters = [k for k in data.get('china_filters', CHINA_FILTER_DEFAULTS)
                     if k in CHINA_FILTER_DEFAULTS]
    match = data.get('match', 'or')
    industry = (data.get('industry') or '').strip()
    auto_enrich = bool(data.get('auto_enrich', True))   # 搜索时是否就地抓取联系方式（不勾=只收集网站线索）
    lang = (data.get('lang') or '').strip()             # 条件词的搜索语言，留空由 run_search 按国家 hl 推断
    # 数据源：google=谷歌网页搜索（默认，老链路），maps=谷歌地图名录（新链路）
    source = (data.get('source') or 'google').strip()
    city = (data.get('city') or '').strip()             # 仅地图用：城市/地区名，会拼进查询词
    # 国家限定（主页第 4 步，可选，默认关）：none / cr / site / both。非法值静默回落 none。
    # 只对网页搜索生效 —— 地图走 run_maps（根本不接收该参数），自定义模式在 run_search 内强制置 none。
    country_limit = (data.get('country_limit') or COUNTRY_LIMIT_DEFAULT).strip()
    if country_limit not in COUNTRY_LIMIT_MODES:
        country_limit = COUNTRY_LIMIT_DEFAULT
    if source == 'maps' and raw_queries:
        # 自定义搜索词只服务「谷歌网页搜索」：地图走「关键词库 + 城市 + 身份词」，这里直接忽略
        log(f'⚠️ 地图模式不使用自定义搜索词，已忽略 {len(raw_queries)} 条（切回谷歌网页搜索可用）')
        raw_queries = []
    if source == 'maps':
        t = threading.Thread(target=run_maps,
                             args=(products, cond_keys, countries, city, target_count, industry,
                                   auto_enrich, lang, china_filters),
                             daemon=True)
        t.start()
        return jsonify({'ok': True})
    t = threading.Thread(target=run_search,
                         args=(products, cond_keys, countries, pages, exclude, match, target_count, industry,
                               auto_enrich, lang, china_filters),
                         kwargs={'raw_queries': raw_queries, 'country_limit': country_limit},
                         daemon=True)
    t.start()
    return jsonify({'ok': True})


@app.route('/api/export_feishu', methods=['POST'])
def api_export_feishu():
    if STATE['running']:
        return jsonify({'ok': False, 'msg': '任务正在运行'})
    with STATE_LOCK:
        STATE.update(running=True, done=False, logs=[], result_count=0,
                     output='', stop=False, phase='export')
    threading.Thread(target=run_export_feishu, daemon=True).start()
    return jsonify({'ok': True})


@app.route('/api/open_folder', methods=['POST'])
def api_open_folder():
    try:
        os.startfile(output_dir())   # Windows 下打开文件资源管理器（结果 Excel 所在目录）
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/api/keywords')
def api_keywords():
    base_dir = _app_dir()          # 程序根（原来是内联的 dirname(abspath(__file__))）
    try:
        with open(os.path.join(base_dir, KEYWORD_LIB), 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({})


@app.route('/api/db_stats')
def api_db_stats():
    try:
        return jsonify({'ok': True, **db_stats()})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


# ================= 客户库查询页 /db 与导出 =================
# 纯读链路：**不占 STATE_LOCK、不改 paths.ENRICH_FILE / STATE['output']**（原因见 core/db.py
# 「客户库查询」一节）。所以这里的查询再慢也不会把采集/落盘/页面轮询卡住。
@app.route('/db')
def query_page():
    """客户库查询页：按行业/国家/来源/评级/评分/联系方式筛客户，满意后导出 Excel。

    与 /manual 一样，首页顶栏已有指向本页的导航。入口共三处：扩展面板底部按钮 /
    首页顶栏 / `/manual` 页顶部链接。
    """
    return QUERY_HTML


@app.route('/api/db/facets')
def api_db_facets():
    """筛选面板的勾选项：库里**真实存在**的取值 + 各自条数（不是硬编码的行业枚举）。"""
    try:
        return jsonify({'ok': True, **db_facet_counts()})
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'{type(e).__name__}: {e}'})


def _query_payload(src):
    """从 POST 的 JSON body 取筛选条件与分页参数（前端固定用 JSON 传，因为多选是数组）。"""
    d = src if isinstance(src, dict) else {}
    filters = d.get('filters')
    return {
        'filters': filters if isinstance(filters, dict) else {},
        'order': d.get('order') or '',
        'limit': d.get('limit', 50),
        'offset': d.get('offset', 0),
    }


@app.route('/api/db/query', methods=['POST'])
def api_db_query():
    """按条件分页查询。条件非法（例如评分区间填了字母）时返回 ok=False 并说明原因。"""
    p = _query_payload(request.get_json(silent=True))
    try:
        total, rows, limit = db_query_customers(p['filters'], order=p['order'],
                                                limit=p['limit'], offset=p['offset'])
        offset = max(0, int(p['offset'] or 0))
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'{type(e).__name__}: {e}'})
    return jsonify({'ok': True, 'total': total, 'rows': rows,
                    'limit': limit, 'offset': offset})


# 查询导出的列（客户库全字段）。**刻意不复用结果 Excel 的 10 列硬契约**：
# 那是「本轮采集结果」的格式，飞书导出与启动迁移都按**下标**读它；查询导出是另一类产物，
# 多带行业 / 来源渠道 / 采集时间这些跟进客户时真正用得上的字段，两边互不影响。
QUERY_EXPORT_COLUMNS = (
    ('company_name', '公司名称'), ('website', '网站网址'), ('email', '邮箱'),
    ('phone', '电话'), ('contact_url', '联系页'), ('country', '国家'),
    ('industry', '行业'), ('score', '评分'), ('rating', '评级'),
    ('source', '来源渠道'), ('snippet', '摘要'), ('search_formula', '搜索公式'),
    ('first_seen_at', '首次采集时间'), ('last_seen_at', '最近更新时间'),
)
QUERY_EXPORT_WIDTHS = (34, 42, 30, 20, 34, 12, 14, 8, 10, 12, 50, 40, 20, 20)
QUERY_EXPORT_MAX = 5000          # 单次导出的硬上限：再多就提示收窄条件，别把内存撑爆


def _save_query_excel(rows, path):
    """把查询结果写成 Excel（14 列，见 QUERY_EXPORT_COLUMNS）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '查询结果'
    ws.append([title for _, title in QUERY_EXPORT_COLUMNS])
    for r in rows:
        ws.append([r.get(col, '') for col, _ in QUERY_EXPORT_COLUMNS])
    for i, w in enumerate(QUERY_EXPORT_WIDTHS):      # 14 列 < 26，chr 够用
        ws.column_dimensions[chr(ord('A') + i)].width = w
    wb.save(path)
    return path


@app.route('/api/db/export', methods=['POST'])
def api_db_export():
    """按当前条件导出**全部命中行**（不受分页影响），返回可下载的文件名与 URL。

    ⚠️ 落盘位置是 output/查询导出/**子目录**：output/ 根下的 *.xlsx 会被
       `find_latest_result()` 选中当「最新结果文件」，把飞书导出的目标劫持到查询表上。
    ⚠️ 本函数**绝不**碰 paths.ENRICH_FILE 与 STATE['output'] —— 那两个指针归「本轮采集」用。
    """
    p = _query_payload(request.get_json(silent=True))
    try:
        total, _, _ = db_query_customers(p['filters'], order=p['order'], limit=1, offset=0)
    except Exception as e:
        return jsonify({'ok': False, 'msg': f'{type(e).__name__}: {e}'})
    if total <= 0:
        return jsonify({'ok': False, 'msg': '当前条件没有命中任何客户，没有可导出的内容'})
    if total > QUERY_EXPORT_MAX:
        return jsonify({'ok': False, 'msg': f'命中 {total} 条，超过单次导出上限 '
                                            f'{QUERY_EXPORT_MAX} 条，请再加点筛选条件'})
    rows, offset = [], 0
    while len(rows) < total:                        # 分页拉完，避免一次 SELECT 太大
        _, page, _ = db_query_customers(p['filters'], order=p['order'],
                                        limit=QUERY_MAX_LIMIT, offset=offset)
        if not page:
            break
        rows.extend(page)
        offset += len(page)
    path = ts_query_export_path(len(rows))
    try:
        with EXCEL_LOCK:                            # 与其它 Excel 写盘互斥，写盘一律串行
            _save_query_excel(rows, path)
    except Exception as e:
        log(f'⚠️ 查询导出失败（可能被 Excel 占用）：{type(e).__name__}: {e}')
        return jsonify({'ok': False, 'msg': f'写入 Excel 失败：{type(e).__name__}: {e}'})
    name = os.path.basename(path)
    log(f'📤 客户库查询导出 {len(rows)} 条 → {OUTPUT_DIRNAME}/{QUERY_EXPORT_DIRNAME}/{name}')
    return jsonify({'ok': True, 'rows': len(rows), 'name': name,
                    'url': '/api/db/download/' + quote(name)})


@app.route('/api/db/download/<path:name>')
def api_db_download(name):
    """下载查询导出的 Excel。

    ⚠️ 必须挡路径穿越：只允许下载「查询导出目录里的那一个文件」，
       basename 之后还要再确认解析出来的目录就是导出目录本身。
    """
    d = query_export_dir()
    safe = os.path.basename(name or '')
    path = os.path.join(d, safe)
    if not safe or not os.path.isfile(path) \
            or os.path.dirname(os.path.abspath(path)) != os.path.abspath(d):
        return jsonify({'ok': False, 'msg': '文件不存在或已被移走'}), 404
    return send_file(path, as_attachment=True, download_name=safe)


@app.route('/api/db/open_folder', methods=['POST'])
def api_db_open_folder():
    """打开查询导出目录（与首页的「打开结果目录」分开，免得用户找不到导出的表）。"""
    try:
        os.startfile(query_export_dir())
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


@app.route('/api/db/delete', methods=['POST'])
def api_db_delete():
    """把查询结果里选中的客户从客户库删掉（**不可逆**，删前自动备份客户库）。

    前端固定 POST `{'ids': [主键…]}`：单行 ✕ 就是长度为 1 的数组，走同一条路
    （少一条代码路径就少一处「只有批量删才备份」之类的漏洞）。

    ⚠️ 只动客户库，**不碰 STATE / MANUAL_STATE**。若「本轮采集」正在进行，被删的这条
       仍留在它的内存明细里（那份明细不是从库里读的），要一并拿掉请到 /manual 点那行的 ✕，
       否则本轮生成的结果 Excel 仍会带上它。
    ⚠️ 锁纪律：本链路全程**不持 STATE_LOCK** —— `backup_db_before_delete()` 内部会调
       `log()`，而 `log()` 自己要抢那把**非可重入**锁，持锁调用必死锁。
    ⚠️ 删前备份由 `backup_db_before_delete()` 负责（300 秒节流 + sqlite 在线 backup，
       文件落 `DB/backups/`）；备份失败**不阻断**删除，只在返回体里如实说明。
    """
    p = request.get_json(silent=True)
    ids = (p or {}).get('ids') if isinstance(p, dict) else None
    if not isinstance(ids, list) or not ids:
        return jsonify({'ok': False, 'msg': '没有选中任何行'})
    if len(ids) > QUERY_DELETE_MAX:
        return jsonify({'ok': False,
                        'msg': f'一次最多删 {QUERY_DELETE_MAX} 条，请分批删除'})
    backup = backup_db_before_delete()              # 锁外：先备份（失败不阻断，返回 ''）
    try:
        deleted, missing = db_delete_customers_by_ids(ids)
    except Exception as e:
        log(f'⚠️ 客户库查询页删除失败：{type(e).__name__}: {e}')
        return jsonify({'ok': False, 'msg': f'{type(e).__name__}: {e}'})
    if deleted:
        tip = f'（另有 {len(missing)} 条库里已不存在）' if missing else ''
        log(f'🗑️ 客户库查询页删除 {deleted} 条{tip}'
            + (f'，已备份：{os.path.basename(backup)}' if backup else '（已有备份，未重复备份）'))
    return jsonify({'ok': True, 'deleted': deleted, 'missing': missing,
                    'backup': os.path.basename(backup) if backup else ''})


@app.route('/api/stop', methods=['POST'])
def api_stop():
    STATE['stop'] = True
    return jsonify({'ok': True})


@app.route('/api/status')
def api_status():
    since = int(request.args.get('since', 0))
    with STATE_LOCK:
        logs = STATE['logs']
        new_logs = logs[since:] if since < len(logs) else []
        payload = {
            'running': STATE['running'],
            'phase': STATE['phase'],
            'done': STATE['done'],
            'result_count': STATE['result_count'],
            'output': STATE['output'],
            'rows': list(STATE['rows']),      # 本轮已入库明细，前端每秒刷新用它渲染实时表格
            'logs': new_logs,
            'total_logs': len(logs),
        }
    # 库总数单独查（不持锁、不做迁移导入，避免每秒轮询触发重活）；查不到不影响主流程
    try:
        with closing(db_connect()) as conn:
            payload['db_total'] = conn.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
            payload['db_verified'] = conn.execute(
                'SELECT COUNT(*) FROM customers WHERE score IS NOT NULL').fetchone()[0]
    except Exception:
        payload['db_total'] = None
        payload['db_verified'] = None
    return jsonify(payload)


# 启动端口候选：优先保持原来的 5000，被系统保留/占用就往后面顺延
# ⚠️ Chrome 扩展（extension/ports.js 的 DP_PREFERRED_PORTS）按同一批候选逐个试 /api/ping。
#    改这里就必须改那边，两边都留了指向对方的注释；.workbuddy/_check_ext.py 的 C 组会把
#    「两边是否一致」当成硬断言 —— 一旦漂了，回归会直接红。
PREFERRED_PORTS = (5000, 8000, 8080, 8765, 9000, 7000, 6500, 5800, 5555)


def pick_port(host='127.0.0.1', preferred=PREFERRED_PORTS):
    """挑一个**真正能绑上**的端口，返回 (端口, 换端口的说明)。说明为空 = 首选端口可用。

    ⚠️ 不能把端口写死：Windows 会把**成片**的 TCP 端口保留给 Hyper-V / WinNAT
    （用 `netsh interface ipv4 show excludedportrange protocol=tcp` 可以看到），
    落在保留段里的端口一 bind 就抛 `WSAEACCES(10013)` —— 中文提示是
    「以一种访问权限不允许的方式做了一个访问套接字的尝试。」，而 `netstat` 里
    **看不到任何进程占用**，极易被误判成「端口被别的程序抢了」。
    更要命的是保留段每次开机由 winnat 重新生成、会漂移，所以固定换一个端口只是治标，
    正确做法就是启动时实测一遍。
    """
    reason = ''
    for p in preferred:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((host, p))
            return p, reason
        except OSError as e:
            if not reason:                      # 只记第一个失败的原因，通常就是 5000
                reason = f'{e.strerror}（WinError {e.errno}）'
        finally:
            s.close()
    # 候选全试不通：让系统分配一个空闲端口，记下号再释放（交给 app.run 重新绑）
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, 0))
        return s.getsockname()[1], reason or '候选端口全部不可用'
    finally:
        s.close()


if __name__ == '__main__':
    init_customer_db()
    HOST = '127.0.0.1'
    PORT, PORT_REASON = pick_port(HOST)
    if PORT_REASON:
        print(f'⚠️ 首选端口 {PREFERRED_PORTS[0]} 不能用：{PORT_REASON}')
        print(f'   已自动改用端口 {PORT}。'
              f'（Windows 把成片端口保留给 Hyper-V/WinNAT，属正常现象，不影响使用）')
    # 回填真实端口：/api/ping 会把它告诉 Chrome 扩展（扩展靠它发现该连哪个端口）
    _RUN_PORT = PORT
    url = f'http://{HOST}:{PORT}/'
    print(f'启动本地网页服务：{url}')
    print(f'  手动采集页：{url}manual      页面右上角扩展请连端口 {PORT}')
    print('请在浏览器中打开（若未自动打开请手动访问）')
    webbrowser.open(url)
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
