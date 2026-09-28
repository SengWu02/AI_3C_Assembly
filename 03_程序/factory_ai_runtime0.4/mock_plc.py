
"""
虚拟 PLC 模拟器

协议无关的通用 PLC 模拟器。可模拟任意品牌 PLC（Modbus、西门子S7、三菱FX等），
只要求真实 PLC 驱动实现了以下 5 个方法：
    connect() -> bool
    read_input(address) -> bool
    write_coil(address, value: bool)
    write_register(address, value: int)
    close()

用法：
    1. 在 config.py 中设置 PROTOCOL = "virtual"
    2. 在 modbus_client.py 工厂函数中创建 VirtualPLC()
    3. 通过 set_input() 实时注入传感器信号
    4. 通过 run_scenario() 按时间轴自动编排场景
"""

import time
from typing import Optional


class VirtualPLC:
    """协议无关的通用 PLC 模拟器"""

    def __init__(self):

        # 数字量输入（传感器/按钮/限位开关）
        self.digital_inputs: dict[int, bool] = {}

        # 数字量输出（继电器/电磁阀/电机启停）
        self.digital_outputs: dict[int, bool] = {}

        # 模拟量参数（变频器频率/目标值/计数器）
        self.analog_params: dict[int, int] = {
            0: 0,    # 转盘位置，初始0
        }

        # 操作日志：记录所有写入操作，方便测试验证
        self.history: list[dict] = []

    # ==================== 接口方法（协议无关） ====================

    def connect(self) -> bool:
        """模拟连接PLC，总是成功"""
        self.history.append({"time": time.time(), "action": "connect", "result": True})
        return True

    def read_input(self, address: int) -> bool:
        """读取数字量输入（传感器）"""
        return self.digital_inputs.get(address, False)

    def write_coil(self, address: int, value: bool):
        """写入数字量输出（执行器）"""
        self.digital_outputs[address] = value
        self.history.append({
            "time": time.time(),
            "action": "write_coil",
            "address": address,
            "value": value,
        })

    def write_register(self, address: int, value: int):
        """写入模拟量参数"""
        self.analog_params[address] = value
        self.history.append({
            "time": time.time(),
            "action": "write_register",
            "address": address,
            "value": value,
        })

    def close(self):
        """断开连接"""
        self.history.append({"time": time.time(), "action": "close"})

    # ==================== 场景控制 ====================

    def set_input(self, address: int, value: bool):
        """设置数字量输入状态"""
        self.digital_inputs[address] = value

    def set_inputs(self, **kwargs):
        """批量设置数字量输入

        用法: plc.set_inputs(**{0: True, 3: True, 5: False})
        """
        for addr, val in kwargs.items():
            self.digital_inputs[int(addr)] = bool(val)

    def get_coil(self, address: int) -> bool:
        """读取数字量输出当前状态"""
        return self.digital_outputs.get(address, False)

    def get_register(self, address: int) -> int:
        """读取模拟量参数当前值"""
        return self.analog_params.get(address, 0)

    def clear_history(self):
        """清空操作日志"""
        self.history.clear()

    def print_history(self, last_n: Optional[int] = None):
        """打印最近 N 条操作日志"""
        items = self.history[-last_n:] if last_n else self.history
        for h in items:
            t = time.strftime("%H:%M:%S", time.localtime(h["time"]))
            match h["action"]:
                case "write_coil":
                    print(f"  [{t}] DO[{h['address']}] -> {h['value']}")
                case "write_register":
                    print(f"  [{t}] AO[{h['address']}] -> {h['value']}")
                case _:
                    print(f"  [{t}] {h['action']}")

    def run_scenario(self, events: list[dict], loop_interval: float = 0.1):
        """按时间轴自动触发数字量输入变化

        events: [
            {"at": 1.0, "inputs": {0: True}},           # 1秒后触发视觉传感器
            {"at": 1.5, "inputs": {0: False}},          # 1.5秒后释放
            {"at": 3.0, "inputs": {0: True, 1: True}},  # 3秒后同时触发多个输入
        ]
        """
        if not events:
            return False

        start = time.time()
        while events:
            now = time.time() - start
            while events and now >= events[0]["at"]:
                ev = events.pop(0)
                for addr, val in ev["inputs"].items():
                    self.set_input(int(addr), bool(val))
            if not events:
                break
            time.sleep(loop_interval)

        return True


# ==================== 快速测试 ====================
if __name__ == "__main__":
    print("VirtualPLC 自检...")
    plc = VirtualPLC()
    assert plc.connect() == True
    assert plc.read_input(0) == False

    plc.set_input(0, True)
    assert plc.read_input(0) == True

    plc.write_coil(0, True)
    assert plc.get_coil(0) == True

    plc.write_register(10, 42)
    assert plc.get_register(10) == 42

    assert len(plc.history) == 3  # connect + write_coil + write_register

    print(f"操作记录 ({len(plc.history)} 条):")
    plc.print_history()
    print("VirtualPLC 自检通过 [OK]")
