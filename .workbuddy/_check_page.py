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


def _find_node():
    """定位 managed node.exe。

    ⛔ 别把版本号写死：本机从 22.22.2-3 升到 22.22.2-6 时，写死的路径直接
    FileNotFoundError —— 看着像「回归红了」，其实是环境漂移的假红。
    取 versions/ 下最新的一个（版本号字典序即可），末位才退回旧写死路径。
    """
    base = os.path.join(os.environ.get('USERPROFILE') or r'C:\Users\admin',
                        '.workbuddy', 'binaries', 'node', 'versions')
    try:
        for d in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, d, 'node.exe')
            if os.path.isfile(p):
                return p
    except OSError:
        pass
    return r'C:\Users\admin\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'


NODE = _find_node()

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
assert m.cond_template('buyer', 'en') == '{p} (buyer OR procurement OR purchasing OR sourcing)'
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
           'CHINA_FILTERS_PLACEHOLDER', 'MAPS_CENTERS_PLACEHOLDER', 'MAPS_ROLES_PLACEHOLDER',
           'COUNTRY_LIMITS_PLACEHOLDER'):
    assert ph not in html, f'占位符未替换：{ph}'
print('  ✓ 七个占位符均已替换')

# ---- 2b. 第 5 项关键词组合的 Google 语义 ----
assert "pwords.length > 1 ? '(' + joined + ')' : joined" in html, \
    '前端多产品 OR 没有整体加括号'
assert m.COND_TEMPLATE.get('buyer') == '{p} ({role})', 'buyer 条件模板缺失'
assert '客户发现' in html and '辅助线索' in html, \
    '预览缺少条件用途分类'
print('  ✓ buyer 条件、多产品 OR 括号与用途分类就位')

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
# ⚠️ 基线在 V1.5 推进过六次：① 主页顶栏加了「手动采集页 / 客户库查询」两个导航链接；
#    ② 主页加「7. 自定义搜索词」卡片（自定义查询：原样搜、不套条件模板、不做中国过滤）；
#    ③ 主页第 5 步加「国家限定」四选一（none 默认 / cr / site / both）；
#    ④ 主页「本轮已入库明细（实时）」加逐行删除（第 7 列 ✕ + #liveDelModal 居中模态框 +
#       livedel-* 样式，见 R12）；
#    ⑤ 把「本次任务采集数量」从第 5 步（参数）提成「1.」独立卡并改成强必填，原 1~6 号全部 +1（见 R13）；
#    ⑥ 把「本轮明细」表抽成共享组件 ui/live-table.js（与 /manual ③ 同一份）：主页表 +2 列「行业/国家」、
#       模态框标记从页面搬进组件的运行时构建、页面新增一行 <script>LIVE_TABLE_JS_PLACEHOLDER</script>。
#    ⑦ ui/live-table.js 支持 cfg.badgeText（/manual 徽章改报「有效 X / 共 Y」两组数）—— 模板没动，
#       但组件正文被注入到构建结果里 → **只有 _BUILT_SHA 变，_TMPL_SHA 不变**（这正说明两个哈希各管一半）。
#    ⑧ ui/live-table.js 的「邮箱」列多邮箱分隔符 ' / ' → ', '（用户要求，全链路统一成逗号；电话不变）
#       —— 同样只动组件正文，**只有 _BUILT_SHA 变**。
#    那八次都是**故意**改的；以后凡是故意动 page.html 或 ui/live-table.js，下面两个字面量必须**一起**重算（漏一个就红）。
#    这条断言剩余的价值 = 「哪次误格式化/误翻译把模板改变形，立刻能被抓到」。
#    ⛔ 如果只是改了别的东西却发现这里红：先看 diff，别顺手把基线改掉。
_TMPL_SHA = '569c5fd836c67a5b0044afe99082a85986ff1326b9b0925d95d7fe22d0d99d77'
_BUILT_SHA = '6f5a45bcaa1de3756b3f06c96d5a6dff52389bd6c087e775e9b0eae3fdf344aa'
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
assert 'class="livedel-btn"' in m.MANUAL_HTML, '本轮明细的删除按钮不在页面上'
assert 'data-rid' in m.MANUAL_HTML, '删除按钮没带 data-rid（删除靠行号，不能按 url）'
assert 'onSessionBodyClick' in m.MANUAL_HTML and 'deleteSessionRow' in m.MANUAL_HTML, \
    '删除单条的 JS 入口不在页面上'
assert '/api/manual/session/delete' in m.MANUAL_HTML, '页面没打删除接口'
assert "getElementById('sessionBody').addEventListener('click'" in m.MANUAL_HTML, \
    '删除没做事件委托（应挂在 #sessionBody 上）'
# 删除按钮与居中确认框的样式现在来自**共享块**（page.html 的第一个 <style>，由 _page_style()
# 注入本页）—— 与主页那张表是同一套，本页不再自带一份。
# ⚠️ 下面前两条是「这一页真的接上了共享组件」的证据：行模板与确认框都不在本页了，
#    本页只留 renderSession / onSessionBodyClick / deleteSessionRow 三个入口（见 ui/live-table.js）。
assert '.livedel-btn' in m.MANUAL_HTML, '删除按钮的样式没注入到 manual 页（共享块丢了？）'
assert 'makeLiveTable' in m.MANUAL_HTML and 'function renderSession(rows, st)' in m.MANUAL_HTML, \
    'manual 页没接上「本轮明细」共享组件 ui/live-table.js'
assert 'class="row-del"' not in m.MANUAL_HTML, \
    'manual 页还在自己拼删除按钮 —— 现已统一用共享组件的 livedel-btn'
# 本页原来那套 live-del / row-del 样式名要清干净：留着就是死规则，且下次有人照着它写会再撞一次名
# 计数口径必须报**两组数**：「有效数」＝新增（＝结果 Excel 行数），「采集总数」＝明细行数
# （＝新增 + 已在库）。只报一个「已采 N 条」＝总数，会把重复的也算成成功数（用户点名要改）。
for _need in ('function liveBadgeText(', 'function breakdownText(', 'function roundTally(',
              "'有效 ' + (st.added || 0) + ' · 采集总数 ' + n",
              "'有效 ' + a + ' 条 / 采集总数 ' + n + ' 条 = 新增 '",
              '只写「有效（新增）」的 ',
              'badgeText: function(st, n){ return liveBadgeText(st, n); }',
              'renderSession(st.session_rows, st)'):
    assert _need in m.MANUAL_HTML, f'计数口径（有效数 / 采集总数）的实现不在页面上：{_need}'
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
              'id="btnPrev"', 'id="btnNext"', 'id="log"',
              # 结果表的删除：全选框 + 批量删按钮（单行 ✕ 与勾选框是每行动态渲染的，见下）
              'id="ckAll"', 'id="btnDelSel"'):
    assert _need in m.QUERY_HTML, f'客户库查询页缺少 {_need}'
for _fn in ('function collect(', 'function runQuery(', 'function renderResult(',
            'function loadFacets(', 'function doExport(', 'function resetForm(',
            'function selectedIds(', 'function syncSel(', 'function toggleAll(',
            'function onResBodyClick(', 'function deleteRows('):
    assert _fn in m.QUERY_HTML, f'查询页缺少逻辑函数：{_fn}'
assert '/api/db/facets' in m.QUERY_HTML and '/api/db/query' in m.QUERY_HTML \
    and '/api/db/export' in m.QUERY_HTML and '/api/db/open_folder' in m.QUERY_HTML \
    and '/api/db/delete' in m.QUERY_HTML, \
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
for _api in ('api_db_facets', 'api_db_query', 'api_db_export', 'api_db_download',
             'api_db_open_folder', 'api_db_delete'):
    assert _api in m.app.view_functions, f'查询接口没注册：{_api}'

# --- 结果删除（勾选批量 / 每行 ✕）---
# 每行两个入口都是**动态渲染**的：勾选框与 ✕ 都带 data-id，且删的是主键而不是网址
# （按主键无歧义，不会像按键删那样删到同键的另一条）。
for _need in ('class="row-ck"', 'class="row-del"', 'data-id',
              "getElementById('resBody').addEventListener('click'",
              "getElementById('resBody').addEventListener('change'"):
    assert _need in m.QUERY_HTML, f'查询页缺少删除相关实现：{_need}'
# ⚠️ 事件**委托**必须挂在 #resBody 上：行是 innerHTML 整表重画的，逐行绑监听会随行一起丢
assert 'closest(\'.row-del\')' in m.QUERY_HTML, '单行 ✕ 没做事件委托（应挂 #resBody）'
# 样式只能进本页自带的第二个 <style>（page.html 那份会被注入到全部三页）
assert '.row-del' in m.QUERY_HTML and '.btn-del' in m.QUERY_HTML, \
    '删除相关样式没写进查询页自己的 <style>'
assert m.QUERY_DELETE_MAX == 500, f'单次批量删除上限被改了：{m.QUERY_DELETE_MAX}'
# 二次确认必须是**页面自己的居中模态框**：原生 confirm() 弹在浏览器窗口顶部、样式不可控，
# 用户明确要求把它挪到屏幕中间。所以这里同时钉住「有模态框」与「没有原生 confirm」。
for _need in ('id="delModal"', 'id="delModalTitle"', 'id="delModalBody"',
              'id="delModalOk"', 'id="delModalCancel"',
              'function askDeleteConfirm(', 'function closeDeleteConfirm(',
              "getElementById('delModalOk').addEventListener('click'",
              "getElementById('delModalCancel').addEventListener('click'",
              "getElementById('delModal').addEventListener('click'",
              "e.key === 'Escape'", "e.key === 'Enter'"):
    assert _need in m.QUERY_HTML, f'删除确认模态框缺少实现：{_need}'
assert '#delModal { position:fixed; inset:0' in m.QUERY_HTML \
    and '#delModal.show { display:flex; }' in m.QUERY_HTML, \
    '模态框样式没写进查询页自己的 <style>，或不是「fixed 全屏 + flex 居中」'
# ⛔ 不许再用原生 confirm()。注意 askDeleteConfirm( / closeDeleteConfirm( 里的是大写 C，
#    不会误命中这个小写子串断言。
assert 'confirm(' not in m.QUERY_HTML, \
    '查询页里还有原生 confirm()（贴浏览器顶部、位置样式都改不了，应走页面自己的居中模态框）'
# ⚠️⚠️ 两条继承来的硬纪律，都用源码级断言钉住（这类失误没有任何运行时报错）：
#   ① 必须按主键批量删 + 删前备份；② 全程不许持 STATE_LOCK
#      —— 那把锁非可重入，而 backup_db_before_delete() 内部会调 log()（log 自己也要抢它），
#      持锁调用必死锁（历史上踩过两次）。
# ⚠️ 用 AST 只取**标识符**，不拿源码做子串匹配：这几个名字在 docstring 里也出现过
#    （说明性文字），按子串匹配的话「调用被删了、注释还在」这种回归会被漏掉。
import ast as _ast
import inspect as _insp
_tree_del = _ast.parse(_insp.getsource(m.api_db_delete))
_ids_del = {n.id for n in _ast.walk(_tree_del) if isinstance(n, _ast.Name)}
_ids_del |= {n.attr for n in _ast.walk(_tree_del) if isinstance(n, _ast.Attribute)}
assert 'db_delete_customers_by_ids' in _ids_del, \
    '删除接口没有按主键删（应走 db_delete_customers_by_ids，而不是按 website_key）'
assert 'backup_db_before_delete' in _ids_del, '删除接口没做删前备份'
assert 'STATE_LOCK' not in _ids_del, \
    '删除接口持了 STATE_LOCK —— backup_db_before_delete() 内部的 log() 也抢它，非可重入会死锁'
assert hasattr(m.db, 'db_delete_customers_by_ids'), 'core/db.py 没导出按主键批量删的函数'
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
      '哨兵值与后端一致、导出落 output/查询导出/ 子目录、勾选/✕ 双入口删除就位')

# --- R10 主页「7. 自定义搜索词」（原样搜 / 与标准模式互斥 / 不做中国过滤）---
# 这一卡的价值全压在两条约定上：① 搜索词**一个字符都不加**；② 它与标准模式互斥。
# 两条都是**静默失效**型 —— 写错了不会有任何运行时报错，只会悄悄拼上排除词、或悄悄整卡不生效。
import ast as _ast2
import inspect as _insp2
for _need in ('id="rawCard"', 'id="rawQueries"', 'id="rawMapsHint"',
              'function rawQueries()', 'custom_queries: raws'):
    assert _need in m.PAGE_HTML, f'主页缺少自定义搜索词实现：{_need}'
# 自定义词只服务谷歌网页搜索：切到地图模式必须置灰（否则用户会以为地图也在用它）
assert "getElementById('rawQueries').disabled" in m.PAGE_HTML, \
    '切到地图模式时没有把自定义搜索词置灰'
# 预览与实搜必须一致：预览里也要走「原样」分支，否则用户照预览抄下来的词与实际发出去的不符
assert '条自定义查询（原样搜索，不拼任何词）' in m.PAGE_HTML, \
    '组合预览没有自定义查询分支（预览与实搜会不一致）'
assert m.RAW_QUERY_MAX == 20, f'自定义搜索词单轮上限被改了：{m.RAW_QUERY_MAX}'
# ⚠️ 同样只用 AST 取标识符/字符串常量，不做源码子串匹配（docstring 里同名会造成假绿）。
#    注意 'custom_queries' 是 JSON 键 → 落在 ast.Constant 里，不在 ast.Name 里。
_tree_start = _ast2.parse(_insp2.getsource(m.api_start))
_names_start = {n.id for n in _ast2.walk(_tree_start) if isinstance(n, _ast2.Name)}
_consts_start = {n.value for n in _ast2.walk(_tree_start)
                 if isinstance(n, _ast2.Constant) and isinstance(n.value, str)}
assert 'custom_queries' in _consts_start, \
    'api_start 没有读 custom_queries（前端填的自定义词会被静默丢弃）'
assert 'raw_queries' in _names_start, 'api_start 没有把自定义词传递给 run_search'
assert 'RAW_QUERY_MAX' in _names_start, 'api_start 没有用单轮上限做长度校验'
assert 'run_search' in _names_start and 'run_maps' in _names_start, 'api_start 的两个 worker 分支不见了'
_tree_rs = _ast2.parse(_insp2.getsource(m.run_search))
_names_rs = {n.id for n in _ast2.walk(_tree_rs) if isinstance(n, _ast2.Name)}
_names_rs |= {n.attr for n in _ast2.walk(_tree_rs) if isinstance(n, _ast2.Attribute)}
assert 'raw_queries' in _names_rs and 'custom_mode' in _names_rs, \
    'run_search 没有 raw_queries / custom_mode 分支'
assert 'china_filter_terms' in _names_rs, \
    'run_search 不再拼中国过滤词了？（标准模式会静默退化）'
assert 'cond_template' in _names_rs, 'run_search 不再用条件模板了？（标准模式会静默退化）'
print('  ✓ R10 主页自定义搜索词：卡片/预览/地图置灰/上限齐备，'
      'api_start 读 custom_queries 并传给 run_search，run_search 有独立自定义分支')

# --- R11 主页「国家限定」四选一（默认关 / cr 走 URL / site: 走搜索词 / 只标准模式）---
# 这一支最怕两件事：① 默认值被改成非 none（用户没勾却悄悄改了搜索行为）；
#                  ② 前端预览与后端实搜不一致（照预览抄下来的公式发出去对不上）。
# 两条都是**静默失效**型 —— 不报错，只是结果悄悄变样。
for _need in ('id="countryLimit"', 'name="country_limit"',
              'value="none" checked', 'value="cr"', 'value="site"', 'value="both"',
              'function countryLimit()', 'function effectiveLimit()', 'function siteTerm()',
              "getElementById('countryLimit').style.display",
              '#conds, #excludes, #chinaFilters, #countryLimit',
              'country_limit: countryLimitVal'):
    assert _need in m.PAGE_HTML, f'主页缺少国家限定实现：{_need}'
# 预览与实搜必须同位置：site: 拼在条件模板之后（后端 core + ' ' + site）
assert "if (st) core = core + ' ' + st;" in m.PAGE_HTML, \
    '前端预览没把 site: 拼进公式主体（预览与实搜会不一致）'
assert "s += '&cr=' + cr;" in m.PAGE_HTML, \
    '前端预览没把 cr 挂到 URL 参数上（预览与实搜会不一致）'
# 数据层完整性：每个国家都要有 (cr, site) 条目；且不许动 COUNTRIES 的元组长度
assert set(m.COUNTRY_LIMITS) == {c[0] for c in m.COUNTRIES}, \
    'COUNTRY_LIMITS 与 COUNTRIES 的国家代码没对齐（缺项会让该国静默失效）'
assert all(len(c) == 4 for c in m.COUNTRIES), \
    'COUNTRIES 被改成非 4 元组（会连带炸前端注入与 run_search 解包）'
assert m.COUNTRY_LIMITS['us'][1] == '', '美国不该配 site: 后缀（.com 为主、.us 极少）'
assert m.COUNTRY_LIMITS['ca_fr'][0] == 'countryCA', 'ca_fr（内部代码）没映射到 countryCA'
assert m.COUNTRY_LIMIT_MODES == ('none', 'cr', 'site', 'both'), \
    f'四选一的取值被改了：{m.COUNTRY_LIMIT_MODES}'
assert m.COUNTRY_LIMIT_DEFAULT == 'none', \
    f'国家限定默认值被改了（用户没勾却会改搜索行为）：{m.COUNTRY_LIMIT_DEFAULT}'
# ⚠️ 同样只用 AST 取标识符/字符串常量，不做源码子串匹配。
assert 'country_limit' in _consts_start, \
    'api_start 没有读 country_limit（前端选的限定会被静默丢弃）'
assert 'country_limit' in _names_start, 'api_start 没有把国家限定传给 worker'
assert 'country_limit' in _names_rs and 'COUNTRY_LIMITS' in _names_rs, \
    'run_search 没有国家限定分支'
assert 'site_term' in _names_rs and 'cr_param' in _names_rs, \
    'run_search 里 cr/site 的拼装变量不见了（限定会静默失效）'
# 用**参数对象**断言默认值（signature 里是求值后的 'none'，不是源码里的常量名 —— 别按文本匹配）
_sig_rs = _insp2.signature(m.run_search)
assert 'country_limit' in _sig_rs.parameters, 'run_search 丢了 country_limit 参数'
assert _sig_rs.parameters['country_limit'].default == 'none', \
    f'country_limit 默认值应回落 none（旧调用方行为必须不变）：{_sig_rs.parameters["country_limit"].default}'
print('  ✓ R11 主页国家限定：四选一控件/默认 none/预览同位置齐备，'
      'COUNTRY_LIMITS 与 COUNTRIES 对齐，api_start 读并透传，run_search 有独立限定分支')

# --- R12 主页「本轮已入库明细（实时）」逐行删除（✕ / 居中模态框 / 墓碑过滤 / 锁外慢 IO）---
# 这一支最怕三件事，且**全都是静默失效型**（不报错，只是删得不对）：
#   ① 只删了内存明细、没删客户库 → 那条仍在库里，下次采到同站被判「已在客户库」永久跳过；
#   ② 没记墓碑 → 内存删了，但**结果 Excel 是用 worker 自己的局部 all_rows 写的**，那条照样进表、
#      飞书照样推（＝假删除，与 /manual ③ 的语义不一致）；
#   ③ 把备份/删库写进了 with STATE_LOCK 块 → backup_db_before_delete() 内部会调 log()，
#      而 log() 自己抢同一把**非可重入**的锁 → 必死锁（现场表现为页面卡死、要重启工具）。
# ⑥ 之后表格与逐行删除都搬进了共享组件 ui/live-table.js，所以「逐字钉住」的那几条要跟着变：
#    · 组件发请求是 fetch(cfg.endpoint)，整串 fetch('/api/live/delete') 不再存在 ——
#      改成「页面的 cfg 里确实写了这个接口」+「组件确实 fetch(endpoint)」两条一起钉。
#    · 模态框标记也搬进组件的运行时构建了，id="liveDelModal" 仍在页面文本里（在组件源码里）。
# ⛔ 同时钉住「两页用的是同一份组件」—— 去重的意义就在这里：改一处两边都变。
assert _cu._read_live_table_js() in m.PAGE_HTML and _cu._read_live_table_js() in m.MANUAL_HTML, \
    '「本轮明细」共享组件没有同时注入主页与 /manual —— 两页的表又分家了'
# 表头：两页必须真的是**同一张表**。上一轮就是「行业 / 国家」只长在 /manual 上、主页没有 ——
# 「只改一页」正是这条断言的靶子。取两页各自的 <thead> 逐字比对，比各自钉一串 <th> 更能暴露分家。
def _thead_of(html, body_id):
    _i = html.index('id="%s"' % body_id)
    _s = html.rindex('<thead>', 0, _i)
    return html[_s:html.index('</thead>', _s)]


_pg_thead = _thead_of(m.PAGE_HTML, 'liveBody')
_mn_thead = _thead_of(m.MANUAL_HTML, 'sessionBody')
assert _pg_thead == _mn_thead, \
    '主页与 /manual 的「本轮明细」表头不一致（又是只改了一页）：\n主页：%s\n/manual：%s' \
    % (_pg_thead, _mn_thead)
for _col in ('>行业</th>', '>国家</th>'):
    assert _col in _pg_thead, f'主页实时表缺列「{_col}」（/manual 有、主页没有就是分家）'
for _need in ('id="liveDelModal"', 'class="livedel-btn"', 'data-n',
              'function deleteLiveRow(', "'/api/live/delete'", 'fetch(endpoint',
              "getElementById('liveBody').addEventListener('click'",
              "closest('.livedel-btn')", 'function syncLiveEditable(',
              "classList.toggle('livedel-ro'", 'id="liveDelHint"', 'id="liveWrap"',
              '#liveDelModal { position:fixed; inset:0', '#liveDelModal.show { display:flex; }',
              "e.key === 'Escape'", "e.key === 'Enter'", 'renderedTail',
              'makeLiveTable'):
    assert _need in m.PAGE_HTML, f'主页缺少「实时明细逐行删除」实现：{_need}'
# ⚠️ 负向护栏：page.html 的 <style> 会被注入 /manual 与 /db，那两个页面各有一套自己的
#    删除按钮与居中弹窗（delModal 系 / modal 系 / 各自的 row-del、live-del）。
#    主页一旦复用了它们的名字，就会互相污染（哪条生效取决于文档顺序，极难排查）。
#    ⛔ 断言字符串本身不写前导的 . 和 #；另外**注释里也别写全名**，否则子串判定假红
#       （同一个坑见 R9 里那条 confirm 断言）。
for _bad in ('confirm(', '#delModal', '.row-del', '.live-del', '.modal-t', '.btn-danger', '.btn-plain'):
    assert _bad not in m.PAGE_HTML, \
        f'主页出现了属于 /manual 或 /db 的选择器「{_bad}」——共用样式会互相污染，请改用 livedel- 前缀'
# 数据层：STATE 必须有墓碑字段，且接口要真的注册上
assert 'rows_deleted' in m.STATE, "STATE 里没有 rows_deleted（删了却还在结果 Excel 里）"
assert 'api_live_delete' in m.app.view_functions, 'POST /api/live/delete 没有注册'
# ⚠️ 只用 AST 取标识符/字符串常量，不做源码子串匹配（docstring 里同名会造成假绿/假红）
_tree_live = _ast2.parse(_insp2.getsource(m.api_live_delete))
_names_live = {n.id for n in _ast2.walk(_tree_live) if isinstance(n, _ast2.Name)}
_names_live |= {n.attr for n in _ast2.walk(_tree_live) if isinstance(n, _ast2.Attribute)}
_consts_live = {n.value for n in _ast2.walk(_tree_live)
                if isinstance(n, _ast2.Constant) and isinstance(n.value, str)}
for _need in ('STATE_LOCK', 'STATE', '_delete_customer_and_backup'):
    assert _need in _names_live, f'api_live_delete 缺少：{_need}'


def _state_keys(tree):
    """取出 tree 里 `STATE['xxx']` 这类下标访问的字符串键。
    ⚠️ 必须结构化取，不能按源码子串匹配：`STATE['rows_deleted']` 里的 rows_deleted 是
       **字符串常量**（dict 键），既不在 ast.Name 里，靠整段源码 grep 又会被注释/docstring 骗到。"""
    _out = set()
    for _n in _ast2.walk(tree):
        if (isinstance(_n, _ast2.Subscript) and isinstance(_n.value, _ast2.Name)
                and _n.value.id == 'STATE' and isinstance(_n.slice, _ast2.Constant)):
            _out.add(_n.slice.value)
    return _out


assert 'rows_deleted' in _state_keys(_tree_live), \
    'api_live_delete 没有把 n 记进墓碑（内存删了，结果 Excel 里还在）'
assert 'phase' in _state_keys(_tree_live) and 'search' in _consts_live, \
    "api_live_delete 没有按 phase == 'search' 判定（导出飞书阶段会误删：库删了、表早写好了）"
# 慢 IO 必须在锁外：把「删库那半边」的调用按「祖先链里有没有 with」分成两组 —— 有一头进了 with
# 块就是死锁隐患（backup 内部调 log()，而 log() 抢同一把非可重入的锁）。
# ⑥ 之后这段是两个接口**共用**的 helper，所以两个接口都要过一遍 —— 顺带让 manual 那条链路也拿到
# 这个此前只有主页才有的结构化保证（以前它俩各自写着同样的两行，没人钉过 manual 那一份）。
def _slow_io_split(tree):
    _free, _locked = [], []

    def _walk(node, in_with):
        for _child in _ast2.iter_child_nodes(node):
            _nxt = in_with or isinstance(_child, _ast2.With)
            if isinstance(_child, _ast2.Call):
                _f = _child.func
                _nm = (_f.id if isinstance(_f, _ast2.Name)
                       else _f.attr if isinstance(_f, _ast2.Attribute) else '')
                if _nm in ('backup_db_before_delete', 'db_delete_customer',
                           '_delete_customer_and_backup'):
                    (_locked if _nxt else _free).append(_nm)
            _walk(_child, _nxt)

    _walk(tree, False)
    return _free, _locked


for _label, _fn in (('api_live_delete', m.api_live_delete),
                    ('api_manual_session_delete', m.api_manual_session_delete)):
    _free, _locked = _slow_io_split(_ast2.parse(_insp2.getsource(_fn)))
    assert not _locked, \
        f'{_label}: 慢 IO 被写进了 with 块内（backup 内部会调 log()，STATE_LOCK 非可重入 → 必死锁）：{_locked}'
    assert _free == ['_delete_customer_and_backup'], \
        f'{_label}: 删库那半边没走共享 helper（或漏了先备份 → 退化成只删内存的假删除）：{_free}'
# helper 自己：必须真的做「先备份 + 再删库」这两件事，而且**体内一把锁都不许拿**（它只负责慢 IO）
_tree_helper = _ast2.parse(_insp2.getsource(m._delete_customer_and_backup))
_helper_calls = [_c.func.id for _c in _ast2.walk(_tree_helper)
                 if isinstance(_c, _ast2.Call) and isinstance(_c.func, _ast2.Name)]
assert sorted(_helper_calls) == ['backup_db_before_delete', 'db_delete_customer'], \
    f'_delete_customer_and_backup 该做的两件事不齐：{_helper_calls}'
assert not [n for n in _ast2.walk(_tree_helper) if isinstance(n, _ast2.With)], \
    '共用删库半边里出现了 with 块 —— 它必须留在锁外（拿 STATE_LOCK 会与 log() 互锁）'
# 两个 worker 的 finally 都必须引用墓碑，否则「网页搜索」或「地图」有一条链路仍会把删掉的行落盘
_tree_maps = _ast2.parse(_insp2.getsource(m.run_maps))
assert 'rows_deleted' in _state_keys(_tree_rs), \
    'run_search 没碰 STATE[rows_deleted]（落盘前不过滤 → 删掉的行仍会进结果 Excel）'
assert 'rows_deleted' in _state_keys(_tree_maps), \
    'run_maps 没碰 STATE[rows_deleted]（地图链路落盘前不过滤 → 删掉的行仍会进结果 Excel）'
print('  ✓ R12 主页实时明细逐行删除：✕ 列/居中模态框/事件委托齐备（表格与确认框来自共享组件 '
      'ui/live-table.js，两页表头逐字一致、含「行业 / 国家」），api_live_delete 按 phase==search '
      '判定，两个删除接口的删库半边都走共享 helper 且都在锁外，墓碑进了 STATE 与两个 worker 的落盘过滤')

# --- R13 主页「1. 本次任务采集数量」（强必填 / 编号整轮顺延 / 后端不许有缺省值）---
# 用户 2026-10-02 拍板：把采集数量从「参数」卡里提出来，做成排在「目标国家」之前的第 1 张卡，
# 并且**强必填** —— 三条链路（标准网页搜索 / 自定义搜索词 / 谷歌地图）都要先写这个数才让开始。
# 三处都是**静默失效**型：① 编号重排漏改 → 页面里的提示语指到错的步骤（不报错，只是对不上）；
#                          ② 前端悄悄兜底默认值 → 用户清空后仍按 10 跑（等于没必填）；
#                          ③ 后端缺键取默认 → 手工/脚本直接打接口就绕过了必填。
_pg = m.PAGE_HTML
assert _pg.count('id="targetCount"') == 1, \
    f'#targetCount 出现了 {_pg.count("id=\"targetCount\"")} 次（搬卡时留下了重复 id？）'
for _need in ('<h3>1. 本次任务采集数量', '<h3>2. 目标国家（单选，下拉选择）',
              '<h3>7. 自定义搜索词（原样搜，不套上面的条件）',
              '或在第 7 步填一条自定义搜索词',
              '请先填写本次任务采集数量',
              '按新增个数计'):          # ⚠️ 这句原本在被搬走的那段 .note 里，必须逐字活下来
    assert _need in _pg, f'主页采集数量卡缺失：{_need}'
# 编号必须**整轮**顺延：不能还留着任何一个旧号（否则提示语与实际卡片对不上）
for _gone in ('<h3>6. 自定义搜索词', '<h3>1. 目标国家', '<h3>2. 产品关键词',
              '<h3>3. 搜索条件', '<h3>4. 参数', '<h3>5. 关键词组合预览'):
    assert _gone not in _pg, f'主页编号没有整轮顺延，仍残留旧标题：{_gone}'
# ⛔ 负向守卫：前端必须没有「清空后兜底默认值」那一段（有它就等于没必填）。
#    注意别把这段字面量写进注释，否则这条断言会被自己的注释撞红（老坑，踩过两次）。
assert "|| '10'" not in _pg, \
    'start() 里还留着 targetCount 的兜底默认值（输入框清空后会静默按 10 跑 → 等于没必填）'
assert 'valueAsNumber' in _pg, 'targetCount 没改用 valueAsNumber（清空时应得到 NaN 并被拦住）'
# 后端：data.get('target_count') 必须**不带第二个默认值参数**，且函数体里有对应的拒绝文案。
# ⚠️ 用 AST 看代码，不做源码子串匹配（docstring/注释里同名会假绿）。
_tree_start = _ast2.parse(_insp2.getsource(m.api_start))
_no_default, _bad_default, _has_msg = False, [], False
for _n in _ast2.walk(_tree_start):
    if (isinstance(_n, _ast2.Call) and isinstance(_n.func, _ast2.Attribute)
            and _n.func.attr == 'get' and _n.args
            and isinstance(_n.args[0], _ast2.Constant) and _n.args[0].value == 'target_count'):
        if len(_n.args) == 1:
            _no_default = True          # 正确写法：data.get('target_count')
        else:
            _bad_default.append(_n.lineno)   # 错误写法：带着默认值 → 缺键会被静默放过
    if isinstance(_n, _ast2.Constant) and isinstance(_n.value, str) \
            and '本次任务采集数量' in _n.value:
        _has_msg = True
assert _no_default, 'api_start 里找不到 data.get("target_count")（采集数量字段被改名了？）'
assert not _bad_default, \
    f'api_start 的 data.get("target_count") 又带上了缺省值（缺键会被静默放过）：行 {_bad_default}'
assert _has_msg, 'api_start 里没有「本次任务采集数量」的拒绝文案（缺键/空串必须显式拒绝）'
print('  ✓ R13 主页采集数量卡：提为「1.」且编号整轮顺延、#targetCount 唯一、'
      '前端无兜底默认值，api_start 的 data.get("target_count") 不带缺省值且有拒绝文案')

print('  ✓ 拆包防护断言全部通过（程序根 / 单例 / 动态 ENRICH_FILE / 残留定义 / 模板哈希 / '
      '第二页 R7 / 第三页 R9 / 主页 R10 / 主页 R11 / 主页 R12 / 主页 R13）')

print('\n✅ 页面静态检查通过')
