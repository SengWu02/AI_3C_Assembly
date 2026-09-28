# ============================================================================
#  modbus_client.py —— 和 Factory IO 说话的那一层（逐行注释版）
# ----------------------------------------------------------------------------
#  这一层的作用：把"写线圈/读输入/写寄存器"三种操作，
#  统一成一套跟协议无关的接口。上层 main.py 只管调用，
#  不用关心底层是真实 Modbus 还是本地假 PLC。
#
#  三种操作对应 Factory IO 的三类点：
#    write_coil(地址, True/False)   写输出线圈（开皮带、点转盘、吸嘴）
#    read_input(地址)               读输入点（限位、视觉、传感器）→ True/False
#    write_register(地址, 值)       写模拟量（机械臂位置）→ 0~10000
#
#  ★ 切换真实/模拟只改 config.PROTOCOL：
#      "modbus"  → 连真实 Factory IO（pymodbus）
#      "virtual" → 用 mock_plc.py 的假 PLC，不接现场也能跑逻辑
# ============================================================================

from config import PROTOCOL     # 只从这里读一个开关，决定用哪个后端


# ============================================================================
#  后端构建：根据 PROTOCOL 造出对应的驱动对象
# ============================================================================
def _build_backend(host: str, port: int):
    """根据 config.PROTOCOL 创建后端驱动实例。

    返回的对象必须实现这 5 个方法（上层依赖这个约定）：
        connect()                  连接，返回 True/False
        read_input(address)        读一个输入位，返回 True/False
        write_coil(address, value) 写一个输出位
        write_register(address, v) 写一个模拟量寄存器
        close()                    断开
    """
    # match 是 Python 3.10+ 的语法，相当于 if/elif 链
    match PROTOCOL:

        # ---------- 模式一：本地假 PLC（不连现场）----------
        case "virtual":
            # 延迟导入：只有真的用 virtual 时才去加载 mock_plc
            from mock_plc import VirtualPLC
            return VirtualPLC()

        # ---------- 模式二：真实 Modbus TCP（连 Factory IO）----------
        case "modbus":
            # ★ 这一句是唯一的第三方依赖。没装 pymodbus 就会在这里报
            #   ModuleNotFoundError —— 装法：pip install pymodbus
            from pymodbus.client import ModbusTcpClient

            # 创建 TCP 客户端。注意这时【还没连接】，
            # 真正连接发生在下面的 connect()
            client = ModbusTcpClient(host=host, port=port)

            # 用一个内部类把 pymodbus 的接口"翻译"成上面约定的那 5 个方法，
            # 这样上层就不用关心底下是 pymodbus 还是 VirtualPLC
            class ModbusBackend:
                def connect(self):
                    # 连 Factory IO。连不上返回 False，上层会打印"PLC连接失败"并退出
                    return client.connect()

                def read_input(self, address):
                    # 读离散输入（Discrete Input，1x 区）——对应 Factory IO 的输入点。
                    # count=1 表示只读一个位
                    result = client.read_discrete_inputs(address, count=1)
                    if result.isError():
                        # 通信出错时返回 False，而不是抛异常。
                        # ★ 副作用：出错和"读到 0"在返回值上分不出来。
                        #   调产线时如果怀疑通信不稳，要在这里加日志。
                        return False
                    return result.bits[0]        # 取第 0 位，就是 True/False

                def write_coil(self, address, value):
                    # 写线圈（Coil，0x 区）——对应 Factory IO 的输出点。
                    # 开皮带、点转盘、吸嘴、推杆都走这里
                    client.write_coil(address, value)

                def write_register(self, address, value):
                    # 写保持寄存器（Holding Register，4x 区）——机械臂模拟量。
                    # 寄存器是无符号 16 位（0~65535），但上层可能传负数，
                    # 所以这里做一次"有符号 → 无符号"的转换（补码）
                    v = int(value)
                    if v < 0:
                        v = 65536 + v
                    # ★ 检查返回值！原来直接调用不检查，写失败也是静默的，
                    #   程序以为写成功了、机械臂其实没收到 → "TRACE 说写了 500 但没动"
                    try:
                        rr = client.write_register(address, v)
                        if rr is not None and hasattr(rr, "isError") and rr.isError():
                            print(f"      [modbus] ★写寄存器失败 reg{address}={v}: {rr}")
                    except Exception as e:
                        print(f"      [modbus] ★写寄存器异常 reg{address}={v}: {e}")

                def read_register(self, address):
                    """回读保持寄存器（Holding Register，4x）。

                    返回读到的整数；读失败返回 None。
                    用途：校验刚才那次写到底有没有生效。
                    """
                    try:
                        rr = client.read_holding_registers(address, count=1)
                        if rr is None or (hasattr(rr, "isError") and rr.isError()):
                            return None
                        return rr.registers[0]
                    except Exception:
                        return None

                def read_input_register(self, address):
                    """读输入寄存器（Input Register，3x）——机械臂的实际位置在这里。

                    返回读到的整数；读失败返回 None。

                    ★ 注意：能不能读到取决于 Factory IO 那边有没有把
                      "Position (V)" 这类模拟量输入点挂到这个区。
                      读不到时返回 None，不会报错。
                    """
                    try:
                        rr = client.read_input_registers(address, count=1)
                        if rr is None or (hasattr(rr, "isError") and rr.isError()):
                            return None
                        return rr.registers[0]
                    except Exception:
                        return None

                def close(self):
                    # 断开连接。程序退出前会调
                    client.close()

            return ModbusBackend()       # 返回封装好的后端

        # ---------- 其他值：直接报错，避免静默跑错模式 ----------
        case _:
            raise ValueError(f"不支持的协议: {PROTOCOL}，可选: virtual, modbus")


# ============================================================================
#  上层的统一入口类：main.py 只用这个类，不直接用上面的后端
# ============================================================================
class FactoryModbusClient:
    """工厂 PLC 驱动。对外提供与协议无关的统一接口。

    main.py 里的用法：
        mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)   # 建对象（此时还没连）
        mc.connect()                                          # 连接
        mc.write_coil(BELT_0_COIL, True)                      # 开皮带
        mc.read_input(TABLE_A_LIMIT_90_INPUT)                 # 读限位
        mc.write_register(ARM1_X_REG, 10000)                  # 机械臂 X 伸到极限
        mc.close()                                            # 断开
    """

    def __init__(self, host, port):
        # 建对象时就根据 PROTOCOL 把后端造好（但还没连接）
        self._backend = _build_backend(host, port)

    # ------------------------------------------------------------------
    #  以下 5 个是"标准接口"，真实 Modbus 和虚拟 PLC 都支持
    # ------------------------------------------------------------------

    def connect(self):
        """连接 PLC。返回 True/False。False 时程序应该停下别硬跑。"""
        return self._backend.connect()

    def read_input(self, address):
        """读一个输入位（限位/视觉/传感器）。返回 True/False。

        ⚠ 通信出错也返回 False，跟"读到 0"无法区分（见后端里的说明）。
        """
        return self._backend.read_input(address)

    def write_coil(self, address, value):
        """写一个输出位（开/关某个设备）。value 传 True 或 False。"""
        self._backend.write_coil(address, value)

    def write_register(self, address, value):
        """写一个模拟量寄存器（机械臂位置）。value 传 0~10000。

        int(value) 是保险：万一上层传了浮点数，这里转成整数再发。
        """
        self._backend.write_register(address, int(value))

    def read_input_register(self, address):
        """读一个【输入寄存器】（Input Register，3x）——机械臂的实际位置。

        返回读到的整数；以下情况返回 None：
          * 后端不支持
          * Float 点没挂到 Modbus（当前很可能就是这个情况）
          * 读失败

        ★ 这是唯一能拿到"机械臂实际在哪"的通道。
          用之前先拿 test_read_position.py 确认编号。
        """
        if hasattr(self._backend, "read_input_register"):
            return self._backend.read_input_register(address)
        return None

    def read_register(self, address):
        """回读一个模拟量寄存器。

        用途：校验"刚才那次写到底有没有生效"。
        返回读到的整数；以下情况返回 None：
          * 后端不支持回读（虚拟模式、或旧实现）
          * 读失败 / 通信错误

        ★ 有了它就能回答"TRACE 说写了 500，寄存器里到底是不是 500"。
        """
        if hasattr(self._backend, "read_register"):
            return self._backend.read_register(address)
        return None

    def close(self):
        """断开连接。程序退出前调用。"""
        self._backend.close()

    # ------------------------------------------------------------------
    #  以下方法只有"虚拟模式(virtual)"才真正有效
    #  真实 Modbus 模式下它们是空操作（或返回默认值），
    #  因为真实 PLC 的输入是现场硬件给的，Python 改不了。
    # ------------------------------------------------------------------

    def set_input(self, address: int, value: bool):
        """【仅虚拟模式】强行设置一个输入位的值。

        用途：写测试脚本时模拟"限位到了"、"视觉看到料了"，
        不用真的等现场硬件动作。
        """
        if hasattr(self._backend, "set_input"):
            self._backend.set_input(address, value)

    def set_inputs(self, **kwargs):
        """【仅虚拟模式】一次设置多个输入位。用法：mc.set_inputs(a=True, b=False)"""
        if hasattr(self._backend, "set_inputs"):
            self._backend.set_inputs(**kwargs)

    def get_coil(self, address: int) -> bool:
        """读一个输出线圈的当前状态。

        ⚠ 真实 Modbus 模式下【恒返回 False】——因为后端没实现 get_coil。
          已知影响：main.py 用它来显示报警状态，所以真机上报警灯显示永远"正常"。
          要修就得在后端里实现线圈回读（pymodbus 的 read_coils）。
        """
        if hasattr(self._backend, "get_coil"):
            return self._backend.get_coil(address)
        return False

    def get_register(self, address: int) -> int:
        """读一个模拟量寄存器的值。【仅虚拟模式有效】，真机返回 0。"""
        if hasattr(self._backend, "get_register"):
            return self._backend.get_register(address)
        return 0

    def print_history(self, last_n=None):
        """【仅虚拟模式】打印操作历史，调试时序时很有用。"""
        if hasattr(self._backend, "print_history"):
            self._backend.print_history(last_n)

    def clear_history(self):
        """【仅虚拟模式】清空操作历史。"""
        if hasattr(self._backend, "clear_history"):
            self._backend.clear_history()
