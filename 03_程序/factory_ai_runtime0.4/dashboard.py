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

        # ★ 窗口放大：右边加"步骤进度"栏，下面加"事件日志"栏
        self.root.geometry("1256x900")
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

        # ★★★ 线程安全的更新队列（2026-09-28 修）★★★
        #  为什么必须有这个：
        #    Tkinter 【不允许从其他线程操作控件】，连 root.after() 都不行 ——
        #    非主线程调用 after() 会抛 "main thread is not in main loop"，
        #    表现就是【界面完全不刷新】。
        #  而我们的调用方恰恰都是别的线程：
        #    生产线程 main.py → app.update_data / app.set_step
        #    LLM 线程        → app.update_data
        #    event_manager   → app.log
        #  所以改成：其他线程只往队列里塞数据，主线程的 _tick 定时取出来刷界面。
        import queue as _queue
        self._q = _queue.Queue(maxsize=2000)

        # 下面这些【只由主线程读写】，其他线程不许直接碰
        self._pending_step = None     # 待处理的步骤号
        self._pending_logs = []       # 待追加的日志行

        # ★ 当前步骤 + 步骤本身耗时
        self._cur_step = 0            # 0 = 空闲；1~5 = 正在做第几步
        self._cur_step_t0 = time.time()
        self._last_step_time = 0.0    # 上一步用了多久

        # ★ 事件日志行（最多保留 MAX_LOG 条，滚动显示）
        self._log_lines = []
        self.MAX_LOG = 200

        # ★ 节拍历史（最近 20 件），用来画迷你趋势
        self._cycle_history = []

        # 定时刷新（步骤耗时是连续走的，需要自己走时钟，不能只靠 update_data）
        self.root.after(200, self._tick)

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

        # ========== 中部：左边画布 + 右边步骤进度栏 ==========
        mid = tk.Frame(root, bg="#0a0a0f")
        mid.pack(fill="x")

        self.canvas = tk.Canvas(mid, width=960, height=540, bg="#0a0a0f",
                                highlightthickness=0)
        self.canvas.pack(side="left")

        self._build_step_panel(mid)

        # 绘制轮盘静态元素
        self._draw_rotary_table()

        # ========== 底部信息栏 ==========
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
        self.llm_decision_label.grid(row=2, column=0, columnspan=5, sticky="ew", padx=20, pady=(0, 4))

        # ★ 让 5 列均匀分配宽度，日志栏才能真正铺满（不然只跨到用过的列宽）
        for _c in range(5):
            info_frame.grid_columnconfigure(_c, weight=1)

        # ★ 事件日志栏（最下面）
        self._build_log_panel(info_frame)

    # ---------- 右侧：生产步骤进度栏 ----------

    # ★ 步骤清单（和 main.py produce_one 里的 5 步一一对应）
    STEP_NAMES = [
        "1 转盘A 接料送料",
        "2 锁螺丝臂 搬运",
        "3 点胶臂 点胶",
        "4 转盘B 送料",
        "5 视觉检测分拣",
    ]

    def _build_step_panel(self, parent):
        """右边那一栏：当前走到第几步、每步耗时、节拍趋势、事件日志"""
        p = tk.Frame(parent, bg="#0a0a0f", width=280)
        p.pack(side="left", fill="both", expand=True, padx=(6, 0))
        p.pack_propagate(False)

        # ---- 标题 ----
        tk.Label(p, text="生产步骤", font=("微软雅黑", 11, "bold"),
                 bg="#0a0a0f", fg="#ff6600").pack(anchor="w", pady=(4, 6))

        # ---- 5 个步骤行：圆点 + 名称 + 本步耗时 ----
        self.step_rows = []
        for i, nm in enumerate(self.STEP_NAMES):
            row = tk.Frame(p, bg="#0a0a0f")
            row.pack(fill="x", pady=2)
            dot = tk.Label(row, text="●", font=("微软雅黑", 11),
                           bg="#0a0a0f", fg="#333340")
            dot.pack(side="left")
            tk.Label(row, text=nm, font=("微软雅黑", 9), bg="#0a0a0f",
                     fg="#a0a0a0", anchor="w").pack(side="left", padx=(4, 0))
            t = tk.Label(row, text="", font=("Consolas", 9), bg="#0a0a0f",
                         fg="#ff6600", width=7, anchor="e")
            t.pack(side="right")
            self.step_rows.append({"dot": dot, "time": t})

        # ---- 当前步骤大数字 ----
        box = tk.Frame(p, bg="#1a0a00")
        box.pack(fill="x", pady=(10, 4))
        tk.Label(box, text="当前", font=("微软雅黑", 8), bg="#1a0a00",
                 fg="#a0a0a0").pack(anchor="w", padx=8, pady=(4, 0))
        self.step_now = tk.Label(box, text="空闲", font=("微软雅黑", 12, "bold"),
                                 bg="#1a0a00", fg="#ff6600")
        self.step_now.pack(anchor="w", padx=8)
        self.step_clock = tk.Label(box, text="已用 0.0s", font=("Consolas", 10),
                                   bg="#1a0a00", fg="#a0a0a0")
        self.step_clock.pack(anchor="w", padx=8, pady=(0, 6))

        # ---- 节拍信息 ----
        tk.Label(p, text="节拍", font=("微软雅黑", 11, "bold"),
                 bg="#0a0a0f", fg="#ff6600").pack(anchor="w", pady=(10, 4))
        self.cycle_info = tk.Label(p, text="本件: --s   上件: --s",
                                   font=("Consolas", 9), bg="#0a0a0f",
                                   fg="#a0a0a0", anchor="w", justify="left")
        self.cycle_info.pack(anchor="w")
        self.cycle_mini = tk.Canvas(p, width=250, height=56, bg="#0a0a0f",
                                    highlightthickness=1,
                                    highlightbackground="#333340")
        self.cycle_mini.pack(anchor="w", pady=4)
        self.cycle_best = tk.Label(p, text="最快: --s   平均: --s",
                                   font=("Consolas", 9), bg="#0a0a0f",
                                   fg="#a0a0a0", anchor="w")
        self.cycle_best.pack(anchor="w")

        # ---- 参数一览（只读，方便一眼看到当前用的值）----
        tk.Label(p, text="当前参数", font=("微软雅黑", 11, "bold"),
                 bg="#0a0a0f", fg="#ff6600").pack(anchor="w", pady=(10, 4))
        self.param_label = tk.Label(p, text="等待 config...", font=("Consolas", 8),
                                    bg="#0a0a0f", fg="#a0a0a0",
                                    anchor="w", justify="left")
        self.param_label.pack(anchor="w")

    # ---------- 事件日志栏（横跨底部）----------

    def _build_log_panel(self, parent):
        """底部日志：显示最近的事件，滚动保留"""
        tk.Label(parent, text="事件日志", font=("微软雅黑", 9, "bold"),
                 bg="#1a0a00", fg="#ff6600").grid(
            row=3, column=0, columnspan=5, sticky="w", padx=20, pady=(6, 0))
        self.log_text = tk.Text(parent, height=5, bg="#0d0d14", fg="#c0c0c0",
                                font=("Consolas", 8), bd=0,
                                highlightthickness=1,
                                highlightbackground="#333340",
                                state="disabled", wrap="none")
        self.log_text.grid(row=4, column=0, columnspan=5, sticky="ew",
                           padx=20, pady=(2, 10))

    def log(self, msg):
        """往日志里追加一行。【可从任意线程调用】

        ★ 注意：这里【不能】直接改 _log_lines，也不能调 root.after()，
          因为 Tkinter 不允许其他线程碰它。只往队列里塞，主线程去取。
        """
        self._safe_put(("log", msg))

    def _refresh_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        # 只显示最后 8 行（面板就这么高）
        for line in self._log_lines[-8:]:
            self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ---------- 步骤/节拍 刷新 ----------

    def set_step(self, step_no):
        """main.py 每进入一个步骤调用一次。step_no: 1~5；0 = 空闲

        【可从任意线程调用】—— 只记到队列，主线程 _tick 里真正切换。
        """
        self._safe_put(("step", step_no))

    # ---------- 线程间通信 ----------

    def _safe_put(self, item):
        """把一条更新塞进队列。【任意线程都可调用，不会碰 Tk】"""
        try:
            self._q.put_nowait(item)
        except Exception:
            pass          # 队列满/关了都无所谓，界面丢一帧不影响生产

    def _drain_queue(self):
        """★ 只由主线程调用：把队列里的更新全部取出来应用到界面。"""
        got_step = None
        got_data = None
        got_logs = []
        while True:
            try:
                kind, payload = self._q.get_nowait()
            except Exception:
                break
            if kind == "step":
                got_step = payload          # 只保留最后一个（中间的没必要逐帧走）
            elif kind == "data":
                got_data = payload          # 同上，界面只要最新状态
            elif kind == "log":
                got_logs.append(payload)    # 日志不能丢，全留着

        # ---- 应用步骤切换 ----
        if got_step is not None:
            now = time.time()
            if self._cur_step != 0:
                self._last_step_time = now - self._cur_step_t0
                row = self.step_rows[self._cur_step - 1]
                row["time"].config(text=f"{self._last_step_time:.1f}s")
            self._cur_step = got_step
            self._cur_step_t0 = now

        # ---- 应用日志 ----
        if got_logs:
            for m in got_logs:
                ts = time.strftime("%H:%M:%S")
                self._log_lines.append(f"[{ts}] {m}")
            if len(self._log_lines) > self.MAX_LOG:
                self._log_lines = self._log_lines[-self.MAX_LOG:]
            self._refresh_log()

        # ---- 应用数据 ----
        if got_data is not None:
            self._apply_data(got_data)
            self._refresh_ui()

    def _tick(self):
        """★ 只在主线程跑。每 200ms：消费队列 + 刷新"当前步骤已用时间"。"""
        try:
            self._drain_queue()
            self._refresh_steps()
        except Exception as e:
            print("      [GUI] 刷新出错（不影响生产）:", e)
        self.root.after(200, self._tick)

    def _refresh_steps(self):
        for i, row in enumerate(self.step_rows):
            if self._cur_step == i + 1:
                row["dot"].config(fg="#ff6600")       # 正在做的：亮橙
            elif self._cur_step > i + 1:
                row["dot"].config(fg="#44ff44")       # 已做完的：绿
            else:
                row["dot"].config(fg="#333340")       # 未开始的：暗
        if self._cur_step == 0:
            self.step_now.config(text="空闲", fg="#a0a0a0")
            self.step_clock.config(text="")
        else:
            self.step_now.config(text=self.STEP_NAMES[self._cur_step - 1],
                                 fg="#ff6600")
            used = time.time() - self._cur_step_t0
            self.step_clock.config(text=f"已用 {used:.1f}s")

    def _draw_cycle_mini(self):
        """画节拍迷你趋势图（最近 20 件）"""
        c = self.cycle_mini
        c.delete("all")
        w, h = 250, 56
        c.create_line(0, h - 1, w, h - 1, fill="#333340")
        hist = self._cycle_history[-20:]
        if not hist:
            c.create_text(w // 2, h // 2, text="暂无数据",
                          font=("微软雅黑", 8), fill="#555560")
            return
        lo, hi = min(hist), max(hist)
        span = max(hi - lo, 1.0)
        n = len(hist)
        bw = max(2, (w - 10) // max(n, 1) - 2)
        for i, v in enumerate(hist):
            bh = int((v - lo) / span * (h - 14)) + 4
            x0 = 5 + i * (bw + 2)
            y0 = h - 3 - bh
            # 最后一件用亮橙，其余用暗橙
            col = "#ff6600" if i == n - 1 else "#7a3a00"
            c.create_rectangle(x0, y0, x0 + bw, h - 3, fill=col, outline="")
        c.create_text(2, 8, text=f"{hi:.0f}s", font=("Consolas", 7),
                      fill="#a0a0a0", anchor="w")
        c.create_text(2, h - 10, text=f"{lo:.0f}s", font=("Consolas", 7),
                      fill="#a0a0a0", anchor="w")

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

    def update_data(self, production_count, target, station_stats, llm_status,
                    ai_score, alarm, cycle, last_result=None, llm_decision=None,
                    cycle_time=None, params=None):
        """更新仪表盘数据。【可从任意线程调用】

        last_result:   True=OK, False=NG, None=无产品
        llm_decision:  AI线长最新决策文本
        cycle_time:    ★ 本件实际节拍（秒）。给了就记进节拍趋势图
        params:        ★ 当前关键参数 dict，显示在"当前参数"栏

        ★ 实现说明：这里【不直接碰控件】，只把数据打包塞进队列，
          由主线程的 _tick 取出来应用。原因见 __init__ 里 _q 的注释。
        """
        self._safe_put(("data", {
            "production_count": production_count,
            "target": target,
            "station_stats": station_stats,
            "llm_status": llm_status,
            "ai_score": ai_score,
            "alarm": alarm,
            "cycle": cycle,
            "last_result": last_result,
            "llm_decision": llm_decision,
            "cycle_time": cycle_time,
            "params": params,
        }))

    def _apply_data(self, d):
        """★ 只由主线程调用：把队列里取出的数据应用到内部状态。"""
        old_decision = self._data.get("llm_decision")
        old_params = self._data.get("params")
        self._data = {
            "production_count": d["production_count"],
            "target": d["target"],
            "station_stats": d["station_stats"],
            "llm_status": d["llm_status"],
            "ai_score": d["ai_score"],
            "alarm": d["alarm"],
            "cycle": d["cycle"],
            "last_result": d["last_result"],
            "llm_decision": d["llm_decision"] if d["llm_decision"] is not None else old_decision,
            "params": d["params"] if d["params"] is not None else old_params,
        }
        # ★ 记录节拍历史（给趋势图用）
        if d["cycle_time"] is not None:
            self._cycle_history.append(float(d["cycle_time"]))
            if len(self._cycle_history) > self.MAX_LOG:
                self._cycle_history = self._cycle_history[-self.MAX_LOG:]

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

        # ★ 节拍信息 + 趋势图
        hist = self._cycle_history
        if hist:
            cur = hist[-1]
            prev = hist[-2] if len(hist) >= 2 else None
            self.cycle_info.config(
                text=f"本件: {cur:.1f}s   上件: {('--' if prev is None else f'{prev:.1f}s')}")
            self.cycle_best.config(
                text=f"最快: {min(hist):.1f}s   平均: {sum(hist)/len(hist):.1f}s")
            self._draw_cycle_mini()

        # ★ 参数一览
        p = d.get("params")
        if p:
            self.param_label.config(
                text="\n".join(f"{k}: {v}" for k, v in p.items()))

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
