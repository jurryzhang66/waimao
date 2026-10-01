# -*- coding: utf-8 -*-
"""页面静态检查：确认改动后 PAGE_HTML 结构完好、内嵌 JS 语法正确、新文案就位。
不启动浏览器、不联网。JS 语法用 node --check 校验。"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

SRC = r'D:\waimao\dp\客户开发工具.py'
NODE = r'C:\Users\admin\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)

html = m._build_page()
print('页面长度：', len(html))

# ---- 1. 关键文案就位 ----
expects = [
    '搜到一个就顺手抓它的联系方式（推荐）',
    '搜到一个网站就立刻抓联系方式',
    '本轮新增',
    '搜索中（每搜到一个网站就同步抓联系方式）',
    '按新增个数计',
    '补历史欠账.py',
]
for t in expects:
    assert t in html, f'页面缺少文案：{t}'
    print('  ✓ 文案存在：', t)

# ---- 1b. 实时入库明细表必须就位（后端 rows → 前端 renderRows） ----
live_must = ['liveBody', 'liveCount', 'liveEmpty', 'renderRows(d.rows)', '本轮已入库明细']
for t in live_must:
    assert t in html, f'实时明细表缺少元素/逻辑：{t}'
print('  ✓ 实时入库明细表元素与渲染逻辑就位')
assert 'd.db_total' in html, 'dbCounter 未接入 /api/status 的实时库总数'
print('  ✓ 库总数徽章已改为跟随轮询刷新')

# ---- 1d. 条件词本地化 + 国家筛选参数显示 ----
multi_must = ['curLang', 'countryParams', 'cmb-arg', '条件词语言', 'LANG_CN',
              'tmplMap[lang] || tmplMap.en']
for t in multi_must:
    assert t in html, f'条件词本地化/国家参数显示缺少：{t}'
assert '&gl=' in html, '预览未显示国家筛选参数'
# 后端：每个有角色词的条件都必须备齐 8 种语言；无角色词的 contact 除外
assert all(k in m.COND_ROLES for k, _ in m.CONDITIONS if k != 'contact'), \
    '有条件缺 COND_ROLES 定义'
assert all(len(v) >= 8 for v in m.COND_ROLES.values()), '有条件的语言没备齐 8 种'
assert m.cond_template('wholesale', 'fr') == '{p} (grossiste OR distributeur)'
assert m.cond_template('exhibitor', 'de') == '{p} (Verband OR Ausstellerliste) filetype:pdf'
assert m.cond_template('wholesale', 'fa') == '{p} (wholesaler OR distributor)', '缺语言应回落英文'
assert '""' not in m.cond_template('contact', 'fr'), '条件模板不该再给 {p} 加引号'
print('  ✓ 条件词本地化（8 语言）与国家参数显示逻辑就位')

# ---- 1e. 结果 Excel 统一输出到 output/ 子目录 ----
assert m.OUTPUT_DIRNAME == 'output', '输出子目录名不是 output'
expect_out = os.path.join(os.path.dirname(os.path.abspath(SRC)), 'output')
assert m.output_dir() == expect_out, f'output_dir() 不对：{m.output_dir()}'
assert os.path.isdir(expect_out), 'output 目录不存在（应自动创建）'
assert os.path.dirname(m.ts_result_path('宠物用品', '法国')) == expect_out, \
    'ts_result_path 没把结果写进 output 目录'
assert os.path.dirname(m.ENRICH_FILE or '') == expect_out, \
    f'find_latest_result 没优先扫 output 目录：{m.ENRICH_FILE}'
assert '客户搜索结果_20260928_0118.xlsx' in m.LEGACY_RESULT_FILES, \
    '旧 5 列文件没被排除出「最新结果」候选'
assert len(m._save_enrich_excel.__doc__ or '') and 'output/' in m._save_enrich_excel.__doc__, \
    '_save_enrich_excel 文档没说明输出位置'
print('  ✓ 结果 Excel 统一输出到 output/，旧 5 列文件已排除')

# ---- 1c. 「补全联系方式+评分」按钮必须已彻底移除 ----
for gone in ('btnEnrich', 'api/enrich', '补全联系方式+评分', '补全历史欠账中'):
    assert gone not in html, f'页面仍残留已删除的按钮痕迹：{gone}'
print('  ✓ 补全按钮相关痕迹已全部清除')

# ---- 1f. 数据源切换（谷歌网页搜索 / 谷歌地图） ----
maps_ui = ['name="source"', 'value="google"', 'value="maps"', 'mapsCity', 'mapsCityWrap',
           'mapsNote', 'pagesWrap', 'excludesWrap', 'condMapsHint', 'chinaMapsHint',
           'function onSource', 'function curSource', 'function curCity',
           'function mapsUrlPreview', 'function mapsRoleWord', 'MAPS_CENTERS', 'MAPS_ROLES',
           'RUN_SOURCE']
for t in maps_ui:
    assert t in html, f'数据源切换缺少元素/逻辑：{t}'
# 地图模式下必须把网页搜索专属的东西藏起来
for t in ('excludesWrap\').style.display  = maps',
          'pagesWrap\').style.display     = maps',
          'mapsCityWrap\').style.display  = maps'):
    assert t in html, f'地图模式没有正确切换显示：{t}'
assert "curSource() === 'maps'" in html, 'renderCombos 没有地图分支'
assert 'maps/search/' in html, '预览没有拼出地图搜索 URL'
assert 'https://www.google.com/maps/search/' in html
# 地图必须把身份词拼进查询词（否则只返回餐馆），预览与后端都要有
assert 'mapsRoleWord()' in html, '前端预览没拼身份词'
assert hasattr(m, 'maps_role_word'), '后端缺少 maps_role_word'
assert m.maps_role_word(['wholesale'], 'fr') == 'grossiste', '法语身份词取值不对'
assert m.maps_role_word(['importer'], 'fr') == 'importateur'
assert m.maps_role_word([], 'fr') == '', '没勾条件时不该有身份词'
assert m.maps_role_word(['wholesale'], 'fa') == 'wholesaler', '缺语言应回落英文'
print('  ✓ 数据源单选、城市输入框、地图模式切换、身份词拼接与地图预览就位')

# 后端：地图链路的函数与常量必须齐备
for fn in ('run_maps', 'maps_open', 'maps_feed_scroll', 'maps_cards', 'maps_detail',
           'maps_consent_wall', 'maps_reached_end', 'maps_search_url', 'maps_place_key',
           'db_has_customer'):
    assert hasattr(m, fn), f'后端缺少地图函数：{fn}'
assert len(m.COUNTRY_CENTERS) == len(m.COUNTRIES), '有国家没配地图中心坐标'
assert all(len(c) == 4 for c in m.COUNTRIES), 'COUNTRIES 元组长度被改坏了'
assert 'div[role="feed"]' in m.MAPS_FEED_CSS
assert 'phone:tel:' in ' '.join(m.MAPS_DETAIL_READY), '详情面板缺少电话选择器'
assert 'authority' in ' '.join(m.MAPS_DETAIL_READY), '详情面板缺少官网选择器'
assert len(m.MAPS_END_HINTS) >= 4, '列表末尾提示没备多语言'
# run_search 必须一行没动（网页搜索链路不能被地图改动波及）
import inspect as _inspect
_sig = str(_inspect.signature(m.run_search))
assert _sig.startswith('(products, cond_keys, countries, pages'), f'run_search 签名被改了：{_sig}'
assert str(_inspect.signature(m.run_maps)) == \
    "(products, cond_keys, countries, city='', target_count=10, industry='', " \
    "auto_enrich=True, lang='', china_filters=None)"
print('  ✓ 后端地图函数齐备；run_search 签名未变（网页搜索链路不受影响）')

# ---- 2. 占位符必须已被替换 ----
for ph in ('CONDS_PLACEHOLDER', 'COUNTS_PLACEHOLDER', 'EXCLS_PLACEHOLDER',
           'CHINA_FILTERS_PLACEHOLDER', 'MAPS_CENTERS_PLACEHOLDER', 'MAPS_ROLES_PLACEHOLDER'):
    assert ph not in html, f'占位符未替换：{ph}'
print('  ✓ 六个占位符均已替换')

# ---- 3. 内嵌 JS 语法检查 ----
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
print(f'  找到 {len(scripts)} 段内嵌 JS')
for i, js in enumerate(scripts, 1):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(js)
        tmp = f.name
    r = subprocess.run([NODE, '--check', tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if r.returncode != 0:
        print(f'  ✗ 第 {i} 段 JS 语法错误：\n{r.stderr[:800]}')
        sys.exit(1)
    print(f'  ✓ 第 {i} 段 JS 语法 OK')

# ---- 4. 标签配对检查 ----
VOID = {'br', 'img', 'input', 'meta', 'link', 'hr', 'source', 'area', 'base', 'col'}


class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errs = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errs.append(f'多余闭合标签 </{tag}>')
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errs.append(f'标签错配：期望 </{self.stack[-1]}>，实际 </{tag}>')
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass


c = Checker()
c.feed(html)
if c.errs:
    print('  ✗ 标签问题：')
    for e in c.errs[:10]:
        print('     ', e)
    sys.exit(1)
print(f'  ✓ 标签配对正常（未闭合栈：{c.stack}）')

# ---- 5. 启动端口必须自动避让（Windows 会把成片端口保留给 Hyper-V/WinNAT） ----
assert hasattr(m, 'pick_port'), '缺少 pick_port（端口写死会在被保留的端口上直接启动失败）'
assert m.PREFERRED_PORTS[0] == 5000, '首选端口应仍是 5000（能用就沿用）'
assert len(set(m.PREFERRED_PORTS)) == len(m.PREFERRED_PORTS) >= 5, '候选端口应有至少 5 个且不重复'
_src = open(SRC, encoding='utf-8').read()
_main = _src[_src.index("if __name__ == '__main__':"):]
assert 'port=PORT' in _main and 'port=5000' not in _main, '__main__ 里端口又被写死了'
assert 'pick_port(' in _main, '__main__ 没调用 pick_port'
print('  ✓ 启动端口自动避让就位（_check_startup.py 做真机 e2e 验证）')

# ================= 6. 拆包防护断言（阶段 A：入口 + core/ 包） =================
# 这几条守的是「会静默出错、不报错」的坑：算错程序根 → 悄悄换成空库；
# 打桩失效 → 假数据进真实库；ENRICH_FILE 变成快照 → 外部脚本读到旧路径。
_root = os.path.dirname(os.path.abspath(SRC))

# --- R1 程序根必须还是 <root>（不能是 <root>/core，否则等于换了一个空数据库）---
assert m.output_dir() == os.path.join(_root, 'output'), f'_app_dir/output_dir 算错：{m.output_dir()}'
assert m.db_path() == os.path.join(_root, 'DB', '客户库.sqlite3'), f'db_path 算错：{m.db_path()}'
assert not os.path.exists(os.path.join(_root, 'core', 'DB')), 'core/ 下出现 DB/：_app_dir 算错'
assert not os.path.exists(os.path.join(_root, 'core', 'output')), 'core/ 下出现 output/：_app_dir 算错'
assert os.path.exists(os.path.join(_root, 'ui', 'page.html')), '缺少 ui/page.html'
print('  ✓ R1 程序根正确：output/ 与 DB/ 仍在项目根，core/ 下没被带出副本')

# --- R2/R7/R8 单例性：入口拿到的必须是子模块里那个对象，不能是副本 ---
import core as _co
import core.db as _cdb
import core.paths as _cp
import core.state as _cs

assert os.path.abspath(_co.__file__).startswith(_root + os.sep), \
    f'导入到的 core 不是本项目：{_co.__file__}'
assert m.db is _cdb and m.paths is _cp
assert m.db_path is _cdb.db_path and m.db.db_path is _cdb.db_path, 'db_path 被复制'
assert m.STATE is _cs.STATE and m.STATE_LOCK is _cs.STATE_LOCK, 'STATE/STATE_LOCK 被复制'
assert m.log is _cs.log, 'log 被复制（core.db.init_customer_db 调的是 core.state.log）'
assert m.CONDITIONS is _co.config.CONDITIONS, 'CONDITIONS 不是 core.config 里的那个对象'
assert m.PREFERRED_PORTS is not None
print('  ✓ R2 单例性正确：db/paths/state 均为同一对象（打桩 m.db.db_path 能打到 core.db 内部）')

# --- R3 ENRICH_FILE 必须是「活转发」，不是 import 那一刻的快照 ---
assert 'ENRICH_FILE' not in vars(m), \
    '入口把 ENRICH_FILE 变成了模块级名字（赋值或 from ... import），__getattr__ 转发永久失效'
_o = _cp.ENRICH_FILE
try:
    _cp.ENRICH_FILE = _o + '.probe'
    assert m.ENRICH_FILE == _o + '.probe', '入口没有动态转发 core.paths.ENRICH_FILE'
    assert m.ENRICH_FILE is not None
finally:
    _cp.ENRICH_FILE = _o
assert m.ENRICH_FILE == _o, '恢复 ENRICH_FILE 失败'
# vars(m) 里没有这个名字，就已经证明入口既没做模块级赋值、也没直接 import 它
# （两种情况都会把名字写进模块字典，__getattr__ 便永久失效）。
_src3 = open(SRC, encoding='utf-8').read()
assert 'paths.ENRICH_FILE' in _src3, '入口内部没有改用 paths.ENRICH_FILE（裸名会 NameError）'
print('  ✓ R3 ENRICH_FILE 活转发正常（补历史欠账.py 读 kf.ENRICH_FILE 拿到的是最新值）')

# --- R4 入口不得残留任何已搬迁的定义 ---
# ⚠️ 必须用 ast 走真正的模块级语句，不能拿 `'def log(' in 源码` 硬扫：
#    `__getattr__` 的 docstring 里就写着 `ENRICH_FILE = ...` 作反例说明，纯文本扫描会误报。
import ast
_src2 = open(SRC, encoding='utf-8').read()
_tree = ast.parse(_src2)

# 搬进 core/* 的函数：入口里不允许再出现同名 def
_banned_defs = {
    'cond_template', '_app_dir', 'output_dir', '_safe_name_part', 'build_result_name',
    'ts_result_path', '_result_time_key', 'find_latest_result', 'db_path', 'maps_place_key',
    'normalize_domain', 'normalize_email', 'db_connect', 'init_customer_db',
    'db_upsert_customer', 'db_stats', 'log', '_build_page', '_read_page_template',
}
# 搬进 core/* 的常量/状态：入口里不允许再出现模块级赋值（只能用 import 拿）
_banned_assign = {
    'CONDITIONS', 'COND_TEMPLATE', 'COND_ROLES', 'COND_LANGS', 'KEYWORD_LIB', 'COUNTRIES',
    'COUNTRY_CENTERS', 'MAPS_CENTER_DEFAULT', 'EXCLUDE_OPTIONS', 'EXCLUDE_DEFAULT',
    'CHINA_FILTER_OPTIONS', 'CHINA_FILTER_DEFAULTS', 'BLOCK_DOMAINS', 'BLOCK_SUBSTR',
    'SEARCH_ENGINE_PREFIX', 'LEGACY_RESULT_FILES', 'RESULT_DATE_RE', 'OUTPUT_DIRNAME',
    'MAPS_PLACE_ID_RE', 'DB_DIR', 'DB_FILE', 'BASE_TOKEN', 'TABLE_ID', 'LARK_CLI',
    'IMPORT_JSON', 'COUNTRY_STANDARD', 'STATE', 'STATE_LOCK', 'log', 'PAGE_HTML',
    'ENRICH_FILE',
}
_left = []
for _node in _tree.body:                       # 只看模块级
    if isinstance(_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _node.name in _banned_defs:
        _left.append(f'def {_node.name}')
    if isinstance(_node, ast.Assign):
        for _t in _node.targets:
            if isinstance(_t, ast.Name) and _t.id in _banned_assign:
                _left.append(f'{_t.id} =')
    if isinstance(_node, ast.AnnAssign) and isinstance(_node.target, ast.Name) \
            and _node.target.id in _banned_assign:
        _left.append(f'{_node.target.id} :')
    if isinstance(_node, ast.ImportFrom):
        for _a in _node.names:
            # ENRICH_FILE 是被重新赋值的活值，import 只会拿到快照（STATE 等是允许 re-export 的）
            if _a.name == 'ENRICH_FILE':
                _left.append(f'from {_node.module} import ENRICH_FILE')
assert not _left, f'入口仍残留已搬迁的定义：{_left}'
# 插件式 glue 必须在位
for _need in ('from core.ui import PAGE_HTML, _build_page', 'from core import db',
              'from core import paths', 'paths.ENRICH_FILE', '_app_dir()'):
    assert _need in _src2, f'入口缺少拆包 glue：{_need}'
print('  ✓ R4 入口已无任何已搬迁的模块级定义（AST 扫描 19 个函数 + 30 个常量）')

# --- R5 模板与构建结果哈希必须与基线一致（防误格式化 / 转义静默变形）---
# ⚠️ 基线在 V1.5 推进过一次：主页顶栏加了「手动采集页 / 客户库查询」两个导航链接。
#    那是**故意**改的；以后凡是故意动 page.html，下面两个字面量必须**一起**重算（漏一个就红）。
#    这条断言剩余的价值 = 「哪次误格式化/误翻译把模板改变形，立刻能被抓到」。
#    ⛔ 如果只是改了别的东西却发现这里红：先看 diff，别顺手把基线改掉。
_TMPL_SHA = 'f90082ea1d375eaec7dcef1c187d7f73ded020e4d5bfd3d21954e45796e9478d'
_BUILT_SHA = '563818c65670d8a38a2606d0e2bec20a19757551b70b2e8e6f7cffe1f69b0e11'
import hashlib as _hl
_raw = open(os.path.join(_root, 'ui', 'page.html'), encoding='utf-8').read()
assert _hl.sha256(_raw.encode('utf-8')).hexdigest() == _TMPL_SHA, \
    'ui/page.html 与基线不一致（可能被误格式化，转义会静默变形；若是故意改的，' \
    '就把本节的 _TMPL_SHA 与 _BUILT_SHA 一起重算）'
assert _hl.sha256(m._build_page().encode('utf-8')).hexdigest() == _BUILT_SHA, \
    '构建后页面与基线不一致（动了模板却忘了重算 _BUILT_SHA？）'
print('  ✓ R5 模板与构建结果哈希均与基线一致（转义没被破坏）')

# --- R6 页面必须是已构建的成品 ---
assert m.PAGE_HTML == m._build_page()
assert 'PLACEHOLDER' not in m.PAGE_HTML
# 主页顶栏的两个导航（V1.5 加）：href 写错/被删掉**不会**有任何运行时报错，只会静默少个入口。
# （两个路由自身的注册分别由 R7 / R9 断言，这里只管主页确实指过去了。）
for _href in ('/manual', '/db'):
    assert f'href="{_href}"' in m.PAGE_HTML, f'主页缺少指向 {_href} 的导航链接'
assert 'class="nav-a"' in m.PAGE_HTML and '.nav-a' in m.PAGE_HTML, \
    '主页导航的样式类 .nav-a 不在页面上（导航会退化成一条带下划线的裸链接）'
# 模板缺文件必须显式报错（带绝对路径），而不是静默发出空页面
import core.ui as _cu
assert os.path.isabs(_cu._PAGE_TEMPLATE_PATH), '模板路径不是绝对路径'
try:
    _save = _cu._PAGE_TEMPLATE_PATH
    _cu._PAGE_TEMPLATE_PATH = os.path.join(_root, 'ui', '__不存在__.html')
    try:
        _cu._read_page_template()
        raise AssertionError('模板缺失时没有报错')
    except RuntimeError as e:
        assert '__不存在__.html' in str(e), '报错信息里没有给出出错的绝对路径'
finally:
    _cu._PAGE_TEMPLATE_PATH = _save
print('  ✓ R6 页面为已构建成品；模板缺失会显式报错（带绝对路径）')

# --- R7 第二个页面（手动采集 /manual）---
# ⚠️ 设计成「副页面用 PAGE_CSS_PLACEHOLDER 复用 page.html 的 <style> 块」→ 公共样式只维护一份。
#    所以加/改本页**不影响** R5 的基线（R5 只管 page.html 自身）。
assert m.MANUAL_HTML == m._build_manual_page(), 'MANUAL_HTML 不是 _build_manual_page() 的成品'
assert 'PLACEHOLDER' not in m.MANUAL_HTML, 'MANUAL_HTML 里有占位符没被替换'
assert os.path.isabs(_cu._MANUAL_TEMPLATE_PATH), 'manual 模板路径不是绝对路径'
# 共享样式确实注入了（抽查两个只出现在 page.html 样式块里的 class）
assert '.btn-start' in m.MANUAL_HTML and 'table.live' in m.MANUAL_HTML, \
    'manual 页没拿到 page.html 注入的共享样式'
# 页面该有的四张卡与关键 id 都在
for _need in ('id="heart"', 'id="urls"', 'id="pwords"', 'id="industry"', 'id="upgrade"',
              'id="log"', 'id="bar"', 'id="mcounter"',
              # ③ 本轮采集明细（2026-09-29 由「最近采集记录」改成实时明细）
              'id="sessionBody"', 'id="sessionCount"', 'id="sessionEmpty"',
              'id="sessionStatus"', 'id="sessionFile"',
              'id="btnSessionStart"', 'id="btnSessionFinish"'):
    assert _need in m.MANUAL_HTML, f'手动采集页缺少 {_need}'
assert 'recentBody' not in m.MANUAL_HTML, '旧的「最近采集记录」表应该已被本轮明细取代'
assert 'id="btnSessionStart"' in m.MANUAL_HTML and '开始本轮采集' in m.MANUAL_HTML, \
    '本轮会话的「开始」入口不在页面上'
assert 'sessionStart' in m.MANUAL_HTML and 'sessionFinish' in m.MANUAL_HTML, \
    '本轮会话的两个 JS 入口不在页面上'
# 本轮明细每行的 ✕ 删除。⚠️ 必须挂在 #sessionBody 上做**事件委托**：行是 innerHTML 拼好再
# appendChild 的，且换轮 / 行数变少时都会把 tbody 清空重画 —— 逐行绑监听会随行一起丢。
assert 'class="row-del"' in m.MANUAL_HTML, '本轮明细的删除按钮不在页面上'
assert 'data-rid' in m.MANUAL_HTML, '删除按钮没带 data-rid（删除靠行号，不能按 url）'
assert 'onSessionBodyClick' in m.MANUAL_HTML and 'deleteSessionRow' in m.MANUAL_HTML, \
    '删除单条的 JS 入口不在页面上'
assert '/api/manual/session/delete' in m.MANUAL_HTML, '页面没打删除接口'
assert "getElementById('sessionBody').addEventListener('click'" in m.MANUAL_HTML, \
    '删除没做事件委托（应挂在 #sessionBody 上）'
# 删除按钮的样式写在本页自带的第二个 <style> 里：公共样式统一从 page.html 注入，
# 本页专有的样式别混进那一份（混进去会顺带影响 / 与 /manual 两页）
assert '.row-del' in m.MANUAL_HTML, '删除按钮的样式没写进 manual 页自己的 <style>'
# 计数口径必须拆开报：「已采 N 条」＝ 新增 + 已在库，而结果 Excel **只写「新增」**。
# 只报一个数，就是用户最容易误判成「表漏写了」的地方（实测踩过：已采 17 条、表里 13 行）。
for _need in ('function breakdownText(', 'function roundTally(',
              "'新增 ' + (st.added || 0) + ' · 已在库 ' + (st.existed || 0)",
              "'已采 ' + n + ' 条 = 新增 '",
              '只写「新增」的 ',
              'renderSession(st.session_rows, st)'):
    assert _need in m.MANUAL_HTML, f'计数口径拆分的实现不在页面上：{_need}'
# 路由已注册
assert 'manual_page' in m.app.view_functions, '/manual 路由没注册'
# share 的行业下拉必须是动态取的，不能在页面里再硬编码一份行业枚举
for _ind in ('塑料包装袋', '宠物用品', '机械零部件'):
    assert _ind not in m.MANUAL_HTML, \
        f'手动采集页硬编码了行业名「{_ind}」——应从 /api/keywords 动态生成'
# manual 模板缺文件同样要显式报错
try:
    _save_m = _cu._MANUAL_TEMPLATE_PATH
    _cu._MANUAL_TEMPLATE_PATH = os.path.join(_root, 'ui', '__不存在__.html')
    try:
        _cu._read_manual_template()
        raise AssertionError('manual 模板缺失时没有报错')
    except RuntimeError as e:
        assert '__不存在__.html' in str(e), 'manual 模板报错信息里没有绝对路径'
finally:
    _cu._MANUAL_TEMPLATE_PATH = _save_m
print('  ✓ R7 手动采集页 /manual：成品、共享样式已注入、四张卡齐全、行业枚举未硬编码、每行 ✕ 删除就位')

# --- R9 第三个页面（客户库查询 /db）---
# 与 /manual 同一套设计：用 PAGE_CSS_PLACEHOLDER 复用 page.html 的 <style> 块
# → 加/改本页同样不动 R5 的基线。
assert m.QUERY_HTML == m._build_query_page(), 'QUERY_HTML 不是 _build_query_page() 的成品'
assert 'PLACEHOLDER' not in m.QUERY_HTML, 'QUERY_HTML 里有占位符没被替换'
assert os.path.isabs(_cu._QUERY_TEMPLATE_PATH), 'query 模板路径不是绝对路径'
assert '.btn-start' in m.QUERY_HTML and 'table.live' in m.QUERY_HTML, \
    '查询页没拿到 page.html 注入的共享样式'
# 两张卡与关键控件都在
for _need in ('id="facetGrid"', 'id="resBody"', 'id="resCount"', 'id="resEmpty"',
              'id="resStatus"', 'id="pageInfo"', 'id="resNote"',
              'id="kw"', 'id="order"', 'id="pagesize"', 'id="scoreMin"', 'id="scoreMax"',
              'id="contact"', 'id="seenAfter"', 'id="seenBefore"',
              'id="btnQuery"', 'id="btnExport"', 'id="btnReset"', 'id="btnOpen"',
              'id="btnPrev"', 'id="btnNext"', 'id="log"'):
    assert _need in m.QUERY_HTML, f'客户库查询页缺少 {_need}'
for _fn in ('function collect(', 'function runQuery(', 'function renderResult(',
            'function loadFacets(', 'function doExport(', 'function resetForm('):
    assert _fn in m.QUERY_HTML, f'查询页缺少逻辑函数：{_fn}'
assert '/api/db/facets' in m.QUERY_HTML and '/api/db/query' in m.QUERY_HTML \
    and '/api/db/export' in m.QUERY_HTML and '/api/db/open_folder' in m.QUERY_HTML, \
    '查询页没打开全部新接口'
# ⚠️⚠️ 前端 JS 里那个「未填写」哨兵值必须与后端 core.db.QUERY_EMPTY 一字不差。
#    写错不会报错，只会让「勾了未填写却筛不出任何东西」——最典型的静默失效。
assert f"const EMPTY = '{m.db.QUERY_EMPTY}'" in m.QUERY_HTML, \
    '查询页的 EMPTY 哨兵值与 core.db.QUERY_EMPTY 不一致（「未填写」筛选会静默失效）'
# 行业/国家/来源/评级 必须全部由接口动态生成，页面里不许出现行业名（库里还有历史行业名）
for _ind in ('塑料包装袋', '宠物用品', '家具家居', 'LED照明'):
    assert _ind not in m.QUERY_HTML, \
        f'客户库查询页硬编码了行业名「{_ind}」——应从 /api/db/facets 动态生成'
assert 'QUERY_ORDER_SQL' not in m.QUERY_HTML, '排序白名单是后端的事，不该出现在页面里'
# 导出列是**另一套**契约（14 列客户库全字段），不能误用结果 Excel 的 10 列硬契约
assert len(m.QUERY_EXPORT_COLUMNS) == 14, f'查询导出应 14 列，实际 {len(m.QUERY_EXPORT_COLUMNS)}'
assert m.QUERY_EXPORT_COLUMNS[0][1] == '公司名称', '查询导出首列应是「公司名称」'
assert '行业' in [t for _, t in m.QUERY_EXPORT_COLUMNS] \
    and '来源渠道' in [t for _, t in m.QUERY_EXPORT_COLUMNS], \
    '查询导出应带行业与来源渠道（这是它与结果 Excel 10 列契约的区别）'
assert len(m.EXCEL_HEADER_10) == 10, '结果 Excel 的 10 列硬契约被改坏了'
# 路由已注册
assert 'query_page' in m.app.view_functions, '/db 路由没注册'
for _api in ('api_db_facets', 'api_db_query', 'api_db_export', 'api_db_download', 'api_db_open_folder'):
    assert _api in m.app.view_functions, f'查询接口没注册：{_api}'
# ⚠️ 导出必须落 output/查询导出/**子目录**：落 output/ 根下会被 find_latest_result()
#    选中当「最新结果文件」，把飞书导出的目标劫持到一份查询表上。
assert m.QUERY_EXPORT_DIRNAME == '查询导出', '查询导出子目录名被改了'
assert os.path.basename(m.query_export_dir()) == '查询导出', 'query_export_dir 不在 output 子目录下'
assert os.path.dirname(m.query_export_dir()) == m.output_dir(), \
    '查询导出目录必须是 output/ 的直接子目录（否则可能被 find_latest_result 扫到）'
assert '查询导出' in m.ts_query_export_path(1), '查询导出文件名没带标识'
# query 模板缺文件同样要显式报错
try:
    _save_q = _cu._QUERY_TEMPLATE_PATH
    _cu._QUERY_TEMPLATE_PATH = os.path.join(_root, 'ui', '__不存在__.html')
    try:
        _cu._read_query_template()
        raise AssertionError('query 模板缺失时没有报错')
    except RuntimeError as e:
        assert '__不存在__.html' in str(e), 'query 模板报错信息里没有绝对路径'
finally:
    _cu._QUERY_TEMPLATE_PATH = _save_q
print('  ✓ R9 客户库查询页 /db：成品、共享样式已注入、控件齐全、行业枚举未硬编码、'
      '哨兵值与后端一致、导出落 output/查询导出/ 子目录')

print('  ✓ 拆包防护断言全部通过（程序根 / 单例 / 动态 ENRICH_FILE / 残留定义 / 模板哈希 / 第二页 R7 / 第三页 R9）')

print('\n✅ 页面静态检查通过')
