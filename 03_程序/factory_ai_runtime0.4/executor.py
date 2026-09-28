import time


class FactoryExecutor:

    def __init__(self, modbus, config, line_id=1):

        self.modbus = modbus
        self.config = config
        self.line_id = line_id

        # 根据产线号绑定对应的线圈地址
        if line_id == 1:
            self.conveyor_coil = config.CONVEYOR_COIL
            self.pusher_coil = config.PUSHER_COIL
        elif line_id == 2:
            self.conveyor_coil = config.CONVEYOR1_COIL
            self.pusher_coil = config.PUSHER1_COIL
        else:
            raise ValueError(f"不支持的产线编号: {line_id}")

    def start_conveyor(self):

        self.modbus.write_coil(
            self.conveyor_coil,
            True
        )

    def stop_conveyor(self):

        self.modbus.write_coil(
            self.conveyor_coil,
            False
        )

    def push_forward(self):

        self.modbus.write_coil(
            self.pusher_coil,
            True
        )

    def push_back(self):

        self.modbus.write_coil(
            self.pusher_coil,
            False
        )

    def push_object(self):

        self.push_forward()

        time.sleep(1)

        self.push_back()