# -*- coding: utf-8 -*-
"""Chrome 扩展（extension/）静态回归校验 —— 不联网、不开浏览器，纯读文件。

覆盖 5 组：
  A. manifest.json 结构（权限最小化、host 白名单、内容脚本加载顺序、被引用文件都存在）
  B. 全部 JS 的语法（node --check）
  C. 端口表跨文件一致：extension/ports.js ↔ 客户开发工具.py 的 PREFERRED_PORTS
  D. 纪律检查（这几条都是踩过的坑，别改回去）：
       D1 只有 background.js 能 fetch 127.0.0.1 —— 内容是「唯一 fetch 出口」
       D2 content.js 里拼 HTML 不得出现 style= —— 会被页面 style-src 拦
       D3 floating-css.js 的 CSS 字符串里不得有反引号 / ${ —— 会被模板字符串吃掉
       D4 grabPage 体内不得引用 DP_* 常量 —— 它被序列化后送到页面执行，引用外部变量会炸
       D5 悬浮按钮必须用 Shadow DOM（attachShadow 存在）+ closed 模式
  E. 后端配套接口在位（/api/ping、/api/collect、X-DP-Ext 校验、/api/manual/* 与
     session/start|finish|delete），以及 popup 三条消息（DP_MANUAL_STATE / DP_SESSION_FINISH /
     DP_SESSION_DELETE）在 popup.js 与 background.js 两端都接上了

用法：python .workbuddy\\_check_ext.py     （EXIT 0 = 全过）
"""
import io
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, 'extension')
ENTRY = os.path.join(ROOT, '客户开发工具.py')


def _find_node():
    """定位 managed node.exe。

    ⛔ 别把版本号写死：本机从 22.22.2-3 升到 22.22.2-6 时，写死的路径直接
    FileNotFoundError —— 看着像「回归红了」，其实是环境漂移的假红。
    取 versions/ 下最新的一个（版本号字典序即可），最后才退回旧写死路径。
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

FAILS = []
WARNS = []


def check(cond, label, detail=''):
    if cond:
        print(f'  ✅ {label}')
    else:
        print(f'  ❌ {label}' + (f' —— {detail}' if detail else ''))
        FAILS.append(label)


def warn(cond, label, detail=''):
    if not cond:
        print(f'  ⚠️  {label}' + (f' —— {detail}' if detail else ''))
        WARNS.append(label)


def read(p):
    with io.open(p, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


print('=' * 78)
print('A. manifest.json')
print('=' * 78)
mf_path = os.path.join(EXT, 'manifest.json')
check(os.path.exists(mf_path), 'manifest.json 存在')
mf = json.loads(read(mf_path))

check(mf.get('manifest_version') == 3, 'manifest_version == 3', str(mf.get('manifest_version')))

perms = sorted(mf.get('permissions') or [])
want = sorted(['activeTab', 'scripting', 'contextMenus', 'storage'])
check(perms == want, f'权限恰好是 {want}', f'实际 {perms}')
for bad in ('tabs', 'notifications', 'alarms', '<all_urls>', 'webRequest'):
    check(bad not in (mf.get('permissions') or []), f'未申请多余权限：{bad}')

hosts = mf.get('host_permissions') or []
check(hosts == ['http://127.0.0.1/*', 'http://localhost/*'],
      'host_permissions 只给本机回环', str(hosts))

cs = (mf.get('content_scripts') or [{}])[0]
check(cs.get('js') == ['floating-css.js', 'content.js'],
      'content_scripts.js 顺序 = [floating-css.js, content.js]（顺序是硬要求）', str(cs.get('js')))
check('css' not in cs,
      'content_scripts 里没有再声明 .css（文档样式跨不过 shadow 边界，这条死路已废）')
check(cs.get('matches') == ['http://*/*', 'https://*/*'], 'content_scripts.matches 覆盖普通网页',
      str(cs.get('matches')))
check('http://127.0.0.1/*' in (cs.get('exclude_matches') or []),
      'content_scripts 排除了本机 127.0.0.1（不然工具自己的页面也长按钮）')

bg = mf.get('background') or {}
check(bg.get('service_worker') == 'background.js' and bg.get('type') != 'module',
      'background 是经典 Service Worker（type != module，才可以用 importScripts）', str(bg))

# 所有被引用的文件都得在
refs = ['background.js', 'popup.html', 'options.html'] + list(cs.get('js') or [])
if mf.get('action', {}).get('default_popup'):
    refs.append(mf['action']['default_popup'])
if mf.get('options_page'):
    refs.append(mf['options_page'])
for r in sorted(set(refs)):
    check(os.path.exists(os.path.join(EXT, r)), f'被引用的文件存在：{r}')

# HTML 里引用的 css/js 也得在
for html in ('popup.html', 'options.html'):
    p = os.path.join(EXT, html)
    if not os.path.exists(p):
        continue
    body = read(p)
    for m in re.finditer(r'(?:src|href)="([^"]+)"', body):
        t = m.group(1)
        if t.startswith(('http', '#', 'data:')):
            continue
        check(os.path.exists(os.path.join(EXT, t)), f'{html} 引用的 {t} 存在')
    # MV3 禁止内联脚本：<script> 必须带 src
    inline = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', body)
    check(not inline, f'{html} 没有内联 <script>（MV3 禁止）', str(inline[:2]))
    # 内联事件处理器同样被 MV3 的 CSP 拦
    onattr = re.findall(r'\son[a-z]+\s*=', body)
    check(not onattr, f'{html} 没有内联事件处理器（onclick 等）', str(onattr[:3]))

print()
print('=' * 78)
print('B. JS 语法（node --check）')
print('=' * 78)
js_files = ['ports.js', 'background.js', 'floating-css.js', 'content.js', 'popup.js', 'options.js']
for f in js_files:
    p = os.path.join(EXT, f)
    if not os.path.exists(p):
        check(False, f'{f} 存在')
        continue
    r = subprocess.run([NODE, '--check', p], capture_output=True, text=True)
    check(r.returncode == 0, f'语法 OK：{f}', (r.stderr or '').strip()[:300])

print()
print('=' * 78)
print('C. 端口表跨文件一致（最容易漂的一条）')
print('=' * 78)
m = re.search(r'^PREFERRED_PORTS\s*=\s*\(([^)]*)\)', read(ENTRY), re.M)
py_ports = [int(x) for x in re.findall(r'\d+', m.group(1))] if m else []
m2 = re.search(r'DP_PREFERRED_PORTS\s*=\s*\[([^\]]*)\]', read(os.path.join(EXT, 'ports.js')))
js_ports = [int(x) for x in re.findall(r'\d+', m2.group(1))] if m2 else []
check(bool(py_ports) and bool(js_ports), '两边都取到了端口表', f'py={py_ports} js={js_ports}')
check(py_ports == js_ports, '客户开发工具.py PREFERRED_PORTS == extension/ports.js DP_PREFERRED_PORTS',
      f'py={py_ports} js={js_ports}')

bg_src = read(os.path.join(EXT, 'background.js'))
check("importScripts('ports.js')" in bg_src, 'background.js 用 importScripts 载入 ports.js')
check("app === DP_APP_ID" in bg_src, '端口 discovery 校验了 app 身份字段（防误连本机别的服务）')

print()
print('=' * 78)
print('D. 纪律检查（踩过的坑，别改回去）')
print('=' * 78)
def strip_comments(src):
    """去掉 JS 注释后再做纪律检查 —— 注释里正大光明地讲「不要写 style=」不该被判违规。"""
    src = re.sub(r'/\*.*?\*/', ' ', src, flags=re.S)
    src = re.sub(r'(?<!:)//[^\n]*', ' ', src)     # (?<!:) 免得把 https:// 当注释
    return src


pkgs = {f: read(os.path.join(EXT, f)) for f in js_files if os.path.exists(os.path.join(EXT, f))}
code = {f: strip_comments(v) for f, v in pkgs.items()}

for f in ('content.js', 'popup.js', 'options.js', 'floating-css.js'):
    if f in code:
        n = len(re.findall(r'\bfetch\s*\(', code[f]))
        check(n == 0, f'{f} 里没有 fetch（请求必须走 background）', f'发现 {n} 处')
check(len(re.findall(r'127\.0\.0\.1', code.get('background.js', ''))) >= 2,
      'background.js 是唯一 fetch 出口（出现 127.0.0.1）')

cjs = code.get('content.js', '')
hit = re.search(r'.{0,50}style\s*=.{0,50}', cjs, re.S)
check(not hit, 'content.js 里拼 HTML 未使用任何 style=（会被页面 style-src 拦）',
      (hit.group(0).replace('\n', ' ') if hit else ''))
check('adoptedStyleSheets' in cjs, 'content.js 用 adoptedStyleSheets 注入样式（CSSOM 不受 CSP 管）')
check("attachShadow({ mode: 'closed' })" in cjs, '悬浮按钮用 Shadow DOM 且 closed 模式')
check("setAttribute('style'" not in cjs, "content.js 没有 setAttribute('style', ...)")

fcss = pkgs.get('floating-css.js', '')
body = fcss.split('String.raw`', 1)[-1].rsplit('`;', 1)[0] if 'String.raw`' in fcss else ''
check(bool(body.strip()), 'floating-css.js 里取到了 CSS 字符串')
check('`' not in body, 'CSS 字符串里没有反引号（会提前闭合模板字符串）')
check('${' not in body, 'CSS 字符串里没有 ${（会被模板字符串当插值吃掉）')
check(':host' in body, 'CSS 里有 :host 规则（把宿主从页面样式继承里摘出来）')

gp = re.search(r'function grabPage\(\)\s*\{(.*?)\n\}', bg_src, re.S)
check(bool(gp), '在 background.js 里找到 grabPage')
if gp:
    check('DP_' not in gp.group(1),
          'grabPage 体内没有引用 DP_* 常量（它被序列化后送进页面，引用外部变量必炸）')

print()
print('=' * 78)
print('E. 后端配套接口')
print('=' * 78)
entry = read(ENTRY)
for route in ("@app.route('/api/ping')", "@app.route('/api/collect'",
              "@app.route('/manual')", "@app.route('/api/keywords')",
              "@app.route('/api/manual/batch'", "@app.route('/api/manual/state')",
              "@app.route('/api/manual/stop'", "@app.route('/api/manual/close_browser'",
              "@app.route('/api/manual/session/start'", "@app.route('/api/manual/session/finish'",
              "@app.route('/api/manual/session/delete'"):
    check(route in entry, f'后端路由在位：{route}')
check("request.headers.get('X-DP-Ext') != '1'" in entry,
      '/api/collect 校验了自定义头 X-DP-Ext')
check("origin.startswith('chrome-extension://')" in entry,
      'CORS 只回显 chrome-extension:// 来源')
check("resp.headers['Access-Control-Allow-Origin'] = origin" in entry
      and "'*'" not in entry.split('def _cors_headers')[1][:1200],
      'CORS 绝不返回通配 *')

# popup 的「本轮采集明细 / 结束并生成 Excel」两条消息必须两端都接上
# （popup 只发消息，真正的 fetch 在 background；漏了任一端面板就是死的）
check("DP_MANUAL_STATE" in code.get('popup.js', ''),
      'popup.js 请求了本轮明细（DP_MANUAL_STATE）')
check("DP_SESSION_FINISH" in code.get('popup.js', ''),
      'popup.js 请求了结束本轮（DP_SESSION_FINISH）')
check("case 'DP_MANUAL_STATE'" in code.get('background.js', ''),
      'background.js 路由了 DP_MANUAL_STATE')
check("case 'DP_SESSION_FINISH'" in code.get('background.js', ''),
      'background.js 路由了 DP_SESSION_FINISH')
check('/api/manual/state' in code.get('background.js', '')
      and '/api/manual/session/finish' in code.get('background.js', ''),
      'background.js 里两个新出口打的是真实后端路径')

# 「每行 ✕ 删除」这条链路也必须两端接上（popup 只发消息，fetch 仍只在 background）
check("DP_SESSION_DELETE" in code.get('popup.js', ''),
      'popup.js 请求了删除单条（DP_SESSION_DELETE）')
check("case 'DP_SESSION_DELETE'" in code.get('background.js', ''),
      'background.js 路由了 DP_SESSION_DELETE')
check('/api/manual/session/delete' in code.get('background.js', ''),
      'background.js 的删除出口打的是真实后端路径')
_manual_html = read(os.path.join(ROOT, 'ui', 'manual.html'))
check('data-rid' in code.get('popup.js', '') and 'data-rid' in _manual_html,
      'popup 与页面都给明细行带了 data-rid（按行号删，不按 url）')

print()
print('=' * 78)
if FAILS:
    print(f'❌ 失败 {len(FAILS)} 项：')
    for f in FAILS:
        print('   · ' + f)
    sys.exit(1)
print('✅ 全部通过' + (f'（{len(WARNS)} 条提醒）' if WARNS else ''))
