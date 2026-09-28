# -*- coding: utf-8 -*-
"""GUI 布局几何验证：检查各面板是否超出窗口、有没有被裁掉"""
import tkinter as tk
from dashboard import DashboardApp

app = DashboardApp()
app.root.update_idletasks()
app.set_step(3)
app.update_data(production_count=24, target=50, station_stats={
    1: {"name": "视觉检测", "ok": 23, "total": 24, "yield_pct": 95.8},
    2: {"name": "锁螺丝", "ok": 24, "total": 24, "yield_pct": 100.0},
    3: {"name": "点胶", "ok": 22, "total": 24, "yield_pct": 91.7},
    4: {"name": "成品检测", "ok": 18, "total": 24, "yield_pct": 75.0},
}, llm_status="工作中", ai_score=82, alarm=False, cycle=5,
   cycle_time=51.2, params={"节拍等待": "2.5s", "LLM": "已激活"})
app.root.update()
app.root.update_idletasks()

print("窗口 请求尺寸:", app.root.winfo_reqwidth(), "x", app.root.winfo_reqheight())
print("窗口 实际尺寸:", app.root.winfo_width(), "x", app.root.winfo_height())

def chk(name, w):
    app.root.update_idletasks()
    print(f"{name:22} x={w.winfo_rootx()-app.root.winfo_rootx():5}  w={w.winfo_width():5}  "
          f"right={w.winfo_rootx()-app.root.winfo_rootx()+w.winfo_width():5}")

chk("canvas", app.canvas)
chk("step_panel 容器", app.step_rows[0]["dot"].master.master)
chk("cycle_mini", app.cycle_mini)
chk("log_text", app.log_text)
chk("llm_decision_label", app.llm_decision_label)

rw = app.root.winfo_rootx()
print("")
print("各控件右边界应 <= 窗口宽度", app.root.winfo_width())
for nm, w in [("canvas", app.canvas), ("cycle_mini", app.cycle_mini),
              ("log_text", app.log_text)]:
    right = w.winfo_rootx() - rw + w.winfo_width()
    print(f"  {nm:14} 右边界 {right:5}  " + ("OK" if right <= app.root.winfo_width() else "★超出"))

app.root.destroy()