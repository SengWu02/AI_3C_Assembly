class FactoryStateMachine:

    def __init__(self):

        self.machine_state = "IDLE"

    def update(self, vision_sensor):

        if vision_sensor:

            self.machine_state = "OBJECT_DETECTED"

        else:

            self.machine_state = "RUNNING"

    def get_status(self):

        return {

            "machine_state": self.machine_state
        }