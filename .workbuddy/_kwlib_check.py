# -*- coding: utf-8 -*-
"""`关键词库.json` 结构 + 字节级约定校验（**只读**，退出码非 0 即失败）。

为什么需要它：这个文件的「格式约定」在功能上是不可见的 ——
    · 换行被双重转换（`\\r\\r\\n`）→ JSON 照样能解析、页面照样能用；
    · 误写 BOM → `json.load` 抛异常会被入口的 except 吞掉 → `/api/keywords` 返回 {}，
      页面只显示「暂无数据」，**一条日志都没有**；
    · 键顺序被打乱 → 前端按 `k[lang]` 取值也不受影响。
所以必须有一处显式断言把这些约定钉住，否则哪天被编辑器/脚本悄悄改了没人知道。

改前快照：`.workbuddy/_kwlib_before.json`（由 `_kwlib_add_plastic.py` 的同批步骤生成）。
缺快照时本脚本会**显式报错**而不是静默跳过 —— 否则「旧数据零改动」这条就形同虚设。

用法：
    D:\\waimao\\dp\\.venv\\Scripts\\python.exe .workbuddy\\_kwlib_check.py
"""
import collections
import io
import json
import os
import sys

ROOT = r'D:\waimao\dp'
P = os.path.join(ROOT, '关键词库.json')
BEFORE = os.path.join(ROOT, '.workbuddy', '_kwlib_before.json')

ORIG_IND = ['宠物用品', 'LED照明', '家具', '服装', '机械零部件', '户外用品', '食品']
NEW_IND = '塑料包装袋'
LANG9 = ['en', 'cn', 'de', 'fr', 'es', 'ar', 'it', 'nl', 'tr']
LANG10 = ['en', 'cn', 'de', 'fr', 'es', 'ar', 'fa', 'it', 'nl', 'tr']

errs = []


def chk(cond, msg):
    if not cond:
        errs.append(msg)


# ================= A. 字节级约定 =================
raw = io.open(P, 'rb').read()
chk(not raw.startswith(b'\xef\xbb\xbf'), '出现 UTF-8 BOM（json.load 会抛异常且被静默吞掉）')
chk(raw.count(b'\n') == raw.count(b'\r\n'), '存在裸 LF（换行约定被破坏）')
chk(b'\r\r' not in raw, '出现 \\r\\r —— 换行被双重转换了')
chk(not raw.endswith(b'\n'), '末尾多了换行（原文件无尾随换行）')
chk(b'\t' not in raw, '出现 Tab 缩进（原文件是 2 空格）')
chk(b'\\u' not in raw, '出现 \\uXXXX 转义 —— ensure_ascii 被打开了，中文/阿拉伯语原文丢失')

txt = raw.decode('utf-8')
for ln in txt.split('\r\n'):
    if ln.strip() and (len(ln) - len(ln.lstrip(' '))) % 2:
        errs.append(f'缩进不是 2 的倍数：{ln[:50]!r}')
        break

# ================= B. 可解析 + 规模 =================
d = json.loads(txt)
n_cat = sum(len(v) for v in d.values())
n_prod = sum(len(s) for v in d.values() for s in v.values())
n_item = sum(len(e) for v in d.values() for s in v.values() for e in s.values())
chk(len(d) == 8, f'行业数应为 8，实为 {len(d)}')
chk(n_cat == 14, f'品类数应为 14，实为 {n_cat}')
chk(n_prod == 40, f'产品数应为 40，实为 {n_prod}')
chk(n_item == 126, f'词条数应为 126，实为 {n_item}')

# ================= C. 字段键集合与顺序 =================
for ind, v in d.items():
    want = LANG10 if ind == '食品' else LANG9
    for c, subs in v.items():
        for p, lst in subs.items():
            for e in lst:
                if list(e.keys()) != want:
                    errs.append(f'{ind}/{c}/{p} 键序异常：{list(e.keys())}')
                    break
                if not all(isinstance(x, str) for x in e.values()):
                    errs.append(f'{ind}/{c}/{p} 有非字符串值')

# ================= D. 新行业质量 =================
new = d.get(NEW_IND)
chk(new is not None, f'缺少行业 {NEW_IND}')
if new:
    chk(list(new.keys()) == ['家用垃圾袋', '宠物清洁袋', '购物手挽袋', '拉链自封袋', '工业防护袋'],
        f'{NEW_IND} 的品类清单/顺序不符：{list(new.keys())}')
    for c, subs in new.items():
        for p, lst in subs.items():
            for e in lst:
                chk(e['en'].strip() != '', f'{NEW_IND}/{c}/{p} 有空 en')
                chk(e['cn'].strip() != '', f'{NEW_IND}/{c}/{p} 有空 cn')
                chk('|' not in e['en'] and '|' not in e['cn'], f'{NEW_IND}/{c}/{p} 出现 |')
                chk(e['en'].strip() == e['en'], f'{NEW_IND}/{c}/{p} en 首尾有空白')
                # 未补译的语言必须恰好是空的（不是漏键）
                for lg in ('de', 'fr', 'es', 'ar', 'it', 'nl', 'tr'):
                    chk(lg in e, f'{NEW_IND}/{c}/{p} 缺 {lg} 键（应存在且为空串）')
                chk('fa' not in e, f'{NEW_IND}/{c}/{p} 不该有 fa（只有食品是 10 键）')

# ================= E. en / cn 唯一性 =================
# ⚠️ 判据是「**行业内部**唯一」，不是全库唯一：
#    「猫砂盆衬袋」这类产品天然两栖（既是宠物用品，也是塑料袋厂的一条产品线），
#    跨行业重复是合理且有意为之的 —— 用户选了「塑料包装袋」就该在里面看到猫砂袋的词。
#    所以跨行业重叠只作为提示打印，不判失败；行业内部重复才是真的复制粘贴事故。
en_dup_errors, cross_overlap = [], []
for ind, v in d.items():
    seen = collections.Counter(
        e['en'] for s in v.values() for l in s.values() for e in l)
    for k, n in seen.items():
        if n > 1:
            en_dup_errors.append(f'{ind} 内部重复 en：{k} ×{n}')
chk(not en_dup_errors, '；'.join(en_dup_errors))

owner = collections.defaultdict(list)
for ind, v in d.items():
    for s in v.values():
        for l in s.values():
            for e in l:
                owner[e['en']].append(ind)
for k, inds in owner.items():
    uniq = sorted(set(inds))
    if len(uniq) > 1:
        cross_overlap.append(f'{k}  ← {" + ".join(uniq)}')

cn_dups = []
for ind, v in d.items():
    seen = collections.Counter(e['cn'] for s in v.values() for l in s.values() for e in l)
    for k, n in seen.items():
        if n > 1:
            cn_dups.append(f'{ind} 内部重复 cn：{k} ×{n}')
chk(not cn_dups, '；'.join(cn_dups))

# ================= F. 旧数据零改动（deep-diff） =================
if not os.path.exists(BEFORE):
    errs.append(f'缺少改前快照 {BEFORE} —— 无法验证旧数据未被改动（请勿静默跳过）')
else:
    before = json.loads(io.open(BEFORE, 'rb').read().decode('utf-8'))
    for k in ORIG_IND:
        chk(k in d, f'原行业 {k} 丢失')
        chk(d.get(k) == before.get(k), f'原行业 {k} 的内容被改动了')
        chk(list(d.get(k, {}).keys()) == list(before.get(k, {}).keys()),
            f'原行业 {k} 的品类顺序变了')
    chk(list(before.keys()) == ORIG_IND, f'改前快照本身就不含全部原行业：{list(before.keys())}')
chk(list(d.keys())[-1] == NEW_IND, f'新行业不在顶层末位（前端下拉顺序）：末位是 {list(d.keys())[-1]}')

# ================= 输出 =================
print('行业     :', ' / '.join(d.keys()))
for ind, v in d.items():
    print('  %-6s %d 品类 %3d 产品 %3d 词条' % (
        ind, len(v),
        sum(len(s) for s in v.values()),
        sum(len(l) for s in v.values() for l in s.values())))
print('合计     : %d 行业 / %d 品类 / %d 产品 / %d 词条' % (len(d), n_cat, n_prod, n_item))
print('\n字节约定 : 无 BOM=%s  纯 CRLF=%s  无末尾换行=%s  2 空格=%s' % (
    not raw.startswith(b'\xef\xbb\xbf'),
    raw.count(b'\n') == raw.count(b'\r\n'),
    not raw.endswith(b'\n'),
    b'\t' not in raw))

cover = collections.Counter()
for v in d.values():
    for s in v.values():
        for l in s.values():
            for e in l:
                for lang in LANG10:
                    if e.get(lang, '').strip():
                        cover[lang] += 1
print('\n语言覆盖（非空条数 —— 缺口就是待补译看板）：')
for lang in LANG10:
    gap = n_item - cover[lang]
    bar = '█' * int(cover[lang] / n_item * 30)
    print('  %-3s %4d / %-4d %s%s' % (lang, cover[lang], n_item, bar,
                                      '' if not gap else f'   缺 {gap}'))
if cross_overlap:
    print('\n跨行业重叠（正常，两栖产品；仅提示）：')
    for x in cross_overlap:
        print('   ·', x)

if errs:
    print('\n❌ 校验失败：')
    for e in errs:
        print('   -', e)
    sys.exit(1)
print('\n✅ 关键词库校验全部通过')
