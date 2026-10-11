# -*- coding: utf-8 -*-
"""从「海关统计数据在线查询平台」抓「8位商品编码 + 商品名称」，写成一份 XLSX。

数据来源：http://stats.customs.gov.cn/  →  参数查询  →  商品参数  →  商品编码/商品名称对照表

⛔ 为什么必须开真浏览器（不要试图改成 requests）：
   该站挂的是**瑞数信息动态防护**。用普通 HTTP 客户端请求时，服务器返回 **412**，
   响应体是一段混淆 JS（含 `$_ts` 变量）+ meta refresh + `SF_cookie_251`，
   等浏览器把那段 JS 跑完、种下有效 Cookie 之后才放行。
   所以纯 requests / urllib **必然拿不到数据**，本项目已内置 DrissionPage，
   这里直接复用 `客户开发工具.py::create_browser_page()`（浏览器 exe 只在那一个地方配）。

用法（在本目录下打开命令行）：
    python 海关商品编码采集.py              # 抓 2025 年版的 8 位编码（8969 条）
    python 海关商品编码采集.py --dry         # 只抓第 1 页，报告总数/总页数，不写文件
    python 海关商品编码采集.py --year ""     # 不限年份（=104238 条 / 522 页）
    python 海关商品编码采集.py --fresh       # 忽略断点缓存，全量重抓

也可以直接双击「海关商品编码采集.bat」，效果一样。
抓的中途可以 Ctrl+C 中断：已抓到的页会缓存下来，重跑会自动续抓。
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, '客户开发工具.py')
SITE = 'http://stats.customs.gov.cn'
ENTRY = SITE + '/queryData/selectCodeTs'
CACHE = os.path.join(BASE, '.workbuddy', '_海关编码_pages.json')   # 断点缓存（可随时删）
DEFAULT_OUT = os.path.join(BASE, 'output', '海关编码')
PROFILE_PREFIX = 'waimao_dp_chrome_'        # create_browser_page() 建临时 profile 用的前缀

HEADER = ('商品编码', '商品名称')
COL_WIDTHS = (14, 60)
EXPECT_DEFAULT = 8969                       # 8位 + 2025年 的实测条数；只用于告警
PAGE_SIZE_MAX = 200                         # 站点「每页显示条数」下拉的最大档
EIGHT_DIGITS_RE = re.compile(r'\d{8}')      # 文件名里出现它会劫持飞书导出，见 _out_path()
TOTAL_RE = re.compile(r'共查询到\s*<span[^>]*>\s*(\d+)\s*</span>')
PAGES_RE = re.compile(r'共(\d+)页')

# 页面里取结构化行：编码 = 勾选框 value；名称 = .th-line 的 title（可见文本被 CSS 截断，title 才是全名）
ROWS_JS = """
return Array.from(document.querySelectorAll('#table tbody tr')).map(function (tr) {
  var cb = tr.querySelector('input[name=checkOne]');
  var tds = tr.querySelectorAll('td');
  var d = tds.length > 2 ? tds[2].querySelector('.th-line') : null;
  return [cb ? cb.value : '', d ? (d.getAttribute('title') || d.textContent || '') : ''];
});
"""

# 表格是否已换上「第 n 页」：结果页表单里的 hidPageNum 就是当前页号。
# ⚠️ 不能只看「有没有行」——提交后的一瞬间旧 DOM 里还留着上一页的行，会误判成已就绪，
#    于是把**上一页的数据当成这一页**存下来（静默错页，比报错难查得多）。
_READY_JS = ("return String((document.getElementById('hidPageNum') || {}).value) === '%(n)d' "
             "&& document.querySelectorAll('#table tbody tr').length > 0;")

# ⚠️ 表单里 codeLength 既是隐藏域、又是 4 个同名 radio，两个都要设，
#    否则提交串里会同时带上旧值（实测：只改隐藏域会出现 codeLength=8 与 codeLength=2 并存）。
# ⚠️ pageSize 页面默认是 10（不是 200），不显式设会变成 897 页。
# ⚠️ yearId 是关键闸门：'2025' → 8969 条；'' → 104238 条。
_SUBMIT_JS = """
return (function () {
  var f = document.getElementById('Search_form');
  if (!f) return false;
  var setVal = function (id, v) { var e = document.getElementById(id); if (e) e.value = v; };
  setVal('codeLength', '8');
  var radios = document.querySelectorAll('input[type=radio][name=codeLength]');
  for (var i = 0; i < radios.length; i++) { if (radios[i].value === '8') radios[i].checked = true; }
  setVal('hidPageNum', '%(n)d');
  setVal('hidPageSize', '%(ps)d');
  setVal('yearId', '%(year)s');
  setVal('codeTsList', '');
  setVal('searchKey', '');
  f.submit();
  return true;
})();
"""


# ==================== 基础小工具 ====================
def load_tool():
    """加载主工具模块，只为了拿 create_browser_page()。

    用 importlib 而不是 import：主工具里 `app.run()` 在 `if __name__ == '__main__'` 内，
    所以 exec_module 不会起 Flask（`补历史欠账.py` 用的就是这一招）。
    """
    spec = importlib.util.spec_from_file_location('kf', SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['kf'] = mod
    spec.loader.exec_module(mod)
    return mod


def _wait_until(page, probe, tries, interval, what):
    """轮询等待（项目纪律：等异步一律轮询，不要固定 sleep）。"""
    for _ in range(tries):
        try:
            if probe():
                return True
        except Exception:
            pass
        time.sleep(interval)
    print(f'⚠️ 等待超时：{what}')
    return False


def _is_real_page(html):
    """反爬是否已过：挑战页只有 2-3KB 且含 $_ts；真页面 > 8KB 且不含。"""
    return len(html) > 8000 and '$_ts' not in html


def _has_form(page):
    try:
        return bool(page.run_js("return !!document.getElementById('Search_form');"))
    except Exception:
        return False


def _rows_of_page(page, n):
    """第 n 页就绪时的行数；页号还没对上就返回 0。"""
    try:
        return int(page.run_js(_READY_JS % {'n': n}) or 0)
    except Exception:
        return 0


def _int_of(regex, text):
    m = regex.search(text or '')
    return int(m.group(1)) if m else 0


def _diag(page):
    """失败时打印足够定位的信息，别只说「失败」。"""
    try:
        html = page.html
    except Exception as e:
        print(f'❌ 连页面都读不到：{type(e).__name__}: {e}')
        return
    print(f'❌ 诊断：URL={getattr(page, "url", "?")} 长度={len(html)} '
          f'含$_ts={"$_ts" in html} 含海关统计={"海关统计" in html}')


# ==================== 抓取 ====================
def _open(page, url, what, rounds=4, tries=40, interval=0.5):
    """打开页面并等反爬挑战过去。

    ⛔ 必须**重新导航**重试，不能只等：站点偶尔会直接吐一个 **39 字节的空文档**
       （`<html><head></head><body></body></html>`，实测偶发）。空文档自己不会变好，
       傻等只会白等到超时 —— 重开一次就正常了。这是站点握手的不稳定，不是被封。
    """
    for k in range(1, rounds + 1):
        try:
            page.get(url)
        except Exception as e:
            print(f'  ⚠️ 打开 {what} 第 {k} 次抛错：{type(e).__name__}: {e}')
        if _wait_until(page, lambda: _is_real_page(page.html), tries, interval, what):
            return True
        if k < rounds:
            print(f'  ↻ {what} 第 {k} 次没拿到真页面（可能是空文档），重新导航…')
            time.sleep(2)
    return False


def _submit_js(n, page_size, year):
    year = re.sub(r'[^0-9]', '', year or '')        # 只可能是数字或空，顺手挡注入
    return _SUBMIT_JS % {'n': n, 'ps': page_size, 'year': year}


def _fetch_page(page, n, page_size, year, retries=3):
    """抓第 n 页，返回 (rows, total, pages)；彻底失败返回 None。"""
    for attempt in range(1, retries + 1):
        try:
            if not _has_form(page):
                raise RuntimeError('页面上找不到 #Search_form')
            try:
                page.run_js(_submit_js(n, page_size, year))
            except Exception:
                pass        # 提交会立刻触发整页跳转，run_js 在这时抛错属正常，别当失败
            if not _wait_until(page, lambda: _rows_of_page(page, n) > 0, 30, 0.3,
                               f'第 {n} 页表格'):
                raise RuntimeError(f'提交后第 {n} 页的表格一直没出来')
            html = page.html
            rows = page.run_js(ROWS_JS) or []
            if not rows:
                raise RuntimeError('解析到 0 行')
            return rows, _int_of(TOTAL_RE, html), _int_of(PAGES_RE, html)
        except Exception as e:
            print(f'  ⚠️ 第 {n} 页第 {attempt} 次失败：{type(e).__name__}: {e}')
            if attempt < retries:
                # 多半是反爬挑战过期了：重走一遍首页 → 查询页
                _open(page, SITE, '重新过反爬')
                _open(page, ENTRY, '重新打开查询页')
    return None


# ==================== 断点缓存 ====================
def _load_cache():
    try:
        with open(CACHE, encoding='utf-8') as f:
            data = json.load(f)
        return {int(k): v for k, v in (data.get('pages') or {}).items()}
    except Exception:
        return {}


def _save_cache(pages):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'pages': {str(k): v for k, v in pages.items()}},
                      f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except Exception as e:
        print(f'⚠️ 断点缓存写不进去（不影响本轮结果）：{type(e).__name__}: {e}')


# ==================== 写出 ====================
def _ensure_out_dir(out_dir):
    """保证输出目录存在；建不出来就退回 output/（名字里没有 8 位日期，回落也安全）。"""
    try:
        os.makedirs(out_dir, exist_ok=True)
        return out_dir
    except Exception as e:
        fallback = os.path.join(BASE, 'output')
        print(f'⚠️ 建不出目录 {out_dir}（{type(e).__name__}: {e}），改用 {fallback}')
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _out_path(out_dir, year, count, partial):
    """output/海关编码/海关商品编码-2025年-共8969条.xlsx；重名自动 _2/_3。

    ⛔ 文件名**绝不能出现 8 位连续数字**：`find_latest_result()`（core/paths.py）只 glob
       output/ 一层 + 靠「文件名里有 8 位日期」挑候选，一旦命中就会被当成「最新结果文件」，
       把飞书导出的目标劫持到这份海关表上 —— 这正是 output/查询导出/ 必须建子目录的同一个坑。
       下面那行断言就是防止以后有人改名字时踩回去。
    """
    stamp = f'{year}年' if year else '全部年份'
    name = f'海关商品编码-{stamp}-共{count}条' + ('-部分' if partial else '')
    path = os.path.join(out_dir, name + '.xlsx')
    n = 2
    while os.path.exists(path):
        path = os.path.join(out_dir, f'{name}_{n}.xlsx')
        n += 1
    if EIGHT_DIGITS_RE.search(os.path.basename(path)):
        raise RuntimeError(f'文件名 {os.path.basename(path)} 含 8 位连续数字，'
                           f'会被 find_latest_result() 当成结果文件，必须改名')
    return path


def _write_xlsx(items, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = '商品编码'
    ws.append(list(HEADER))
    for code, name in items:
        ws.append([code, name])
    ws.column_dimensions['A'].width = COL_WIDTHS[0]
    ws.column_dimensions['B'].width = COL_WIDTHS[1]
    wb.save(path)
    return path


# ==================== 抓取主流程 ====================
def _scrape(kf, cache, args, page_size, year):
    """开真浏览器抓取，把结果并进 cache。

    返回 (status, total, pages, missing, interrupted)：status ∈ {'ok','dry','fail'}。
    """
    missing = []
    interrupted = False
    total = pages = 0
    profiles_before = {n for n in os.listdir(tempfile.gettempdir())
                       if n.startswith(PROFILE_PREFIX)}
    page = None
    try:
        page = kf.create_browser_page()
        print('① 打开站点首页，等待通过动态反爬（瑞数）…')
        if not _open(page, SITE, '站点首页'):
            _diag(page)
            print('❌ 没过反爬。可重跑一次；若持续失败，多半是对方策略变了或本机网络被拦。')
            return 'fail', 0, 0, missing, interrupted

        print('② 打开「商品编码 / 商品名称」查询页…')
        if not _open(page, ENTRY, '查询页'):
            _diag(page)
            return 'fail', 0, 0, missing, interrupted

        if 1 in cache:
            total = cache[1].get('total') or 0
            pages = cache[1].get('pages') or 0
        else:
            got = _fetch_page(page, 1, page_size, year)
            if not got:
                _diag(page)
                return 'fail', 0, 0, missing, interrupted
            cache[1] = {'rows': got[0], 'total': got[1], 'pages': got[2]}
            _save_cache(cache)
            total, pages = got[1], got[2]

        print(f'③ 共查询到 {total} 条 / 共 {pages} 页')
        if args.expect and total != args.expect:
            print(f'⚠️ 与期望 {args.expect} 条不一致（站点数据可能已更新），按实际 {total} 条继续。')

        if args.dry:
            print('\n--dry：只抓了第 1 页，未写文件。去掉 --dry 即正式抓取。')
            return 'dry', total, pages, missing, interrupted

        if pages > 1:
            print(f'④ 逐页抓取（共 {pages} 页，Ctrl+C 可中断，已抓的会保留）…')
        for n in range(2, pages + 1):
            if n in cache:
                continue
            got = _fetch_page(page, n, page_size, year)
            if not got:
                missing.append(n)
                continue
            cache[n] = {'rows': got[0], 'total': got[1], 'pages': got[2]}
            _save_cache(cache)
            print(f'\r   进度 {n}/{pages}', end='', flush=True)
        print()
    except KeyboardInterrupt:
        interrupted = True
        print('\n⏹ 已中断（Ctrl+C）：下面用已抓到的页出一份「部分」结果，重跑会自动续抓。')
    finally:
        try:
            if page is not None:
                page.quit()
        except Exception:
            pass
        for name in {n for n in os.listdir(tempfile.gettempdir())
                     if n.startswith(PROFILE_PREFIX)} - profiles_before:
            shutil.rmtree(os.path.join(tempfile.gettempdir(), name), ignore_errors=True)
    return 'ok', total, pages, missing, interrupted


# ==================== 入口 ====================
def main():
    ap = argparse.ArgumentParser(
        description='抓海关「8位商品编码 + 商品名称」并存成 XLSX（需真浏览器）。')
    ap.add_argument('--year', default='2025',
                    help='年份（表单里的 yearId）；传空字符串 = 不限年份（104238 条）')
    ap.add_argument('--out', default=DEFAULT_OUT, help='输出目录')
    ap.add_argument('--page-size', type=int, default=PAGE_SIZE_MAX,
                    help=f'每页条数，站点上限 {PAGE_SIZE_MAX}')
    ap.add_argument('--expect', type=int, default=EXPECT_DEFAULT,
                    help='期望总条数，仅用于告警（不阻断）')
    ap.add_argument('--fresh', action='store_true', help='忽略断点缓存，全量重抓')
    ap.add_argument('--dry', action='store_true', help='只抓第 1 页并报告总数/总页数，不写文件')
    args = ap.parse_args()

    page_size = max(1, min(PAGE_SIZE_MAX, args.page_size))
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(BASE, args.out)
    year = args.year
    if not args.dry:
        out_dir = _ensure_out_dir(out_dir)   # 早建目录，让下面那行横幅显示的就是真实落点

    print('=' * 62)
    print('海关「8位商品编码 + 商品名称」采集')
    print(f'  年份 yearId = {year or "(不限)"}   每页 = {page_size}   输出目录 = {out_dir}')
    print('=' * 62)

    kf = load_tool()
    cache = {} if args.fresh else _load_cache()
    if cache:
        print(f'↩️ 复用断点缓存：已有 {len(cache)} 页（--fresh 可忽略）')

    cached_pages = cache.get(1, {}).get('pages') or 0
    if args.dry and 1 in cache:
        # --dry 只是探路，连浏览器都不用开
        print(f'✅ 断点缓存已有第 1 页：共查询到 {cache[1].get("total")} 条 / '
              f'共 {cache[1].get("pages")} 页（--fresh 可重新探测）')
        print('\n--dry：未写文件、未访问网站。')
        return 0
    # ⚠️ --dry 绝不能走「缓存全命中 → 直接汇总」那条路，否则会真的写出文件来
    full_cached = (not args.dry) and bool(cached_pages) \
        and all(n in cache for n in range(1, cached_pages + 1))
    missing, interrupted = [], False
    if full_cached:
        print(f'✅ 断点缓存已含第 1–{cached_pages} 页，直接汇总、不开浏览器'
              f'（--fresh 可强制重抓）')
        total = cache[1].get('total') or 0
        pages = cached_pages
    else:
        status, total, pages, missing, interrupted = _scrape(kf, cache, args, page_size, year)
        if status == 'dry':
            return 0
        if status == 'fail':
            return 2

    # ---- 汇总（按编码保序去重）----
    items, seen = [], set()
    for n in sorted(cache):
        for row in cache[n].get('rows') or []:
            code, name = (row + ['', ''])[:2]
            code = (code or '').strip()
            if code and code not in seen:
                seen.add(code)
                items.append((code, (name or '').strip()))
    if not items:
        print('❌ 一条数据都没抓到，没有可写的内容。')
        return 2

    print(f'⑤ 汇总：缓存 {len(cache)} 页 → 去重后 {len(items)} 条'
          f'（页面报告总数 {cache.get(1, {}).get("total", "?")}）')
    for code, name in items[:3]:
        print(f'     {code}  {name}')
    print('      …')
    for code, name in items[-3:]:
        print(f'     {code}  {name}')

    # ---- 收尾断言（不合格要报出来，别静默写坏文件）----
    problems = []
    bad_code = [c for c, _ in items if not re.fullmatch(r'\d{8}', c)]
    bad_name = [(c, nm) for c, nm in items
                if not nm or nm.rstrip().endswith(('...', '…'))]
    reported = cache.get(1, {}).get('total') or 0
    if bad_code:
        problems.append(f'{len(bad_code)} 条编码不是 8 位纯数字，例：{bad_code[:5]}')
    if bad_name:
        problems.append(f'{len(bad_name)} 条名称疑似被截断（以省略号结尾），例：{bad_name[:3]}')
    if missing:
        problems.append(f'有 {len(missing)} 页没抓到：{missing[:20]}')
    if reported and len(items) != reported:
        problems.append(f'去重后 {len(items)} 条 ≠ 页面报告的 {reported} 条')

    partial = bool(problems) or interrupted
    try:
        path = _write_xlsx(items, _out_path(out_dir, year, len(items), partial))
    except Exception as e:
        print(f'❌ 写 XLSX 失败（可能被 Excel 占用同名文件）：{type(e).__name__}: {e}')
        return 3

    print(f'💾 已保存：{path}（{len(items) + 1} 行 × 2 列，含表头）')
    if problems:
        print('\n❌ 数据校验没全过：')
        for p in problems:
            print(f'   · {p}')
        print('   文件已写出，但请先人工核对再用。')
        return 4
    print('✅ 校验通过：编码全为 8 位数字、名称无截断、条数与页面报告一致。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
