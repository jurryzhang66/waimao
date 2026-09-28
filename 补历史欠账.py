# -*- coding: utf-8 -*-
"""补历史欠账：把客户库里「邮箱和电话都为空」的站点批量访问一遍，抓邮箱/电话并评分。

什么时候用：
  - 老版本（搜索与补全分开时）搜到的记录，当年没补到联系方式；
  - 以前访问过、但一个联系方式都没抓到的站，想再试一次。
「开始搜索」现在已经自带就地抓取，所以正常使用流程不需要跑这个脚本。

用法（在本目录下打开命令行）：
    python 补历史欠账.py            # 开始补，结束会写出结果 Excel
    python 补历史欠账.py --dry      # 只列出有多少条待补，不访问任何网站

也可以直接双击「补历史欠账.bat」，效果一样。
跑的过程中可以 Ctrl+C 中断，已抓到的记录会照常落盘、写进客户库。
"""
import importlib.util
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, '客户开发工具.py')


def load_tool():
    """加载主工具模块。用 importlib 而不是 import，避免主工具里启动 Flask 服务。"""
    spec = importlib.util.spec_from_file_location('kf', SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['kf'] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    dry = ('--dry' in sys.argv) or ('--dry-run' in sys.argv)
    kf = load_tool()

    items = kf._enrich_worklist()
    if not items:
        print('客户库里没有「邮箱和电话都为空」的记录，无需补全。')
        return
    print(f'待补全 {len(items)} 个网站（客户库里的历史欠账）')
    if dry:
        for i, it in enumerate(items[:30], 1):
            print(f'  {i:>3}. {it["url"]}')
        if len(items) > 30:
            print(f'  ... 其余 {len(items) - 30} 个略')
        print('\n--dry 模式：未访问任何网站。去掉该参数即开始补全。')
        return

    eta = max(1, len(items) * 12 // 60)
    print(f'开始补全，预计约 {eta} 分钟（Ctrl+C 可随时中断，已抓到的会落盘）…\n')
    try:
        n = kf.enrich_core(industry='')
    except KeyboardInterrupt:
        print('\n已中断（已抓到的记录已写进客户库并落盘）')
        return
    print(f'\n完成：本次处理 {n} 条。')
    print(f'结果文件：{kf.ENRICH_FILE}')


if __name__ == '__main__':
    main()
