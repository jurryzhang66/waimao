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
# 第三个页面（客户库查询）的模板：<项目根>/ui/query.html
_QUERY_TEMPLATE_PATH = os.path.join(_app_dir(), 'ui', 'query.html')
# 从 page.html 里抽 <style>…</style> 注入副页面 —— 多页共用一份 CSS，样式只维护一处。
# ⚠️ 这也意味着往 page.html 的 <style> 里加规则会**连带影响** /manual 与 /db 两页；
#    副页面自己专有的样式请写进它们自带的第二个 <style>。
#    （page.html 自身另有 _check_page.py R5 的 sha256 基线：故意改它要同步重算基线。）
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


def _page_style():
    """取出 page.html 的 <style> 块，供 manual / query 两个副页面注入。

    ⚠️ 用**文本模式**读再正则抽块（和 R5 的 sha256 校验同一口径）——
       本机 core.autocrlf=true 会让 git 检出成 CRLF，但文本模式读会把 CRLF 归一化成 LF，
       所以这里的抽取结果与哈希基线和换行符无关。
    """
    m = _STYLE_RE.search(_read_page_template())
    if not m:
        raise RuntimeError(f'ui/page.html 里找不到 <style> 块，无法给副页面注入样式：'
                           f'{_PAGE_TEMPLATE_PATH}')
    return m.group(1)


def _read_sub_template(path, name):
    """读副页面模板（manual / query 共用同一套「缺文件要显式报错」的处理）。"""
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError as e:
        raise RuntimeError(
            '{}模板读取失败：{}\n原因：{}\n'
            '（它随程序一起分发，请确认没被删除或改名）'.format(name, path, e)) from e


def _inject_page_style(html, path, name):
    """把 page.html 的样式注入副页面模板的 PAGE_CSS_PLACEHOLDER 位置。"""
    if PAGE_CSS_PLACEHOLDER not in html:
        raise RuntimeError(f'{path} 里没有 {PAGE_CSS_PLACEHOLDER} 占位符，'
                           f'{name}的样式无法注入（模板是不是被改坏了？）')
    return html.replace(PAGE_CSS_PLACEHOLDER, _page_style())


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
    return _read_sub_template(_MANUAL_TEMPLATE_PATH, '手动采集页')


def _build_manual_page():
    """构建手动采集页：把 page.html 的 <style> 整块注入，样式只维护一份。"""
    return _inject_page_style(_read_manual_template(), _MANUAL_TEMPLATE_PATH, '手动采集页')


# ⚠️ 同样必须放文件最后：_build_manual_page() 依赖 _read_manual_template 与 page.html 的样式块
MANUAL_HTML = _build_manual_page()


def _read_query_template():
    """读客户库查询页模板。缺文件时同样抛带绝对路径的错误。"""
    return _read_sub_template(_QUERY_TEMPLATE_PATH, '客户库查询页')


def _build_query_page():
    """构建客户库查询页：同样复用 page.html 的 <style> 块，样式只维护一份。"""
    return _inject_page_style(_read_query_template(), _QUERY_TEMPLATE_PATH, '客户库查询页')


QUERY_HTML = _build_query_page()
