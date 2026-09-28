# -*- coding: utf-8 -*-
"""★ 静态检查：函数里有没有"用了但没定义"的名字（NameError 的根源）

为什么需要：
    ast 只查语法。"start = time.time() 被注释块盖掉"这种错，
    语法完全合法，但一跑就 NameError，而且是在生产线程里崩 —— 很难发现。

做法：
    用标准库 symtable 分析每个函数的符号表：
      · 找出所有【被读取】的名字
      · 逐个判断它是不是"局部变量 / 参数 / 全局变量 / 内置函数"
      · 都不是 -> 就是未定义，运行时必然 NameError

这个检查不需要执行代码，所以没有死循环/连设备的风险。
"""
import ast
import builtins
import glob
import os
import symtable
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def collect_star_import_names(tree, base_dir):
    """★ 解析 from X import * 导入的名字。

    为什么必须做：main.py 用的是 from config import *，
    所以 config.py 里的常量（BELT_0_COIL 等）在 main.py 里是"全局名字"，
    但在这个文件里没有任何赋值语句。不解析星号导入就会把几百个常量
    全报成"未定义" —— 那是误报，会把真正的问题淹没。
    （第一版就是这样：314 条报告里几乎全是误报。）
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not any(a.name == "*" for a in node.names):
                continue
            mod_path = os.path.join(base_dir, node.module + ".py")
            if not os.path.exists(mod_path):
                continue
            try:
                sub = ast.parse(open(mod_path, encoding="utf-8").read())
                # 只看模块级、不带下划线的名字（星号导入不会导入 _ 开头的）
                for n in sub.body:
                    if isinstance(n, ast.Assign):
                        for t in n.targets:
                            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                                out.add(t.id)
                    elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                        if not n.name.startswith("_"):
                            out.add(n.name)
                    elif isinstance(n, ast.AnnAssign):
                        if isinstance(n.target, ast.Name) \
                                and not n.target.id.startswith("_"):
                            out.add(n.target.id)
                # 星号导入的模块自己也可能有星号导入 -> 递归一层
                out |= collect_star_import_names(sub, base_dir)
            except Exception:
                pass
    return out


def collect_module_globals(tree):
    """收集模块级定义的全局名字（含 import、赋值、def、class）"""
    names = set()
    # __file__ / __name__ 这类是模块自带的内置属性
    names.update({"__file__", "__name__", "__doc__", "__package__",
                  "__spec__", "__loader__", "__builtins__"})
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            t = getattr(node, "target", None)
            if isinstance(t, ast.Name):
                names.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.For):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    names.add(n.id)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.add(node.name)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            names.add(n.id)
        elif isinstance(node, ast.Global):
            for n in node.names:
                names.add(n)
    return names


def scan_file(path):
    """返回 [(函数名, 行号, 未定义的名字), ...]"""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    gnames = collect_module_globals(tree)
    # ★ 加上 from X import * 带进来的名字
    gnames |= collect_star_import_names(tree, os.path.dirname(os.path.abspath(path)))
    bnames = set(dir(builtins))
    st = symtable.symtable(src, path, "exec")
    problems = []

    def line_of(fname):
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fname:
                return n.lineno
        return 0

    def walk(table, indent_hint):
        for sym in table.get_symbols():
            name = sym.get_name()
            # 只关心"被读取"的名字
            if not sym.is_referenced():
                continue
            # 局部有的就没事
            if sym.is_assigned() or sym.is_parameter() or sym.is_imported():
                continue
            if sym.is_free():
                continue          # 闭包变量，外层的局部，归外层管
            # ★★★ 关键（2026-09-28 踩的坑）★★★
            #  Python 3.14 里，函数内"没赋值、只读取"的名字会被标成 is_global()=True，
            #  也就是"它要去全局找"。所以【不能一看 global 就放过】——
            #  正相反，这类名字恰恰是要检查的重点：
            #     它必须在模块级真的有定义，或者是个内置函数，否则运行时 NameError。
            #  （第一版就是"看到 global 就 continue"，导致完全抓不到 bug，
            #    对着故意写错的样本还报 0 问题 —— 假通过。）
            if name in gnames or name in bnames:
                continue
            problems.append((table.get_name(), line_of(table.get_name()), name))
        for child in table.get_children():
            walk(child, indent_hint + 1)

    walk(st, 0)
    return problems


targets = sys.argv[1:] or [HERE]
files = []
for t in targets:
    if os.path.isdir(t):
        files.extend(sorted(glob.glob(os.path.join(t, "*.py"))))
    else:
        files.append(t)

print("=" * 72)
print("未定义名字检查（NameError 的静态排查）")
print("=" * 72)

total = 0
badfiles = 0
for f in files:
    try:
        probs = scan_file(f)
    except SyntaxError as e:
        print("STAR " + os.path.basename(f) + " 语法错误 line " + str(e.lineno))
        badfiles += 1
        continue
    # 去掉重复（同一个名字在多个作用域重复报）
    seen = set()
    uniq = []
    for fn, ln, nm in probs:
        key = (fn, nm)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((fn, ln, nm))
    if uniq:
        badfiles += 1
        print("")
        print(os.path.basename(f) + ":")
        for fn, ln, nm in uniq:
            total += 1
            print("    L" + str(ln) + "  " + fn + "()  用了未定义的名字: " + nm)

print("")
print("=" * 72)
print("检查文件数: " + str(len(files)) + "   有问题的文件: " + str(badfiles)
      + "   未定义名字总数: " + str(total))
print("=" * 72)