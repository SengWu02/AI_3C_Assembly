class SafetyManager:

    def __init__(self):

        self.emergency_stop = False

    def evaluate(
        self,
        jam_status,
        pusher_status
    ):

        if jam_status["is_blocked"]:

            self.emergency_stop = True

            return

        if pusher_status["push_timeout"]:

            self.emergency_stop = True

            return

        self.emergency_stop = False

    def get_status(self):

        return {

            "emergency_stop": self.emergency_stop
        }