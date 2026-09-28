# -*- coding: utf-8 -*-
"""接口一致性检查：确认 main.py 用的 GUI 方法都存在、参数名对得上"""
import ast
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard import DashboardApp

print("=" * 68)
print("接口一致性检查")
print("=" * 68)

# 1) update_data 的形参
sig = inspect.signature(DashboardApp.update_data)
params = set(sig.parameters.keys()) - {"self"}
print("")
print("DashboardApp.update_data 形参:")
print("   ", sorted(params))

# main.py 里实际传的键名（从源码里扫关键字参数）
src = open("main.py", encoding="utf-8").read()
tree = ast.parse(src)
passed = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "update_data":
            for kw in node.keywords:
                if kw.arg:
                    passed.add(kw.arg)
print("")
print(f"main.py 实际传的键 ({len(passed)}):")
print("   ", sorted(passed))

bad = passed - params
print("")
if bad:
    print("★ 传了界面不认识的参数:", sorted(bad))
else:
    print("✓ main.py 传的参数，界面全部都接受")

# 2) main.py 调用的所有 app.* 方法 / 属性
used = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "app":
            used.add(node.attr)
print("")
print(f"main.py 用到的 app.* ({len(used)}):")
# ★ 注意：on_set_cycle / cycle_entry 这些是【实例属性】（在 __init__ 里赋值的），
#   查 DashboardApp 这个【类】是查不到的 —— 必须实例化后再查。
#   （第一版就是查了类，误报一堆"缺失"。）
try:
    _inst = DashboardApp()
    _missing = []
    for a in sorted(used):
        has = hasattr(_inst, a)
        print(f"    {'OK  ' if has else '★缺失'} app.{a}")
        if not has:
            _missing.append(a)
    # 顺便确认人工介入的 5 个回调挂载点都在
    print("")
    print("人工介入回调挂载点:")
    for a in ("on_set_cycle", "on_stop", "on_resume", "on_pause", "on_continue"):
        has = hasattr(_inst, a) and a in ("on_set_cycle",)
        print(f"    {'OK  ' if hasattr(_inst, a) else '★缺失'} app.{a}")
    _inst.root.destroy()
except Exception as e:
    print("    ★ 实例化失败:", e)

# 3) event_manager.sink 是否被赋值
if "sink" in src:
    print("")
    print("✓ main.py 里挂了 event_manager.sink（事件会进 GUI 日志栏）")
else:
    print("")
    print("★ main.py 没挂 event_manager.sink，事件不会进日志栏")