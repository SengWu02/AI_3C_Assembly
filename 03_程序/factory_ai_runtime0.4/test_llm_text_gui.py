# -*- coding: utf-8 -*-
"""检查 LLM 长文本在 GUI 上的显示效果（会不会被截掉）"""
import tkinter as tk
from dashboard import DashboardApp

app = DashboardApp()
app.root.update_idletasks()

long_text = ("产线需要优化｜已生产 24 件（良品 18、不良 5、漏料 1）；"
             "良率 75.0%；效率 1.2 件/分；动作：继续生产；节拍压快：3.0s → 2.5s")
app.update_data(production_count=24, target=50, station_stats={},
                llm_status="工作中", ai_score=82, alarm=False, cycle=5,
                llm_decision=long_text,
                verdict_counts={"良品": 18, "不良": 5, "漏料": 1})
app._drain_queue()      # ★ update_data 是进队列的，测试里要手动消费
app.root.update()

print("LLM 决策栏文本长度:", len(app.llm_decision_label.cget("text")))
print("  栏宽:", app.llm_decision_label.winfo_width(), "px")
needed = app.llm_decision_label.winfo_reqwidth()
print("  文本需要:", needed, "px")
if needed > app.llm_decision_label.winfo_width():
    print("  ★ 会被截断！需要缩短或加自动换行")
else:
    print("  OK 能完整显示")

print("")
print("三分类显示:")
print("  ", app.verdict_label.cget("text"))
print("  ", app.verdict_yield.cget("text"),
      "  颜色:", app.verdict_yield.cget("fg"))

# 极短窗口下也要能看
app.root.geometry("1050x760")
app._drain_queue()
app.root.update_idletasks()
app.root.update()
print("")
print("最小窗口下 LLM 决策栏：")
print("  栏宽:", app.llm_decision_label.winfo_width(), "px")
wrapped = app.llm_decision_label.cget("wraplength")
print("  wraplength:", wrapped)

app.root.destroy()