class AIGovernance:

    def __init__(self):

        self.ai_score = 100

    def evaluate(self, overall_yield_pct: float, efficiency_ppm: float):
        """根据总体良率和效率评分

        Args:
            overall_yield_pct: 总体良率百分比 (0~100)
            efficiency_ppm: 每分钟产出数
        """
        # 良率评分 (0~60分)
        yield_score = min(60, overall_yield_pct * 0.6)

        # 效率评分 (0~40分)，假设目标节拍3秒=20ppm，以此为满分
        efficiency_score = min(40, efficiency_ppm * 2)

        total = yield_score + efficiency_score

        # 平滑过渡
        self.ai_score = int(total)
        if self.ai_score < 0:
            self.ai_score = 0

    def punish(self):

        self.ai_score -= 10

        if self.ai_score < 0:

            self.ai_score = 0

    def reward(self):

        self.ai_score += 1

        if self.ai_score > 100:

            self.ai_score = 100

    def can_stop_line(self):

        return self.ai_score >= 60

    def get_status(self):

        return {

            "ai_score": self.ai_score
        }