# -*- coding: utf-8 -*-
"""页面模板与渲染（原 `客户开发工具.py` 第 1655–2325 行整段搬入）。

模板本体放在**独立的 `ui/page.html`**：
改样式/文案不用再碰 Python 字符串，直接编辑该文件 → 重启工具即生效
（`PAGE_HTML` 在模块导入时构建一次，和以前一样是「重启才生效」）。

依赖：core.config（条件词/国家/地图常量）+ core.paths._app_dir（定位项目根）。
被入口以 `from core.ui import PAGE_HTML, _build_page` 拉回；
入口的 PEP 562 __getattr__ 再把这两个名字转发给老脚本（万一有脚本读 kf.PAGE_HTML）。
"""
import os
import re

from core.config import (CHINA_FILTER_OPTIONS, COND_LANGS, COND_ROLES, CONDITIONS,
                         COUNTRIES, COUNTRY_CENTERS, EXCLUDE_OPTIONS, cond_template)
from core.paths import _app_dir

# 模板文件：<项目根>/ui/page.html
_PAGE_TEMPLATE_PATH = os.path.join(_app_dir(), 'ui', 'page.html')
# 第二个页面（手动采集）的模板：<项目根>/ui/manual.html
_MANUAL_TEMPLATE_PATH = os.path.join(_app_dir(), 'ui', 'manual.html')
# 从 page.html 里抽 <style>…</style> 注入 manual 页 —— 这样两页共用一份 CSS，
# 且 page.html **一个字节都不用改**（_check_page.py 第 6 节 R5 的模板哈希基线因此保持成立）。
_STYLE_RE = re.compile(r'<style>(.*?)</style>', re.S)
PAGE_CSS_PLACEHOLDER = 'PAGE_CSS_PLACEHOLDER'


def _read_page_template():
    """读页面模板。缺文件时抛出带**绝对路径**的错误，避免只看到一堆裸 KeyError/空页面。"""
    try:
        with open(_PAGE_TEMPLATE_PATH, encoding='utf-8') as f:
            return f.read()
    except OSError as e:
        raise RuntimeError(
            '页面模板读取失败：{}\n原因：{}\n'
            '（ui/page.html 随程序一起分发，请确认它没被删除或改名）'.format(
                _PAGE_TEMPLATE_PATH, e)) from e


# 填充页面里的条件和国家（用 Python 注入，避免 JS 里写中文 JSON 出问题）
def _build_page():
    # (key, 名称, 是否默认勾选, {语言: 公式模板}) —— 模板给前端做「关键词组合预览」，
    # 按当前选择的搜索语言取，保证预览与实际查询（run_search 里 cond_template）一致
    tmpl_map = {k: {lg: cond_template(k, lg) for lg in COND_LANGS} for k, _ in CONDITIONS}
    default_on = ('wholesale', 'importer')
    conds_js = [(k, name, k in default_on, tmpl_map.get(k, {'en': '{p}'}))
                for k, name in CONDITIONS]
    # 默认勾选美国；(代码, 名称, 是否默认勾选, 该国语言 hl, gl) —— hl/gl 用于「国家→语言」联动
    # 和预览里显示国家筛选参数（gl=fr&hl=fr）
    counts_js = [(k, name, k == 'us', hl, gl) for k, name, gl, hl in COUNTRIES]
    excls_js = [(k, v, d) for k, v, d in EXCLUDE_OPTIONS]
    china_js = [(k, q, label, desc) for k, q, label, desc in CHINA_FILTER_OPTIONS]
    # 国家代码 → [纬度, 经度]：给前端拼地图搜索 URL 用，与后端 COUNTRY_CENTERS 同源
    centers_js = {k: [lat, lng] for k, (lat, lng) in COUNTRY_CENTERS.items()}
    # 条件 → {语言: 该条件角色词的第一个词}：地图模式要把它拼进查询词，前端预览必须与后端一致
    roles_js = {k: {lg: (v.get(lg) or v.get('en') or '').split(' OR ')[0].strip().strip('"')
                    for lg in COND_LANGS}
                for k, v in COND_ROLES.items()}
    import json as _json
    # ⚠️ 这里必须用局部变量 tmpl：模块级 PAGE_HTML 要到本文件最后一行才被赋值，
    #    函数体在那一刻引用它会是 NameError。
    tmpl = _read_page_template()
    html = tmpl.replace('CONDS_PLACEHOLDER', _json.dumps(conds_js, ensure_ascii=False))
    html = html.replace('COUNTS_PLACEHOLDER', _json.dumps(counts_js, ensure_ascii=False))
    html = html.replace('EXCLS_PLACEHOLDER', _json.dumps(excls_js, ensure_ascii=False))
    html = html.replace('CHINA_FILTERS_PLACEHOLDER', _json.dumps(china_js, ensure_ascii=False))
    html = html.replace('MAPS_CENTERS_PLACEHOLDER', _json.dumps(centers_js))
    html = html.replace('MAPS_ROLES_PLACEHOLDER', _json.dumps(roles_js, ensure_ascii=False))
    return html


# ⚠️ 必须放在文件最后：_build_page() 依赖上面的全部常量与 _read_page_template
PAGE_HTML = _build_page()


def _read_manual_template():
    """读手动采集页模板。缺文件时同样抛带绝对路径的错误（不要静默发个空页面出去）。"""
    try:
        with open(_MANUAL_TEMPLATE_PATH, encoding='utf-8') as f:
            return f.read()
    except OSError as e:
        raise RuntimeError(
            '手动采集页模板读取失败：{}\n原因：{}\n'
            '（ui/manual.html 随程序一起分发，请确认它没被删除或改名）'.format(
                _MANUAL_TEMPLATE_PATH, e)) from e


def _build_manual_page():
    """构建手动采集页：把 page.html 的 <style> 整块注入，样式只维护一份。"""
    m = _STYLE_RE.search(_read_page_template())
    if not m:
        raise RuntimeError(f'ui/page.html 里找不到 <style> 块，无法给手动采集页注入样式：'
                           f'{_PAGE_TEMPLATE_PATH}')
    tmpl = _read_manual_template()
    if PAGE_CSS_PLACEHOLDER not in tmpl:
        raise RuntimeError(f'ui/manual.html 里没有 {PAGE_CSS_PLACEHOLDER} 占位符，'
                           f'样式无法注入（模板是不是被改坏了？）')
    return tmpl.replace(PAGE_CSS_PLACEHOLDER, m.group(1))


# ⚠️ 同样必须放文件最后：_build_manual_page() 依赖 _read_manual_template 与 page.html 的样式块
MANUAL_HTML = _build_manual_page()
