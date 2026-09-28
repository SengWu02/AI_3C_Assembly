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
for a in sorted(used):
    has = hasattr(DashboardApp, a)
    print(f"    {'OK  ' if has else '★缺失'} app.{a}")

# 3) event_manager.sink 是否被赋值
if "sink" in src:
    print("")
    print("✓ main.py 里挂了 event_manager.sink（事件会进 GUI 日志栏）")
else:
    print("")
    print("★ main.py 没挂 event_manager.sink，事件不会进日志栏")