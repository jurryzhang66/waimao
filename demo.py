# -*- coding: utf-8 -*-
"""诊断脚本：检查 PyCharm 环境和浏览器启动"""
import sys
print('当前使用的 Python：', sys.executable)

try:
    import DrissionPage
    print('DrissionPage 版本：', DrissionPage.__version__)
except ImportError as e:
    print('【问题】DrissionPage 没有安装在当前解释器里：', e)
    sys.exit()

from DrissionPage import ChromiumPage
print('正在启动浏览器，请稍候...')
page = ChromiumPage()
print('浏览器已启动，正在打开百度...')
page.get('https://www.baidu.com')
print('页面标题：', page.title)
input('按回车键关闭浏览器...')  # 等你手动确认，不会自动关闭
page.quit()