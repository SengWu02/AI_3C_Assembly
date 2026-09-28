# -*- coding: utf-8 -*-
"""GUI 渲染截图测试：不弹窗口，跑一遍界面并导出 PNG 供检查"""
import sys

from dashboard import DashboardApp

app = DashboardApp()

stats = {
    1: {"name": "视觉检测", "ok": 23, "total": 24, "yield_pct": 95.8},
    2: {"name": "锁螺丝",   "ok": 24, "total": 24, "yield_pct": 100.0},
    3: {"name": "点胶",     "ok": 22, "total": 24, "yield_pct": 91.7},
    4: {"name": "成品检测", "ok": 18, "total": 24, "yield_pct": 75.0},
}

params = {
    "节拍等待": "2.5s",
    "锁螺丝X": 10000,
    "锁螺丝Z(接触/放料)": "8500/7000",
    "点胶X": 5000,
    "点胶Z": 7000,
    "回零前伸": "500 (1.9s)",
    "转盘A进料/停稳": "3.5/1.0s",
    "皮带2走带": "4.5s",
    "转盘B推料/稳定": "3.5/1.0s",
    "视觉等待": "6.0s",
    "LLM": "已激活",
}

app.set_step(3)          # 假装正在做步骤3
for i in range(8):
    app.update_data(
        production_count=24, target=50, station_stats=stats,
        llm_status="工作中", ai_score=82, alarm=False, cycle=i + 1,
        last_result=False,
        llm_decision="需要优化 -> continue | 调整: {cycle_time: 2.5}",
        cycle_time=52.0 - i * 0.7,
        params=params,
    )

app.log("系统启动 · 仪表盘就绪")
app.log("CYCLE_ADJUST: 节拍 3.0s -> 2.5s（LLM 决策）")
app.log("第23件完成 | 节拍 51.2s | OK")
app.log("LLM: 工位4 良率偏低，建议观察")

app.root.update()
app.root.update_idletasks()

# 导出 PNG
try:
    from PIL import ImageGrab
    x = app.root.winfo_rootx()
    y = app.root.winfo_rooty()
    w = app.root.winfo_width()
    h = app.root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    out = r"D:\AI factory\_recovery\gui_render.png"
    img.save(out)
    print("截图已保存:", out, img.size)
except Exception as e:
    print("截图失败（不影响 GUI 本身）:", e)

app.root.destroy()
print("GUI 渲染测试完成")