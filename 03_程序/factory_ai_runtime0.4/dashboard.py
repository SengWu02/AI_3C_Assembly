"""
3C 组装岛 · 可视化仪表盘（Tkinter 窗口）

用法：
    from dashboard import DashboardApp

    app = DashboardApp()
    # 在另一个线程更新数据
    app.update_data(production_count, target, station_stats, llm_status, ai_score, alarm, cycle)
    app.root.mainloop()
"""

import tkinter as tk
from tkinter import ttk
import threading
import time


class DashboardApp:
    """可视化仪表盘窗口，显示4工位轮盘"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("3C 组装岛 · 实时监控")

        self.root.geometry("960x740")
        self.root.resizable(False, False)
        self.root.configure(bg="#0a0a0f")

        self._build_ui()

        # 数据缓存
        self._data = {
            "production_count": 0,
            "target": 0,
            "station_stats": {},
            "llm_status": "待命",
            "ai_score": 100,
            "alarm": False,
            "cycle": 0,
            "llm_decision": "等待分析...",
        }

    # ---------- 构建 UI ----------

    def _build_ui(self):
        root = self.root

        # 标题
        title_frame = tk.Frame(root, bg="#1a0a00", height=50)
        title_frame.pack(fill="x")
        tk.Label(
            title_frame,
            text="3C 组装岛 · 实时监控",
            font=("微软雅黑", 18, "bold"),
            bg="#1a0a00",
            fg="#ff6600",
        ).pack(pady=10)

        # 轮盘画布区域

        self.canvas = tk.Canvas(root, width=960, height=540, bg="#0a0a0f", highlightthickness=0)
        self.canvas.pack()

        # 绘制轮盘静态元素
        self._draw_rotary_table()

        # 底部信息栏
        info_frame = tk.Frame(root, bg="#1a0a00", height=140)
        info_frame.pack(fill="x", side="bottom")

        self.info_labels = {}
        fields = [
            ("产量", "0/0"),
            ("良品", "0/0"),
            ("LLM", "待命"),
            ("AI分", "100"),
            ("状态", "正常"),
        ]
        for i, (label, val) in enumerate(fields):
            f = tk.Frame(info_frame, bg="#1a0a00")
            f.grid(row=0, column=i, padx=20, pady=8)
            tk.Label(f, text=label, font=("微软雅黑", 10), bg="#1a0a00", fg="#a0a0a0").pack()
            lbl = tk.Label(f, text=val, font=("微软雅黑", 14, "bold"), bg="#1a0a00", fg="#ff6600")
            lbl.pack()
            self.info_labels[label] = lbl

        # 周期标签
        self.cycle_label = tk.Label(
            info_frame, text="周期: 0", font=("微软雅黑", 10),
            bg="#1a0a00", fg="#a0a0a0"
        )
        self.cycle_label.grid(row=1, column=4, sticky="e", padx=20)

        # LLM 决策显示行（横跨底部）
        self.llm_decision_label = tk.Label(
            info_frame, text="AI线长: 等待分析...", font=("微软雅黑", 10),
            bg="#1a0a00", fg="#ff6600", anchor="w"
        )
        self.llm_decision_label.grid(row=2, column=0, columnspan=5, sticky="ew", padx=20, pady=(0, 8))

    def _draw_rotary_table(self):
        c = self.canvas

        # ========== 转盘A（左上）与转盘B（右下）相切 ==========
        ax, ay, ar = 300, 200, 70
        bx, by, br = 440, 310, 70
        # 两个转盘相切：圆心距离 = ar + br = 140
        # (440-300)^2 + (310-200)^2 = 140^2 + 110^2 = 19600+12100=31700
        # sqrt(31700) ≈ 178，略大，微调让它们看起来相切
        bx, by = 435, 310  # 调整后距离约 sqrt(135^2+110^2)=174，接近140+70=...

        c.create_oval(ax - ar, ay - ar, ax + ar, ay + ar,
                       outline="#ff6600", width=2, fill="#1a0a00")
        c.create_text(ax, ay - 5, text="转盘A", font=("微软雅黑", 11, "bold"), fill="#ff6600")
        c.create_text(ax, ay + 15, text="接料", font=("微软雅黑", 8), fill="#a0a0a0")

        c.create_oval(bx - br, by - br, bx + br, by + br,
                       outline="#ff6600", width=2, fill="#1a0a00")
        c.create_text(bx, by - 5, text="转盘B", font=("微软雅黑", 11, "bold"), fill="#ff6600")
        c.create_text(bx, by + 15, text="成品中转", font=("微软雅黑", 8), fill="#a0a0a0")

        # ========== 出料仓+皮带1（最左侧横的） ==========
        feed_x, feed_y = 30, 230
        c.create_rectangle(5, feed_y - 18, 60, feed_y + 18,
                            fill="#1a0a00", outline="#ff6600", width=2)
        c.create_text(32, feed_y, text="出料仓", font=("微软雅黑", 9), fill="#ff6600")

        # 皮带1（横的，出料仓到转盘A）
        c.create_line(60, feed_y + 25, ax - ar - 10, feed_y + 25,
                       fill="#a0a0a0", width=3)
        c.create_text((60 + ax - ar)//2, feed_y + 15, text="皮带1",
                       font=("微软雅黑", 7), fill="#a0a0a0")

        # 视觉0（在皮带1上方）
        v0x, v0y = 180, feed_y + 10
        c.create_rectangle(v0x - 12, v0y - 12, v0x + 12, v0y + 12,
                            fill="#1a0a00", outline="#ffaa00", width=2)
        c.create_text(v0x, v0y - 25, text="视觉0", font=("微软雅黑", 7), fill="#ffaa00")

        # ========== 工位 ==========

        # 工位2: 锁螺丝机械手1（转盘A左下，横的）
        sx2, sy2 = 190, 300
        c.create_rectangle(sx2 - 65, sy2 - 25, sx2 + 65, sy2 + 25,
                            fill="#1a0a00", outline="#ff6600", width=2)
        c.create_text(sx2, sy2 - 8, text="锁螺丝", font=("微软雅黑", 9, "bold"), fill="#ffffff")
        c.create_text(sx2, sy2 + 10, text="良率: --%", font=("微软雅黑", 7), fill="#ff6600")

        # 皮带2（竖的，锁螺丝右侧）
        belt2_x = sx2 + 65
        c.create_line(belt2_x, sy2 + 25, belt2_x, 430, fill="#a0a0a0", width=3)
        c.create_text(belt2_x + 15, 370, text="皮带2",
                       font=("微软雅黑", 7), fill="#a0a0a0")

        # 工位3: 点胶机械手2（转盘B上方偏右）
        sx3, sy3 = 440, 190
        c.create_rectangle(sx3 - 50, sy3 - 35, sx3 + 50, sy3 + 35,
                            fill="#1a0a00", outline="#ff6600", width=2)
        c.create_text(sx3, sy3 - 10, text="点胶", font=("微软雅黑", 9, "bold"), fill="#ffffff")
        c.create_text(sx3, sy3 + 8, text="良率: --%", font=("微软雅黑", 7), fill="#ff6600")
        c.create_text(sx3, sy3 + 22, text="机械手2", font=("微软雅黑", 7), fill="#a0a0a0")

        # ========== 成品检测 + 视觉1 + 推杆 + 皮带3 ==========
        # 皮带3（横的，转盘B右侧引出）
        belt3_y = by
        belt3_start = bx + br + 10
        belt3_end = 800
        c.create_line(belt3_start, belt3_y, belt3_end, belt3_y,
                       fill="#a0a0a0", width=3)
        c.create_text((belt3_start + belt3_end)//2, belt3_y - 20, text="皮带3",
                       font=("微软雅黑", 7), fill="#a0a0a0")

        # 成品检测工位（皮带3上方）
        sx4, sy4 = 640, belt3_y - 40
        c.create_rectangle(sx4 - 60, sy4 - 20, sx4 + 60, sy4 + 20,
                            fill="#1a0a00", outline="#ff6600", width=2)
        c.create_text(sx4, sy4 - 6, text="成品检测", font=("微软雅黑", 9, "bold"), fill="#ffffff")
        c.create_text(sx4, sy4 + 10, text="良率: --%", font=("微软雅黑", 7), fill="#ff6600")

        # 视觉1（皮带3上，成品检测位置，大小同推杆）
        v1x, v1y = sx4 + 25, belt3_y
        c.create_rectangle(v1x - 12, v1y - 12, v1x + 12, v1y + 12,
                            fill="#1a0a00", outline="#ffaa00", width=2)
        c.create_text(v1x, belt3_y + 30, text="视觉1",
                       font=("微软雅黑", 7), fill="#ffaa00")

        # 推杆（皮带3上，正对下方）
        pusher_x = 730
        c.create_rectangle(pusher_x - 15, belt3_y - 40, pusher_x + 15, belt3_y,
                            fill="#2a0a00", outline="#ff4444", width=2)
        c.create_text(pusher_x, belt3_y - 50, text="推杆",
                       font=("微软雅黑", 7), fill="#ff4444")

        # ========== 工位状态框（供 _refresh_ui 实时刷新良率/良品数/OK-NG填充） ==========
        # 说明：上面各工位已画出静态外框；这里为每个工位额外建立"可刷新"的
        #     填充层 + 边框层 + 良率文本 + 计数文本，并把 canvas item id 存进
        #     self.station_frames，_refresh_ui() 依赖这个字典做实时刷新。
        self.station_frames = {}

        for sid, (x0, y0, x1, y1, tx) in {
            1: (0, 0, 0, 0, 0),          # 工位1（视觉检测）由皮带1上的视觉0表示，无独立方框
            2: (sx2 - 65, sy2 - 25, sx2 + 65, sy2 + 25, sx2),
            3: (sx3 - 50, sy3 - 35, sx3 + 50, sy3 + 35, sx3),
            4: (sx4 - 60, sy4 - 20, sx4 + 60, sy4 + 20, sx4),
        }.items():
            if sid == 1:
                continue
            fill_rect = c.create_rectangle(x0, y0, x1, y1,
                                           outline="", fill="#1a0a00")
            rect = c.create_rectangle(x0, y0, x1, y1,
                                      outline="#ff6600", width=2, fill="")
            yield_text = c.create_text(tx, y1 - 16, text="良率: --%",
                                       font=("微软雅黑", 8), fill="#ff6600")
            count_text = c.create_text(tx, y1 - 5, text="0/0",
                                       font=("微软雅黑", 7), fill="#a0a0a0")
            self.station_frames[sid] = {
                "fill_rect": fill_rect,
                "rect": rect,
                "yield_text": yield_text,
                "count_text": count_text,
            }

        # ========== OK出料：皮带3最右端 → 滑坡 → 良品仓 ==========
        c.create_line(belt3_end - 10, belt3_y, 920, belt3_y + 40,
                       fill="#44ff44", width=4)
        c.create_text(920, belt3_y + 50, text="良品仓",
                       font=("微软雅黑", 9, "bold"), fill="#44ff44")

        # ========== NG出料：推杆正下方 → 斜波 → 不良仓 ==========
        ng_end_x, ng_end_y = 730, 480
        c.create_line(pusher_x, belt3_y + 5, ng_end_x, ng_end_y,
                       fill="#ff4444", width=4)
        c.create_text(ng_end_x, ng_end_y + 15, text="不良仓",
                       font=("微软雅黑", 9, "bold"), fill="#ff4444")

        # ========== 只有皮带连线（无其他连线） ==========

        # ========== 图例 ==========
        legend_x, legend_y = 20, 450
        c.create_text(legend_x, legend_y, text="图例",
                       font=("微软雅黑", 8, "bold"), fill="#a0a0a0", anchor="w")
        items = [
            ("#ff6600", "良率≥85%"),
            ("#ffaa00", "良率70%~85%"),
            ("#ff4444", "良率<70%"),
        ]
        for i, (clr, lbl) in enumerate(items):
            y = legend_y + 14 + i * 16
            c.create_rectangle(legend_x, y, legend_x + 10, y + 8, fill=clr, outline="")
            c.create_text(legend_x + 14, y + 4, text=lbl,
                           font=("微软雅黑", 8), fill="#a0a0a0", anchor="w")

        # 标题
        c.create_text(500, 10, text="3C 组装岛 · 产线布局",
                       font=("微软雅黑", 14, "bold"), fill="#ff6600")

    # ---------- 更新数据 ----------

    def update_data(self, production_count, target, station_stats, llm_status, ai_score, alarm, cycle, last_result=None, llm_decision=None):
        """更新仪表盘数据（可从其他线程调用）
        last_result: True=OK, False=NG, None=无产品
        llm_decision: AI线长最新决策文本
        """
        self._data = {
            "production_count": production_count,
            "target": target,
            "station_stats": station_stats,
            "llm_status": llm_status,
            "ai_score": ai_score,
            "alarm": alarm,
            "cycle": cycle,
            "last_result": last_result,
        }
        if llm_decision is not None:
            self._data["llm_decision"] = llm_decision
        # 调度到主线程更新 UI
        self.root.after(0, self._refresh_ui)

    def _refresh_ui(self):
        d = self._data

        # 底部信息
        self.info_labels["产量"].config(text=f"{d['production_count']}/{d['target']}")
        s4 = d["station_stats"].get(4, {})
        self.info_labels["良品"].config(text=f"{s4.get('ok', 0)}/{s4.get('total', 0)}")
        self.info_labels["LLM"].config(text=d["llm_status"])
        self.info_labels["AI分"].config(text=str(d["ai_score"]))
        status_text = "⚠ 报警" if d["alarm"] else "✔ 正常"
        status_color = "#ff4444" if d["alarm"] else "#44ff44"
        self.info_labels["状态"].config(text=status_text, fg=status_color)
        self.cycle_label.config(text=f"周期: {d['cycle']}")

        # LLM 决策
        self.llm_decision_label.config(text=f"AI线长: {d.get('llm_decision', '监管中...')}")

        # 工位方块
        last_result = d.get("last_result")

        for sid, s in d["station_stats"].items():
            if sid not in self.station_frames:
                continue
            sf = self.station_frames[sid]
            total = s.get("total", 0)
            ok = s.get("ok", 0)
            pct = s.get("yield_pct", 100.0)

            # 根据良率变色（赛博工业风）
            if pct >= 85:
                color = "#ff6600"
                border = "#ff6600"
            elif pct >= 70:
                color = "#ffaa00"
                border = "#ffaa00"
            else:
                color = "#ff4444"
                border = "#ff4444"

            self.canvas.itemconfig(sf["yield_text"], text=f"良率: {pct:.1f}%", fill=color)
            self.canvas.itemconfig(sf["count_text"], text=f"{ok}/{total}", fill=color)
            self.canvas.itemconfig(sf["rect"], outline=border)

            # ========== 工位4（成品检测）实时填充 ==========
            if sid == 4:
                if last_result is True:
                    fill = "#1a3a1a"   # 深绿
                elif last_result is False:
                    fill = "#3a1a1a"   # 深红
                else:
                    fill = "#1a1a3e"   # 默认深蓝
                self.canvas.itemconfig(sf["fill_rect"], fill=fill)


# 方便测试
if __name__ == "__main__":
    app = DashboardApp()

    def demo_update():
        import random
        stats = {
            1: {"name": "视觉检测", "ok": 0, "total": 0, "yield_pct": 100.0},
            2: {"name": "锁螺丝", "ok": 0, "total": 0, "yield_pct": 100.0},
            3: {"name": "点胶", "ok": 0, "total": 0, "yield_pct": 100.0},
            4: {"name": "成品检测", "ok": 0, "total": 0, "yield_pct": 100.0},
        }
        for i in range(50):
            for sid in stats:
                stats[sid]["total"] += 1
                if random.random() < 0.85:
                    stats[sid]["ok"] += 1
                stats[sid]["yield_pct"] = round(stats[sid]["ok"] / stats[sid]["total"] * 100, 1)
            app.update_data(
                production_count=i + 1,
                target=50,
                station_stats=stats,
                llm_status="工作中" if i % 3 == 0 else "待命",
                ai_score=max(0, 100 - i),
                alarm=i > 30,
                cycle=i + 1,
            )
            time.sleep(0.3)

    threading.Thread(target=demo_update, daemon=True).start()
    app.root.mainloop()
