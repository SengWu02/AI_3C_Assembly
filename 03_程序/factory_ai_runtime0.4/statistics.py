import time


class FactoryStatistics:

    def __init__(self):

        self.total_detected = 0
        self.total_green_detected = 0

        self.target_blue = 0
        self.target_green = 0

        self.start_time = time.time()

        self.last_detect_time = time.time()

        self.parts_per_minute = 0

    def add_detected(self):

        self.total_detected += 1

        current_time = time.time()

        delta = current_time - self.last_detect_time

        if delta > 0:

            self.parts_per_minute = 60 / delta

        self.last_detect_time = current_time

    def add_green_detected(self):

        self.total_green_detected += 1

        current_time = time.time()

        delta = current_time - self.last_detect_time

        if delta > 0:

            self.parts_per_minute = 60 / delta

        self.last_detect_time = current_time

    def set_target_blue(self, target):

        self.target_blue = target

    def set_target_green(self, target):

        self.target_green = target
    def get_runtime_seconds(self):

        return int(time.time() - self.start_time)

    def get_statistics(self):

        return {

            "total_detected": self.total_detected,
            "total_green_detected": self.total_green_detected,

            "target_blue": self.target_blue,
            "target_green": self.target_green,

            "runtime_seconds": self.get_runtime_seconds(),

            "parts_per_minute": round(
                self.parts_per_minute,
                2
            )
        }