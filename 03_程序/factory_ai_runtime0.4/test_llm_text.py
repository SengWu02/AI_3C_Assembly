# -*- coding: utf-8 -*-
"""测试 LLM 决策 -> 人话 的翻译函数

main.py 顶层有 input()、连 PLC、起线程，不能直接 import。
所以用 AST 把这个函数单独抽出来执行（只取函数定义，不跑模块级代码）。
"""
import ast
import os
import sys

MAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
src = open(MAIN, encoding="utf-8").read()
tree = ast.parse(src)

WANT = {"_llm_decision_to_human"}
parts = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANT:
        parts.append(ast.get_source_segment(src, node))

if not parts:
    print("STAR: 没找到 _llm_decision_to_human")
    sys.exit(1)

ns = {}
exec("\n\n".join(parts), ns)
fn = ns["_llm_decision_to_human"]

print("=" * 70)
print("LLM 决策 -> 人话 翻译测试")
print("=" * 70)

OK3 = {"良品": 18, "不良": 5, "漏料": 1}
cases = [
    ("正常 + 继续", "正常", ["continue"], {}, 3.0, 3.0,
     {"良品": 10, "不良": 0, "漏料": 0}, 100.0, 1.5),
    ("需要优化 + 压节拍", "需要优化", ["continue"], {"cycle_time": 2.5}, 3.0, 2.5,
     OK3, 75.0, 1.2),
    ("异常 + 报警 + 停线", "异常", ["alarm_on", "stop"], {}, 3.0, 3.0,
     {"良品": 3, "不良": 20, "漏料": 7}, 10.0, 0.3),
    ("建议值与当前接近", "需要优化", ["continue"], {"cycle_time": 3.1}, 3.0, 3.0,
     {"良品": 5, "不良": 1, "漏料": 0}, 83.3, 0.9),
    ("无三分类数据", "正常", [], {}, 3.0, 3.0, None, 100.0, 2.0),
    ("未知 assessment", "说不清楚", ["continue"], {}, 3.0, 3.0,
     {"良品": 1, "不良": 0, "漏料": 0}, 100.0, 1.0),
]

MACHINE_TOKENS = ["{", "}", "None", "continue", "rotate",
                  "alarm_on", "alarm_off", "cycle_time", "assessment"]

bad_n = 0
for desc, assess, acts, adj, cb, ca, vc, yld, eff in cases:
    mood, detail = fn({}, assess, acts, adj, cb, ca, vc, yld, eff)
    print("")
    print("[" + desc + "]")
    print("  " + mood + "｜" + detail)
    bad = [t for t in MACHINE_TOKENS if (t in detail or t in mood)]
    if bad:
        bad_n += 1
        print("  STAR 还残留机器味: " + str(bad))
    else:
        print("  OK   全是人话")

print("")
print("=" * 70)
print("完成，含机器味的用例数: " + str(bad_n))