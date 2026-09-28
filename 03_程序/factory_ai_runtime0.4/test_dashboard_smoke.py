# -*- coding: utf-8 -*-
"""仪表盘冒烟测试：不弹窗口，直接实例化 + 刷新一遍，看有没有运行时错误"""
import sys

from dashboard import DashboardApp

ok = True
try:
    app = DashboardApp()
    print("1. 实例化          OK")
except Exception as e:
    print("1. 实例化          ★失败:", e)
    sys.exit(1)

stats = {
    1: {"name": "视觉检测", "ok": 10, "total": 10, "yield_pct": 100.0},
    2: {"name": "锁螺丝",   "ok": 10, "total": 10, "yield_pct": 100.0},
    3: {"name": "点胶",     "ok": 10, "total": 10, "yield_pct": 100.0},
    4: {"name": "成品检测", "ok": 7,  "total": 10, "yield_pct": 70.0},
}

try:
    for step in range(1, 6):
        app.set_step(step)
    app.set_step(0)
    print("2. set_step 1~5    OK")
except Exception as e:
    ok = False
    print("2. set_step        ★失败:", e)

try:
    for i in range(5):
        app.update_data(
            production_count=i + 1, target=10, station_stats=stats,
            llm_status="工作中", ai_score=88, alarm=False, cycle=i + 1,
            last_result=(i % 2 == 0),
            llm_decision="需要优化 -> continue",
            cycle_time=48.0 + i,
            params={"节拍": "3.0s", "锁螺丝臂X": "10000"},
        )
    app._refresh_ui()
    app._refresh_steps()
    app._draw_cycle_mini()
    print("3. update_data     OK")
except Exception as e:
    ok = False
    print("3. update_data     ★失败:", e)

try:
    app.log("测试日志第1行")
    app.log("测试日志第2行")
    app._refresh_log()
    print("4. log             OK")
except Exception as e:
    ok = False
    print("4. log             ★失败:", e)

try:
    app.root.update()          # 真正跑一次 Tk 事件循环（不阻塞）
    print("5. Tk update       OK")
except Exception as e:
    ok = False
    print("5. Tk update       ★失败:", e)

try:
    app.root.destroy()
except Exception:
    pass

print("")
print("结果:", "全部通过" if ok else "有失败项")