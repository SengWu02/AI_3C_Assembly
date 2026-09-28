from config import PROTOCOL

# ========== 协议后端注册表 ==========
# 新协议只需在下面添加 import + 创建逻辑
# run() 方法接收 (host, port) 参数，返回协议驱动实例


def _build_backend(host: str, port: int):
    """根据 PROTOCOL 创建对应的后端驱动实例"""

    match PROTOCOL:

        case "virtual":
            from mock_plc import VirtualPLC
            return VirtualPLC()

        case "modbus":
            from pymodbus.client import ModbusTcpClient

            def connect():
                return client.connect()

            client = ModbusTcpClient(host=host, port=port)

            # 封装成跟 VirtualPLC 接口一致的对象
            class ModbusBackend:
                def connect(self):
                    return client.connect()

                def read_input(self, address):
                    result = client.read_discrete_inputs(address, count=1)
                    if result.isError():
                        return False
                    return result.bits[0]

                def write_coil(self, address, value):
                    client.write_coil(address, value)

                def write_register(self, address, value):
                    # 有符号转无符号
                    v = int(value)
                    if v < 0:
                        v = 65536 + v
                    client.write_register(address, v)

                def close(self):
                    client.close()

            return ModbusBackend()

        case _:
            raise ValueError(f"不支持的协议: {PROTOCOL}，可选: virtual, modbus")


# ========== 工厂驱动类 ==========


class FactoryModbusClient:
    """工厂 PLC 驱动，根据 PROTOCOL 选择实际后端"""

    def __init__(self, host, port):

        self._backend = _build_backend(host, port)

    # ---- 标准接口（协议无关） ----

    def connect(self):
        return self._backend.connect()

    def read_input(self, address):
        return self._backend.read_input(address)

    def write_coil(self, address, value):
        self._backend.write_coil(address, value)

    def write_register(self, address, value):
        self._backend.write_register(address, int(value))

    def close(self):
        self._backend.close()

        # ---- 模拟模式专用方法（virtual 协议可用，真实 PLC 返回空值） ----

    def set_input(self, address: int, value: bool):
        """设置数字量输入状态（仅模拟模式有效）"""
        if hasattr(self._backend, "set_input"):
            self._backend.set_input(address, value)

    def set_inputs(self, **kwargs):
        """批量设置数字量输入（仅模拟模式有效）"""
        if hasattr(self._backend, "set_inputs"):
            self._backend.set_inputs(**kwargs)

    def get_coil(self, address: int) -> bool:
        """读取数字量输出状态（仅模拟模式有效）"""
        if hasattr(self._backend, "get_coil"):
            return self._backend.get_coil(address)
        return False

    def get_register(self, address: int) -> int:
        """读取模拟量参数值（仅模拟模式有效）"""
        if hasattr(self._backend, "get_register"):
            return self._backend.get_register(address)
        return 0

    def print_history(self, last_n=None):
        """打印操作历史（仅模拟模式有效）"""
        if hasattr(self._backend, "print_history"):
            self._backend.print_history(last_n)

    def clear_history(self):
        """清空操作历史（仅模拟模式有效）"""
        if hasattr(self._backend, "clear_history"):
            self._backend.clear_history()