import time

from config import PUSHER_TIMEOUT_SECONDS


class PusherMonitor:

    def __init__(self):

        self.push_start_time = None

        self.push_timeout = False

        self._last_timeout = False

        self.timeout_seconds = PUSHER_TIMEOUT_SECONDS

    def start_push(self):

        self.push_start_time = time.time()

        self.push_timeout = False

        self._last_timeout = False

    def update(self, pusher_back):

        if self.push_start_time is None:

            return

        # 推杆已返回
        if pusher_back:

            self.push_start_time = None
            self.push_timeout = False

            return

        duration = time.time() - self.push_start_time

        if duration > self.timeout_seconds:

            self.push_timeout = True

    def has_changed(self):

        """检测超时状态是否刚变化，避免重复触发事件"""
        changed = self.push_timeout != self._last_timeout
        self._last_timeout = self.push_timeout
        return changed

    def get_status(self):

        return {

            "push_timeout": self.push_timeout
        }