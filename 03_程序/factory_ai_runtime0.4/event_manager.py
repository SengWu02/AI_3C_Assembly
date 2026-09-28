import time


class EventManager:

    def __init__(self):

        self.events = []

    def add_event(self, event_type, message):

        event = {

            "time": time.strftime("%H:%M:%S"),

            "type": event_type,

            "message": message
        }

        self.events.append(event)

        print(f"[EVENT] {event}")

    def get_recent_events(self, limit=20):

        return self.events[-limit:]