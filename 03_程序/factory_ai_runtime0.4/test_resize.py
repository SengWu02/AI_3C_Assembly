# -*- coding: utf-8 -*-
"""窗口缩放测试：验证窗口拉伸时画布图形和字号都跟着缩放"""
import tkinter as tk
from dashboard import DashboardApp

app = DashboardApp()
app.root.update_idletasks()
app.root.update()

# 记下初始状态
c = app.canvas
texts0 = [i for i in c.find_all() if c.type(i) == "text"]
print(f"画布 item 总数: {len(c.find_all())}   其中文字: {len(texts0)}")
if texts0:
    print(f"  首个文字字体: {c.itemcget(texts0[0], 'font')}")
    print(f"  首个文字坐标: {c.coords(texts0[0])}")

# 模拟窗口放大：直接改窗口尺寸并手动触发 Configure
print("")
print("--- 把窗口从 1256x900 放大到 1500x1050 ---")
app.root.geometry("1500x1050")
app.root.update_idletasks()
app.root.update()
# 手动触发一次 Configure（无头环境不一定自动触发）
class E: pass
e = E()
e.width = c.winfo_width()
e.height = c.winfo_height()
print(f"画布实际尺寸: {e.width} x {e.height}")
app._on_canvas_resize(e)
app.root.update()

print(f"  缩放比例 _last_scale = {getattr(app, '_last_scale', None)}")
if texts0:
    print(f"  缩放后首个文字字体: {c.itemcget(texts0[0], 'font')}")
    print(f"  缩放后首个文字坐标: {c.coords(texts0[0])}")

print("")
print("--- 缩回 1256x900 ---")
app.root.geometry("1256x900")
app.root.update_idletasks()
app.root.update()
e.width = c.winfo_width()
e.height = c.winfo_height()
app._on_canvas_resize(e)
app.root.update()
print(f"  缩放比例 _last_scale = {getattr(app, '_last_scale', None)}")
if texts0:
    print(f"  缩放后首个文字字体: {c.itemcget(texts0[0], 'font')}")

# 检查面板还在不在、位置对不对
print("")
px = app.manual_panel.winfo_rootx() - c.winfo_rootx()
py_ = app.manual_panel.winfo_rooty() - c.winfo_rooty()
pw = app.manual_panel.winfo_width()
print(f"人工面板: x={px} y={py_} w={pw}  画布宽={c.winfo_width()}")
print(f"  贴右上角: {'OK' if px + pw >= c.winfo_width() - 25 and py_ <= 25 else '★位置不对'}")

app.root.destroy()
print("")
print("完成")