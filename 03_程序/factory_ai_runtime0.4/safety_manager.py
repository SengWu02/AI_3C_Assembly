class SafetyManager:

    def __init__(self):

        self.emergency_stop = False

        # ★★★ 2026-09-28 新增：人工介入状态 ★★★
        #  为什么不能让 evaluate() 去管它：
        #    evaluate() 每个循环都会跑一遍，末尾有 self.emergency_stop = False，
        #    也就是"只要没检测到卡堵就自动复位"。
        #    如果人工停线也用同一个变量，下一轮就会被自动清掉 —— 按了没用。
        #  所以人工状态单独放，只有人工"恢复"才清。
        self.manual_stop = False        # 人工紧急停线（按了要人工恢复）
        self.manual_pause = False       # 人工暂停（件与件之间生效，不掐断当前件）

    # ---------------- 人工介入接口（GUI 调用） ----------------

    def request_stop(self):
        """人工紧急停线。★ 只有 clear_stop() 能解除。"""
        self.manual_stop = True
        self.emergency_stop = True

    def clear_stop(self):
        """人工恢复：解除停线，重新开始跑。"""
        self.manual_stop = False
        self.emergency_stop = False

    def request_pause(self):
        """人工暂停：当前件做完后停在件与件之间（不会把工件扔在半路）。"""
        self.manual_pause = True

    def clear_pause(self):
        self.manual_pause = False

    def is_stopped(self):
        """是否处于停线状态（人工停线 或 自动检测到卡堵）"""
        return self.manual_stop or self.emergency_stop

    def is_paused(self):
        return self.manual_pause

    # ---------------- 自动检测（原有逻辑，没动） ----------------

    def evaluate(
        self,
        jam_status,
        pusher_status
    ):

        # ★ 人工停线优先：人工没恢复之前，自动检测不改这个状态
        if self.manual_stop:
            self.emergency_stop = True
            return

        if jam_status["is_blocked"]:

            self.emergency_stop = True

            return

        if pusher_status["push_timeout"]:

            self.emergency_stop = True

            return

        self.emergency_stop = False

    def get_status(self):

        return {

            "emergency_stop": self.is_stopped(),
            "manual_stop": self.manual_stop,
            "manual_pause": self.manual_pause,
        }