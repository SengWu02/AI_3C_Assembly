from simple_pid import PID


class SpeedController:

    def __init__(self, modbus, line_id=1):

        self.modbus = modbus
        self.line_id = line_id

        # Modbus 地址绑定
        if line_id == 1:
            self.reg_address = 0         # Holding Reg 0
            self.encoder_a_addr = 6      # Input 6
            self.encoder_b_addr = 7      # Input 7
        elif line_id == 2:
            self.reg_address = 1         # Holding Reg 1
            self.encoder_a_addr = 8      # Input 8
            self.encoder_b_addr = 9      # Input 9
        else:
            raise ValueError(f"不支持的产线: {line_id}")

        # PID 参数
        self.pid = PID(
            Kp=2.0,
            Ki=0.3,
            Kd=0.05,
            setpoint=0,
            output_limits=(-10, 10)
        )

        # 编码器状态
        self.pulse_count = 0
        self.last_a = False
        self.last_b = False

        # 当前实际速度（件/分）
        self.current_ppm = 0.0

        # 脉冲换算系数
        self.pulses_per_part = 10

    def update_encoder(self):

        """读取编码器信号并更新脉冲计数"""

        signal_a = self.modbus.read_input(self.encoder_a_addr)
        signal_b = self.modbus.read_input(self.encoder_b_addr)

        if signal_a and not self.last_a:
            if signal_b:
                self.pulse_count -= 1
            else:
                self.pulse_count += 1

        self.last_a = signal_a
        self.last_b = signal_b

    def set_target_ppm(self, target_ppm):

        """设置目标产能（件/分）"""

        self.pid.setpoint = float(target_ppm)

    def set_pid_params(self, kp, ki, kd):

        """动态调整 PID 参数"""

        self.pid.Kp = kp
        self.pid.Ki = ki
        self.pid.Kd = kd

    def update_speed(self, actual_ppm):

        """PID 计算并写入速度到寄存器，返回当前速度值"""

        self.current_ppm = actual_ppm

        speed = self.pid(actual_ppm)

        # 将 -10~+10 映射到 0~20（PLC无符号寄存器）
        register_value = int(speed) + 10
        register_value = max(0, min(20, register_value))

        self.modbus.write_register(self.reg_address, register_value)

        return speed

    def get_encoder_pulses(self):

        """返回脉冲计数"""

        return self.pulse_count

    def reset_pulses(self):

        """每秒重置脉冲计数"""

        self.pulse_count = 0

    def get_status(self):

        """返回当前状态"""

        return {
            "line_id": self.line_id,
            "setpoint_ppm": round(self.pid.setpoint, 1),
            "current_ppm": round(self.current_ppm, 1),
            "speed_output": round(self.pid.last_output if hasattr(self.pid, 'last_output') else 0, 1),
            "kp": self.pid.Kp,
            "ki": self.pid.Ki,
            "kd": self.pid.Kd
        }
