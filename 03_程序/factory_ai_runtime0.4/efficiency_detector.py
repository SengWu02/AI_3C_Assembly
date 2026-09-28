from config import LOW_EFFICIENCY_PPM


class EfficiencyDetector:

    def __init__(self):

        self.low_efficiency = False

        self._last_low = False

    def update(self, ppm):

        if ppm < LOW_EFFICIENCY_PPM:
            self.low_efficiency = True

        else:

            self.low_efficiency = False

    def has_changed(self):

        """检测低效状态是否刚刚变化，用于避免重复触发事件"""
        changed = self.low_efficiency != self._last_low
        self._last_low = self.low_efficiency
        return changed

    def get_status(self):

        return {

            "low_efficiency": self.low_efficiency
        }