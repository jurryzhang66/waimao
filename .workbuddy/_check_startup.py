# -*- coding: utf-8 -*-
"""真机启动校验：端口不写死后，工具能否自动避开被系统保留的端口并真的起来。

分两段：
  A. 进程内单测 `pick_port()` —— 确认它跳过被系统保留的端口，且返回的端口真的能 bind。
  B. 真机起一次 —— 用子进程跑主工具的 `__main__`（把 webbrowser.open 打桩，避免弹窗），
     从 stdout 抓出真实 URL，再真的发一次 HTTP 请求确认页面在线，最后关掉。
"""
import importlib.util
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request

SRC = r'D:\waimao\dp\客户开发工具.py'
PY = r'D:\waimao\dp\.venv\Scripts\python.exe'

spec = importlib.util.spec_from_file_location('kf', SRC)
m = importlib.util.module_from_spec(spec)
sys.modules['kf'] = m
spec.loader.exec_module(m)


def can_bind(port, host='127.0.0.1'):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


print('================ A. pick_port 单测 ================')
print('候选端口：', m.PREFERRED_PORTS)
for p in m.PREFERRED_PORTS:
    print(f'   本机 {p:5d} 可直接 bind：{can_bind(p)}')

port, reason = m.pick_port('127.0.0.1')
print(f'pick_port() → 端口 {port}；换端口说明：{reason!r}')
assert can_bind(port), f'pick_port 返回的 {port} 其实绑不上'
assert port in m.PREFERRED_PORTS, f'{port} 不在候选列表里，说明挑选逻辑有问题'
# 只有「第一个候选真的绑不上」时才该带换端口说明；候选表首位能绑就该是空说明。
if not can_bind(m.PREFERRED_PORTS[0]):
    assert reason, f'{m.PREFERRED_PORTS[0]} 绑不上，应当给出换端口的说明'
else:
    assert not reason, f'第一个候选就能绑，不该有换端口说明：{reason!r}'

# 逐项验证：它确实是从候选列表里挑「第一个能 bind 的」
expect = next(p for p in m.PREFERRED_PORTS if can_bind(p))
assert port == expect, f'应挑中候选里第一个可用的 {expect}，实际挑了 {port}'
if not can_bind(5000):
    assert port != 5000, '5000 绑不上却仍选了 5000'
    # ⚠️ 只断言「拿到了一个真实的操作系统错误原因」，**不要**写死 10013。
    #    5000 绑不上的成因随机器状态漂移：落在 Hyper-V/WinNAT 保留段 → 10013（权限不允许），
    #    而只要有别的进程真占着它 → 10048（地址已被使用）。2026-09-30 实测两种都出现过。
    assert ('WinError' in reason or '权限' in reason), f'换端口原因不对：{reason}'
    print(f'  ✓ 5000 绑不上（{reason.strip()[:40]}…）→ 已自动顺延')
print(f'  ✓ 自动挑中的端口 {port} 实测可 bind')

# 候选全不可用时必须退回「系统分配」而不是崩掉
# ⚠️ 别用固定端口当「不可用候选」：Windows 保留段每次开机漂移，昨天被保留的 5011
#    今天可能就能 bind（2026-09-29 实测 5011/5050 都可绑，保留段变成 4710-4809/
#    4910-5009/5110-5209/5357/12125-12792…）→ 写死 (5000,5011,5050) 会随机器状态翻车。
#    改成「现场占住 3 个临时端口」，无论哪天跑都确定不可用。
holders, busy = [], []
for _ in range(3):
    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _s.bind(('127.0.0.1', 0))
    _s.listen(1)
    busy.append(_s.getsockname()[1])
    holders.append(_s)
try:
    p_all, r_all = m.pick_port('127.0.0.1', preferred=tuple(busy))
finally:
    for _s in holders:
        _s.close()
print(f'  · 候选 {tuple(busy)} 全被占用时 → {p_all}（{r_all!r}）')
assert can_bind(p_all), f'兜底端口 {p_all} 绑不上'
assert p_all not in busy, '兜底不该再挑回已被占用的端口'
assert r_all, '兜底时应给出说明'
print('  ✓ 候选全不可用 → 退回系统分配的空闲端口，且不重蹈已占用端口')

print('\n================ B. 真机启动 e2e ================')
BOOT = ("import runpy,sys,webbrowser;"
        "webbrowser.open=lambda *a,**k: True;"
        "sys.argv=[r'%s'];" % SRC +
        "runpy.run_path(r'%s', run_name='__main__')" % SRC)

env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
proc = subprocess.Popen([PY, '-c', BOOT], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, env=env)

lines = []
q = queue.Queue()


def pump():
    for raw in proc.stdout:
        q.put(raw.decode('utf-8', 'replace').rstrip())


threading.Thread(target=pump, daemon=True).start()

url = None
try:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            line = q.get(timeout=1)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        if line:
            lines.append(line)
            print('   子进程>', line)
        mm = re.search(r'(http://127\.0\.0\.1:(\d+)/)', line)
        if mm:
            url, got_port = mm.group(1), int(mm.group(2))
            break

    assert url, '没从输出里拿到 URL —— 工具没起来。子进程输出：\n  ' + '\n  '.join(lines)
    # ⚠️ 这里原来是 `assert got_port != 5000, '本机 5000 被系统保留，不该还去用 5000'`。
    #    那是一句**环境快照**：5000 在不在 Windows 的 TCP 排除区间里，会随 Hyper-V/WinNAT
    #    的状态漂移（重启、系统更新后就不一样）。本次复现时 `netsh int ipv4 show
    #    excludedportrange protocol=tcp` 已经没有 5000（最早的一段是 5357），5000 能正常
    #    bind，于是工具按设计挑中 5000，而这条断言却把「环境变好了」判成失败 —— 典型假红
    #    （与 MEMORY.md 里「别写死端口原因 10013」同一类毛病）。
    #    真正要守的不变量是「pick_port 挑出来的端口必须真的能用」，由下面两条断言覆盖：
    assert can_bind(got_port), f'输出的端口 {got_port} 实际绑不上'

    # 等 Flask 真正 listening
    body = None
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                assert r.status == 200, f'HTTP {r.status}'
                body = r.read().decode('utf-8', 'replace')
            break
        except Exception:
            if proc.poll() is not None:
                raise
            time.sleep(0.5)
    assert body, f'URL {url} 打不开'
    assert 'mapsCity' in body, '页面内容不像主工具（缺少地图城市框）'
    print(f'  ✓ 自动端口 {got_port} 的页面已在线，HTTP 200，长度 {len(body)}')
finally:
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

print('\n✅ 启动端口自动避让 校验全部通过')
print(f'   本机实际会用：{url}（5000 被 Windows 保留，已自动顺延）')
