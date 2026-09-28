import time


class EventManager:

    def __init__(self):

        self.events = []
        # ★ 2026-09-28 新增：可选的"外部日志接收器"。
        #   设了之后，每个事件除了打印，还会推给它（用来打到 GUI 的日志栏）。
        #   用法：event_manager.sink = app.log
        #   故意用"可选挂载"而不是直接 import dashboard ——
        #   这样 event_manager 保持独立，不依赖 GUI，测试脚本也能单独用。
        self.sink = None

    def add_event(self, event_type, message):

        event = {

            "time": time.strftime("%H:%M:%S"),

            "type": event_type,

            "message": message
        }

        self.events.append(event)

        print(f"[EVENT] {event}")

        # ★ 推给 GUI 日志栏（挂了 sink 才推；出问题不影响主流程）
        if self.sink is not None:
            try:
                self.sink(f"{event_type}: {message}")
            except Exception:
                pass

        # ★ 只保留最近 500 条，防止长时间跑把内存吃掉
        if len(self.events) > 500:
            self.events = self.events[-500:]

    def get_recent_events(self, limit=20):

        return self.events[-limit:]