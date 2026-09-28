"""
3C 组装岛 · GUI 仪表盘

独立进程，定时读取 shared_data.json，只渲染不修改数据。
"""

import json
import os
import threading
import time
import tkinter as tk
from tkinter import ttk

DATA_FILE = os.path.join(os.path.dirname(__file__), "shared_data.json")


def load_data():
    """读取 shared_data.json，失败返回空字典"""
    try:
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


class AssemblyDashboard:
    """环岛 GUI 仪表盘"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("3C 组装岛 · 实时仪表盘")
        self.root.geometry("600x400")
        self.root.resizable(False, False)

        # 标题
        title = tk.Label(self.root, text="3C 组装岛", font=("微软雅黑", 18, "bold"))
        title.pack(pady=(12, 4))

        self.cycle_label = tk.Label(self.root, text="周期: --", font=("微软雅黑", 10))
        self.cycle_label.pack()

        # 工位状态区域
        self.station_frame = tk.Frame(self.root)
        self.station_frame.pack(pady=10)

        self.station_widgets = {}
        station_names = {1: "视觉检测", 2: "锁螺丝", 3: "点胶", 4: "成品检测"}
        colors = {1: "#e74c3c", 2: "#2ecc71", 3: "#3498db", 4: "#f1c40f"}

        for sid in range(1, 5):
            frame = tk.Frame(self.station_frame, borderwidth=1, relief="solid", padx=8, pady=4)
            frame.pack(fill="x", pady=2)

            name_label = tk.Label(frame, text=f"工位{sid} {station_names[sid]}", font=("微软雅黑", 10, "bold"), width=14, anchor="w")
            name_label.pack(side="left")

            bar_canvas = tk.Canvas(frame, width=200, height=20, bg="#ecf0f1", highlightthickness=0)
            bar_canvas.pack(side="left", padx=8)

            pct_label = tk.Label(frame, text="--%", font=("微软雅黑", 10), width=6)
            pct_label.pack(side="left")

            self.station_widgets[sid] = {
                "canvas": bar_canvas,
                "pct_label": pct_label,
                "color": colors.get(sid, "#000000"),
            }

        # 分隔线
        sep = tk.Frame(self.root, height=1, bg="#bdc3c7")
        sep.pack(fill="x", padx=20, pady=6)

        # 底部状态
        bottom = tk.Frame(self.root)
        bottom.pack(fill="x", padx=20)

        self.production_label = tk.Label(bottom, text="产量: --/--", font=("微软雅黑", 12, "bold"))
        self.production_label.pack(side="left", padx=(0, 20))

        self.llm_label = tk.Label(bottom, text="LLM: --", font=("微软雅黑", 12))
        self.llm_label.pack(side="left", padx=(0, 20))

        self.score_label = tk.Label(bottom, text="AI分: --", font=("微软雅黑", 12))
        self.score_label.pack(side="left", padx=(0, 20))

        self.alarm_label = tk.Label(bottom, text="", font=("微软雅黑", 12, "bold"))
        self.alarm_label.pack(side="left")

        # 启动定时刷新
        self.update_loop()

    def update_loop(self):
        """每500ms读取一次数据刷新界面"""
        data = load_data()
        if data:
            self._update_stations(data.get("stations", {}))
            self._update_status(data)

        self.root.after(500, self.update_loop)

    def _update_stations(self, stations: dict):
        """更新工位状态条"""
        for sid, widget in self.station_widgets.items():
            s = stations.get(str(sid), {})
            total = s.get("total", 0)
            ok = s.get("ok", 0)
            pct = s.get("yield_pct", 0.0)

            canvas = widget["canvas"]
            color = widget["color"]

            canvas.delete("bar")
            bar_width = int(200 * pct / 100) if pct > 0 else 0
            if bar_width > 0:
                canvas.create_rectangle(0, 0, bar_width, 20, fill=color, outline="", tags="bar")

            # 良品/总数
            widget["pct_label"].config(text=f"{pct:.1f}%")

    def _update_status(self, data: dict):
        """更新底部状态"""
        production = data.get("production_count", "--")
        target = data.get("target", "--")
        self.production_label.config(text=f"产量: {production}/{target}")

        llm_status = data.get("llm_status", "--")
        self.llm_label.config(text=f"LLM: {llm_status}")
        llm_color = "#f39c12" if llm_status == "工作中" else "#000000"
        self.llm_label.config(fg=llm_color)

        ai_score = data.get("ai_score", "--")
        self.score_label.config(text=f"AI分: {ai_score}")
        if isinstance(ai_score, (int, float)):
            score_color = "#27ae60" if ai_score >= 80 else "#e67e22" if ai_score >= 50 else "#e74c3c"
            self.score_label.config(fg=score_color)

        alarm = data.get("alarm", False)
        if alarm:
            self.alarm_label.config(text="⚠ 报警中", fg="#e74c3c")
        else:
            self.alarm_label.config(text="状态: 正常", fg="#27ae60")

        cycle = data.get("cycle", "--")
        self.cycle_label.config(text=f"周期: {cycle}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = AssemblyDashboard()
    app.run()
