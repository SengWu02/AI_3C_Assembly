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
        # ★★ 允许调整大小（2026-09-28）
        #    画布布局的缩放交给 Tk 自己：先记下"设计尺寸"，窗口一变就按比例缩放。
        self.root.resizable(True, True)
        self.root.minsize(1050, 760)      # 再小就放不下了
        self.root.configure(bg="#0a0a0f")

        # ★★★ 人工介入的回调（main.py 负责挂上来）★★★
        #  为什么用回调而不是让 dashboard 直接 import main：
        #    那样会循环依赖，而且测试脚本想单独跑 GUI 就跑不起来。
        #  没挂回调时按钮点了会有提示，不会崩。
        self.on_set_cycle = None      # def f(seconds) -> None
        self.on_stop = None           # def f() -> None
        self.on_resume = None         # def f() -> None
        self.on_pause = None          # def f() -> None
        self.on_continue = None       # def f() -> None

        self._build_ui()

        # ★ 记下画布的设计尺寸，用于等比缩放
        self._canvas_base = (960, 540)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

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
        #  ★ expand=True 让中部吃掉窗口的剩余高度，画布才能真正长大
        #    （原来只 fill="x"，高度锁死在 540，窗口拉高也没用）
        mid = tk.Frame(root, bg="#0a0a0f")
        mid.pack(fill="both", expand=True)

        # ★ 画布改成"可拉伸"：窗口放大时画布跟着大，内部图形等比缩放
        self.canvas = tk.Canvas(mid, width=960, height=540, bg="#0a0a0f",
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)   # ★ 横向纵向都拉伸

        self._build_step_panel(mid)

        # 绘制轮盘静态元素
        self._draw_rotary_table()

        # ★★ 人工介入面板：必须在【画完布局之后】建，
        #    这样它才叠在整个画布最上层（place 的层序按创建顺序）。
        self._build_manual_panel()

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

    # ---------- 画布右上角：人工介入面板 ----------

    def _build_manual_panel(self):
        """★ 画布右上角的人工介入面板（悬浮在画布上）。

        功能：
          · 节拍输入 + 设定      —— 立即改 PRODUCTION_CYCLE_TIME
          · 紧急停线 / 恢复       —— 停到人工恢复为止
          · 暂停 / 继续          —— 件与件之间生效，不把工件扔在半路

        ★ 用 place() 而不是 pack()：这样它悬浮在画布上，
          而且窗口拉伸时可以用相对坐标(relx=1.0 anchor=n)自动贴住右上角。
        """
        f = tk.Frame(self.canvas, bg="#14141c",
                     highlightthickness=1, highlightbackground="#ff6600")
        # relx=1.0 + anchor="ne" = 永远贴住父容器右上角
        f.place(relx=1.0, rely=0.0, x=-10, y=10, anchor="ne")
        self.manual_panel = f

        tk.Label(f, text="⚙ 人工介入", font=("微软雅黑", 9, "bold"),
                 bg="#14141c", fg="#ff6600").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 4))

        # ---- 节拍设定 ----
        tk.Label(f, text="节拍(秒)", font=("微软雅黑", 8), bg="#14141c",
                 fg="#a0a0a0").grid(row=1, column=0, sticky="w", padx=(8, 2))
        self.cycle_entry = tk.Entry(f, width=6, font=("Consolas", 10),
                                    bg="#0d0d14", fg="#ff6600",
                                    insertbackground="#ff6600",
                                    justify="center", bd=0,
                                    highlightthickness=1,
                                    highlightbackground="#444450")
        self.cycle_entry.grid(row=1, column=1, sticky="e", padx=(0, 8))
        self.cycle_entry.insert(0, "3.0")
        self.cycle_entry.bind("<Return>", lambda e: self._cb_set_cycle())

        def _btn(text, row, col, color, cb, colspan=1):
            b = tk.Button(f, text=text, font=("微软雅黑", 8),
                          bg="#1e1e28", fg=color,
                          activebackground="#2a2a38", activeforeground=color,
                          relief="flat", bd=0, cursor="hand2",
                          command=cb, padx=6, pady=2)
            b.grid(row=row, column=col, columnspan=colspan,
                   sticky="ew", padx=(8, 8) if colspan == 2 else (8, 2), pady=2)
            return b

        _btn("设定节拍", 2, 0, "#ffaa00", self._cb_set_cycle, colspan=2)

        # ---- 停线 / 恢复 ----
        _btn("■ 紧急停线", 3, 0, "#ff4444", self._cb_stop)
        _btn("▶ 恢复", 3, 1, "#44ff44", self._cb_resume)

        # ---- 暂停 / 继续 ----
        _btn("‖ 暂停", 4, 0, "#ffaa00", self._cb_pause)
        _btn("▶ 继续", 4, 1, "#44ff44", self._cb_continue)

        # ---- 状态显示 ----
        self.manual_status = tk.Label(f, text="就绪", font=("微软雅黑", 8),
                                      bg="#14141c", fg="#a0a0a0",
                                      wraplength=170, justify="left")
        self.manual_status.grid(row=5, column=0, columnspan=2,
                                sticky="w", padx=8, pady=(4, 6))

    # ---------- 人工介入按钮的实际动作 ----------

    def _manual_note(self, text, color="#a0a0a0"):
        """在面板上显示一行反馈（不是日志，只是给操作者看）"""
        try:
            self.manual_status.config(text=text, fg=color)
        except Exception:
            pass

    def _cb_set_cycle(self):
        """点「设定节拍」：读输入框 -> 校验 -> 交给 main.py 回调"""
        raw = self.cycle_entry.get().strip()
        try:
            v = float(raw)
        except ValueError:
            self._manual_note(f"★ \"{raw}\" 不是数字", "#ff4444")
            return
        ok, msg = self._validate_cycle(v)
        if not ok:
            self._manual_note("★ " + msg, "#ff4444")
            return
        if self.on_set_cycle is None:
            self._manual_note("★ 未接入产线（只看界面时无效）", "#ffaa00")
            return
        try:
            self.on_set_cycle(v)
            self._manual_note(f"节拍已设为 {v}s", "#44ff44")
        except Exception as e:
            self._manual_note(f"★ 设置失败: {e}", "#ff4444")

    def _validate_cycle(self, v):
        """节拍范围和 config 里的护栏保持一致（避免 GUI 能设、main 又拦掉）"""
        lo, hi = 1.0, 10.0
        try:
            import config as _c
            lo = getattr(_c, "LLM_CYCLE_MIN", 1.0)
            hi = getattr(_c, "LLM_CYCLE_MAX", 10.0)
        except Exception:
            pass
        if not (lo <= v <= hi):
            return False, f"节拍要 {lo}~{hi} 秒之间"
        return True, ""

    def _cb_stop(self):
        if self.on_stop is None:
            self._manual_note("★ 未接入产线", "#ffaa00")
            return
        # 紧急停线是大事，加一道确认，避免误点
        from tkinter import messagebox
        if not messagebox.askyesno("确认", "确定要紧急停线？\n\n产线会立即停止，\n需要点「恢复」才能继续。"):
            self._manual_note("已取消", "#a0a0a0")
            return
        try:
            self.on_stop()
            self._manual_note("★ 已紧急停线，点「恢复」继续", "#ff4444")
        except Exception as e:
            self._manual_note(f"★ 停线失败: {e}", "#ff4444")

    def _cb_resume(self):
        if self.on_resume is None:
            self._manual_note("★ 未接入产线", "#ffaa00")
            return
        try:
            self.on_resume()
            self._manual_note("已恢复生产", "#44ff44")
        except Exception as e:
            self._manual_note(f"★ 恢复失败: {e}", "#ff4444")

    def _cb_pause(self):
        if self.on_pause is None:
            self._manual_note("★ 未接入产线", "#ffaa00")
            return
        try:
            self.on_pause()
            self._manual_note("已暂停（当前件做完后停）", "#ffaa00")
        except Exception as e:
            self._manual_note(f"★ 暂停失败: {e}", "#ff4444")

    def _cb_continue(self):
        if self.on_continue is None:
            self._manual_note("★ 未接入产线", "#ffaa00")
            return
        try:
            self.on_continue()
            self._manual_note("已继续生产", "#44ff44")
        except Exception as e:
            self._manual_note(f"★ 继续失败: {e}", "#ff4444")

    # ---------- 画布缩放（窗口可调整）----------

    def _on_canvas_resize(self, event):
        """★ 窗口拉伸时，把画布里的图形【和字号】按比例缩放。

        做法：canvas 自带的 scale() 只缩放坐标，【不会缩放文字】，
        所以窗口拉大后会出现"框大了、字没大"的割裂感。
        这里除了 scale() 坐标，还把每个文字的 font 按比例重设一遍。

        每次都是从"基准尺寸 960x540"重新算到当前尺寸（不是累积缩放），
        避免反复拉伸导致误差越滚越大。
        """
        bw, bh = self._canvas_base
        w, h = max(event.width, 1), max(event.height, 1)
        # 等比缩放（用较小的那个比例，避免拉伸变形）
        s = min(w / bw, h / bh)
        s = max(0.6, min(s, 2.0))          # 限制在合理范围
        if abs(s - getattr(self, "_last_scale", 0.0)) < 0.02:
            return                          # 变化太小，不动（避免频繁重绘）

        try:
            ls = getattr(self, "_last_scale", 1.0)
            # 先缩回基准，再按新比例放大
            if abs(ls - 1.0) > 0.001:
                self.canvas.scale("all", 0, 0, 1.0 / ls, 1.0 / ls)
                if not hasattr(self, "_base_fonts"):
                    self._cache_base_fonts()
            self.canvas.scale("all", 0, 0, s, s)
            if not hasattr(self, "_base_fonts"):
                self._cache_base_fonts()
            self._scale_fonts(s)
            self._last_scale = s
        except Exception:
            pass

    def _cache_base_fonts(self):
        """记下每个文字当前的字体（基准），后面按比例重设字体时用"""
        self._base_fonts = {}
        for i in self.canvas.find_all():
            if self.canvas.type(i) != "text":
                continue
            try:
                spec = self.canvas.itemcget(i, "font")
                self._base_fonts[i] = self._parse_font(spec)
            except Exception:
                pass

    @staticmethod
    def _parse_font(spec):
        """把 Tk 的字体字符串解析成 (family, size, style)。

        形如 "微软雅黑 9 bold" 或 "{Microsoft YaHei} 9"。解析不了就返回 None。
        """
        s = str(spec).strip()
        if not s:
            return None
        family = ""
        if s.startswith("{"):                       # 带空格的字体名
            end = s.find("}")
            if end < 0:
                return None
            family = s[1:end]
            rest = s[end + 1:].strip()
        else:
            parts = s.split()
            if len(parts) < 2:
                return None
            family = parts[0]
            rest = " ".join(parts[1:])
        toks = rest.split()
        size = None
        style = []
        for t in toks:
            try:
                size = int(float(t))
            except ValueError:
                if t in ("bold", "italic", "underline", "overstrike"):
                    style.append(t)
        if size is None:
            return None
        return (family, size, " ".join(style))

    def _scale_fonts(self, s):
        """按比例重设所有文字的字体大小（最小 6，避免小到看不清）"""
        for i, base in getattr(self, "_base_fonts", {}).items():
            if base is None:
                continue
            fam, sz, style = base
            new_sz = max(6, int(round(sz * s)))
            try:
                if style:
                    self.canvas.itemconfig(i, font=(fam, new_sz, style))
                else:
                    self.canvas.itemconfig(i, font=(fam, new_sz))
            except Exception:
                pass

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
        p = tk.Frame(parent, bg="#0a0a0f", width=286)
        p.pack(side="left", fill="y", padx=(6, 6))
        p.pack_propagate(False)          # ★ 固定宽度，不跟着窗口变

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

        # ---- 三分类计数（良品 / 不良 / 漏料）----
        #  ★ 漏料也算一件 —— 料根本没到就不能算"没发生"，
        #    不然良率会虚高。这里三个数加起来 = 已生产件数。
        tk.Label(p, text="判定分类", font=("微软雅黑", 11, "bold"),
                 bg="#0a0a0f", fg="#ff6600").pack(anchor="w", pady=(10, 4))
        self.verdict_label = tk.Label(p, text="良品 0   不良 0   漏料 0",
                                      font=("Consolas", 9), bg="#0a0a0f",
                                      fg="#a0a0a0", anchor="w", justify="left")
        self.verdict_label.pack(anchor="w")
        self.verdict_yield = tk.Label(p, text="良率 --%",
                                      font=("微软雅黑", 10, "bold"), bg="#0a0a0f",
                                      fg="#44ff44", anchor="w")
        self.verdict_yield.pack(anchor="w", pady=(2, 0))

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
                    cycle_time=None, params=None, verdict_counts=None):
        """更新仪表盘数据。【可从任意线程调用】

        last_result:    True=良品, False=不良/漏料, None=无产品
        llm_decision:   AI线长最新决策文本
        cycle_time:     ★ 本件实际节拍（秒）。给了就记进节拍趋势图
        params:         ★ 当前关键参数 dict，显示在"当前参数"栏
        verdict_counts: ★ 三分类计数 {"良品":n, "不良":n, "漏料":n}
                          漏料也算一件 —— 良率才准

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
            "verdict_counts": verdict_counts,
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
            "verdict_counts": (d.get("verdict_counts") if d.get("verdict_counts") is not None
                               else self._data.get("verdict_counts")),
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

        # ★ 三分类计数
        vc = d.get("verdict_counts")
        if vc:
            ok_n = vc.get("良品", 0)
            ng_n = vc.get("不良", 0)
            ms_n = vc.get("漏料", 0)
            tot = ok_n + ng_n + ms_n
            self.verdict_label.config(
                text=f"良品 {ok_n}   不良 {ng_n}   漏料 {ms_n}")
            if tot:
                y = ok_n / tot * 100
                # 良率颜色：>=90 绿、>=70 橙、否则红
                col = "#44ff44" if y >= 90 else ("#ffaa00" if y >= 70 else "#ff4444")
                self.verdict_yield.config(
                    text=f"良率 {y:.1f}%   （共 {tot} 件）", fg=col)
            else:
                self.verdict_yield.config(text="良率 --%", fg="#a0a0a0")
        # ★ 旧口径「良品 x/y」也同步（保留兼容）
        if vc:
            self.info_labels["良品"].config(
                text=f"{vc.get('良品', 0)}/{sum(vc.values())}")

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
