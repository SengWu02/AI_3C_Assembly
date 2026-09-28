# -*- coding: utf-8 -*-
"""人工介入面板测试：验证 GUI 按钮 -> 回调 -> 产线状态 的完整链路"""
import sys

from dashboard import DashboardApp
from safety_manager import SafetyManager

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
        print(f"  OK    {name} {detail}")
    else:
        fail_n += 1
        print(f"  ★失败 {name} {detail}")


print("=" * 68)
print("人工介入测试")
print("=" * 68)

# ---------- 1. SafetyManager 的人工状态 ----------
print("")
print("[1] SafetyManager 人工状态")
sm = SafetyManager()
check("初始未停线", not sm.is_stopped())

sm.request_stop()
check("request_stop 后 is_stopped", sm.is_stopped())
check("manual_stop 标志置位", sm.manual_stop)

# ★ 关键：evaluate() 不能把人工停线清掉（这是本次修的核心问题）
sm.evaluate({"is_blocked": False}, {"push_timeout": False})
check("evaluate 后人工停线仍在（不被自动复位）", sm.is_stopped(),
      f"(manual_stop={sm.manual_stop}, emergency_stop={sm.emergency_stop})")

sm.clear_stop()
check("clear_stop 后恢复", not sm.is_stopped())
sm.evaluate({"is_blocked": False}, {"push_timeout": False})
check("恢复后仍是运行态", not sm.is_stopped())

# 自动检测仍然有效
sm.evaluate({"is_blocked": True}, {"push_timeout": False})
check("卡堵仍能触发停线", sm.is_stopped())
sm.evaluate({"is_blocked": False}, {"push_timeout": False})
check("卡堵解除后自动恢复", not sm.is_stopped())

# 暂停
sm.request_pause()
check("request_pause 置位", sm.is_paused())
check("暂停不等于停线", not sm.is_stopped())
sm.clear_pause()
check("clear_pause 解除", not sm.is_paused())

# ---------- 2. GUI 面板控件存在 ----------
print("")
print("[2] GUI 人工面板")
app = DashboardApp()
check("面板已创建", hasattr(app, "manual_panel"))
check("节拍输入框存在", hasattr(app, "cycle_entry"))
check("状态标签存在", hasattr(app, "manual_status"))
check("节拍输入框预填了当前值",
      app.cycle_entry.get().strip() != "", f"(当前值 {app.cycle_entry.get()!r})")

# ---------- 3. 节拍设定的校验 ----------
print("")
print("[3] 节拍校验")
app.on_set_cycle = None      # 先不接产线，只测校验

for raw, should_pass in [("3.0", True), ("1.5", True), ("8.0", True),
                         ("abc", False), ("99", False), ("0.2", False)]:
    app.cycle_entry.delete(0, "end")
    app.cycle_entry.insert(0, raw)
    app._cb_set_cycle()
    note = app.manual_status.cget("text")
    if should_pass:
        ok = ("未接入" in note or "已设" in note)
    else:
        ok = ("★" in note)
    check(f"输入 {raw!r} -> {note[:28]}", ok)

# ---------- 4. 回调链路 ----------
print("")
print("[4] 回调链路（模拟 main.py 挂上来的函数）")
called = []
app.on_set_cycle = lambda s: called.append(("cycle", s))
app.on_stop = lambda: called.append(("stop", None))
app.on_resume = lambda: called.append(("resume", None))
app.on_pause = lambda: called.append(("pause", None))
app.on_continue = lambda: called.append(("cont", None))

app.cycle_entry.delete(0, "end")
app.cycle_entry.insert(0, "4.5")
app._cb_set_cycle()
check("设定节拍回调被调用", ("cycle", 4.5) in called, f"({called})")

app._cb_resume()
check("恢复回调被调用", ("resume", None) in called)
app._cb_pause()
check("暂停回调被调用", ("pause", None) in called)
app._cb_continue()
check("继续回调被调用", ("cont", None) in called)

# ---------- 5. 未接回调时不崩 ----------
print("")
print("[5] 没接回调时点按钮（只看界面 / 测试场景）")
app.on_set_cycle = None
app.on_resume = None
app.on_pause = None
app.on_continue = None
for cb, nm in [(app._cb_set_cycle, "设定节拍"), (app._cb_resume, "恢复"),
               (app._cb_pause, "暂停"), (app._cb_continue, "继续")]:
    try:
        cb()
        check(f"{nm} 未接回调不崩", True, f"-> {app.manual_status.cget('text')[:26]}")
    except Exception as e:
        check(f"{nm} 未接回调不崩", False, str(e))

# ---------- 6. 面板位置（右上角）----------
print("")
print("[6] 面板位置")
app.root.update_idletasks()
px = app.manual_panel.winfo_rootx() - app.canvas.winfo_rootx()
py_ = app.manual_panel.winfo_rooty() - app.canvas.winfo_rooty()
pw = app.manual_panel.winfo_width()
cw = app.canvas.winfo_width()
check("面板贴着画布右侧", px + pw >= cw - 20,
      f"(面板右边界 {px+pw}, 画布宽 {cw})")
check("面板贴着画布顶部", py_ <= 20, f"(面板 y={py_})")

# ---------- 7. 窗口可调整 ----------
print("")
print("[7] 窗口可调整大小")
check("resizable 为 True", app.root.resizable() == (1, 1),
      f"(实际 {app.root.resizable()})")

app.root.destroy()

print("")
print("=" * 68)
print(f"结果: 通过 {pass_n} / 失败 {fail_n}")
print("=" * 68)