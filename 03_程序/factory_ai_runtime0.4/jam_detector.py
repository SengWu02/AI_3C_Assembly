import time

from config import JAM_THRESHOLD_SECONDS


class JamDetector:

    def __init__(self):

        self.block_start_time = None

        self.is_blocked = False

        self._last_blocked = False

    def update(self, vision_sensor):

        if vision_sensor:

            if self.block_start_time is None:

                self.block_start_time = time.time()

            duration = time.time() - self.block_start_time

            if duration > JAM_THRESHOLD_SECONDS:

                self.is_blocked = True

        else:

            self.block_start_time = None

            self.is_blocked = False

    def has_changed(self):

        """检测堵塞状态是否刚变化，避免重复触发事件"""
        changed = self.is_blocked != self._last_blocked
        self._last_blocked = self.is_blocked
        return changed

    def get_status(self):

        return {

            "is_blocked": self.is_blocked
        }