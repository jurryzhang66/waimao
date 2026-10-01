# -*- coding: utf-8 -*-
"""全量回归驱动：按固定清单跑所有回归脚本，产出 _reg__<名字>.log 与一张结果表。

清单就是 .workbuddy 里那一组「回归验证脚本」，加上项目根的 补历史欠账.py --dry。
每项都是独立子进程，退出码 0 才算过；任何一项非 0，整个驱动最后返回 1。

⚠️ 其中 `_check_db_keys` 与 `补历史欠账 --dry` 是**刻意扫真实客户库**的（其余项都把
   `core.db.db_path` 打进临时目录）→ 它们只读、不写库；红了多半是真实数据需要人工修，
   别顺手把断言改松。

用法：python .workbuddy/_run_all_reg.py
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BK = os.path.join(ROOT, '.workbuddy')
PY = r'D:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe'
NODE = r'C:\Users\admin\.workbuddy\binaries\node\versions\22.22.2-3\node.exe'

# (名字, 解释器, 相对路径, 附加参数)
ITEMS = [
    ('_check_page',            PY,   '.workbuddy/_check_page.py',            []),
    ('_check_startup',         PY,   '.workbuddy/_check_startup.py',         []),
    ('_kwlib_check',           PY,   '.workbuddy/_kwlib_check.py',           []),
    ('_check_industry_rules',  PY,   '.workbuddy/_check_industry_rules.py',  []),
    ('_verify_maps_base',      PY,   '.workbuddy/_verify_maps_base.py',      []),
    ('_smoke_search',          PY,   '.workbuddy/_smoke_search.py',          []),
    ('_smoke_maps',            PY,   '.workbuddy/_smoke_maps.py',            []),
    ('_smoke_collect',         PY,   '.workbuddy/_smoke_collect.py',         []),
    ('_smoke_manual_session',  PY,   '.workbuddy/_smoke_manual_session.py',  []),
    ('_smoke_query',           PY,   '.workbuddy/_smoke_query.py',           []),
    ('_check_feishu_records',  PY,   '.workbuddy/_check_feishu_records.py',  []),
    ('_check_maps_ui',         PY,   '.workbuddy/_check_maps_ui.py',         []),
    ('_check_kwlib_ui',        PY,   '.workbuddy/_check_kwlib_ui.py',        []),
    ('_check_live_ui',         PY,   '.workbuddy/_check_live_ui.py',         []),
    ('_check_manual_ui',       PY,   '.workbuddy/_check_manual_ui.py',       []),
    ('_check_query_ui',        PY,   '.workbuddy/_check_query_ui.py',        []),
    ('_check_ext',             PY,   '.workbuddy/_check_ext.py',             []),
    ('_smoke_ext_content',     NODE, '.workbuddy/_smoke_ext_content.js',     []),
    ('_smoke_ext_popup',       NODE, '.workbuddy/_smoke_ext_popup.js',       []),
    ('_smoke_ext_live',        PY,   '.workbuddy/_smoke_ext_live.py',        []),
    # ⚠️ 这两项是刻意扫**真实库**的（其它项都把 db_path 打进临时目录）→ 只读、失败要人工处理
    ('_check_db_keys',         PY,   '.workbuddy/_check_db_keys.py',         []),
    ('补历史欠账 --dry',        PY,   '补历史欠账.py',                        ['--dry']),
]


def main():
    only = sys.argv[1:]
    rows = []
    t_all = time.time()
    for name, interp, rel, extra in ITEMS:
        if only and not any(o in name for o in only):
            continue
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            rows.append((name, 'MISSING', 0.0, '文件不存在：' + rel))
            print(f'❌ {name:24s} MISSING  {rel}')
            continue
        log_path = os.path.join(BK, '_reg__' + name.replace(' ', '_').replace('--', '').strip('_') + '.log')
        t0 = time.time()
        cmd = [interp, '-X', 'utf8', path] + extra if interp == PY else [interp, path] + extra
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', cwd=ROOT, timeout=900)
        dt = time.time() - t0
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('$ ' + ' '.join(cmd) + '\n')
            f.write(f'EXIT={r.returncode}  用时 {dt:.1f}s\n')
            f.write('=' * 70 + '\n' + (r.stdout or '') + '\n' + '-' * 70 + '\n' + (r.stderr or ''))
        mark = 'EXIT=0 ' if r.returncode == 0 else f'EXIT={r.returncode}'
        print(f'{"✅" if r.returncode == 0 else "❌"} {name:24s} {mark:8s} {dt:6.1f}s   {os.path.basename(log_path)}')
        rows.append((name, mark, dt, os.path.basename(log_path)))

    bad = [r for r in rows if r[1] != 'EXIT=0 ']
    print('\n' + '=' * 74)
    print(f'共 {len(rows)} 项，通过 {len(rows) - len(bad)} 项，用时 {time.time() - t_all:.1f}s')
    if bad:
        print('未通过：')
        for name, mark, _, log in bad:
            print(f'   · {name}  {mark}  → .workbuddy/{log}')
        return 1
    print('✅ 全部 EXIT=0')
    return 0


if __name__ == '__main__':
    sys.exit(main())
