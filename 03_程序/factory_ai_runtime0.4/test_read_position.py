# -*- coding: utf-8 -*-
"""试读机械臂的【实际位置】——看输入寄存器能不能读到。

为什么写这个：
    trace 里现在只有"命令值"（比如 X reg0 -> 500），那是我们写下去的数字，
    不是机械臂的实际位置。场景里其实有四个位置反馈点：
        Two-Axis Pick & Place 2 X Position (V)
        Two-Axis Pick & Place 2 Z Position (V)
        Two-Axis Pick & Place 0 X Position (V)
        Two-Axis Pick & Place 0 Z Position (V)
    但它们没挂在 ModbusTCPServer 的 NumericInput 上，所以程序一直读不到。

    这个脚本做两件事：
      1) 直接把 Input Register 0~7 全读一遍，看有没有值
      2) 把机械臂动到一个明显的位置，再读一遍，看哪几个寄存器跟着变
         → 跟着变的那个就是位置反馈

用法：Factory IO 运行中（点过 Reset），然后
      python test_read_position.py
⚠ 机械臂会动，确认现场安全。约 1 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient


def read_iregs(mc, count=8):
    """读 Input Register 0..count-1，返回列表（读不到填 None）"""
    out = []
    for a in range(count):
        try:
            rr = mc._backend._client_read_input_register(a) if hasattr(mc._backend, "_client_read_input_register") else None
        except Exception:
            rr = None
        out.append(rr)
    return out


def try_read(mc, addr):
    """直接通过 pymodbus 读一个输入寄存器"""
    try:
        from pymodbus.client import ModbusTcpClient
    except Exception:
        return None
    try:
        c = mc._backend
        client = getattr(c, "client", None)
        return None
    except Exception:
        return None


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 66)
    print("输入寄存器 / 位置反馈 读取测试")
    print("=" * 66)

    # 直接用 pymodbus 读，绕过封装，把所有寄存器区都试一遍
    try:
        from pymodbus.client import ModbusTcpClient
    except Exception as e:
        print("没装 pymodbus:", e)
        return
    cli = ModbusTcpClient(host=MODBUS_HOST, port=MODBUS_PORT)
    if not cli.connect():
        print("直连失败")
        return
    print("已直连 Factory IO\n")

    def dump(label):
        print(f"--- {label} ---")
        # 输入寄存器 3x
        try:
            rr = cli.read_input_registers(0, count=8)
            if rr is None or (hasattr(rr, "isError") and rr.isError()):
                print(f"  Input Register 0..7 : 读取失败 ({rr})")
            else:
                print(f"  Input Register 0..7 : {rr.registers}")
        except Exception as e:
            print(f"  Input Register 0..7 : 异常 {e}")
        # 保持寄存器 4x
        try:
            rr = cli.read_holding_registers(0, count=8)
            if rr is None or (hasattr(rr, "isError") and rr.isError()):
                print(f"  Holding Register 0..7 : 读取失败 ({rr})")
            else:
                print(f"  Holding Register 0..7 : {rr.registers}")
        except Exception as e:
            print(f"  Holding Register 0..7 : 异常 {e}")
        # 离散输入 1x（对照，这个已知能读）
        try:
            rr = cli.read_discrete_inputs(0, count=13)
            if rr is None or (hasattr(rr, "isError") and rr.isError()):
                print(f"  Discrete Input 0..12 : 读取失败 ({rr})")
            else:
                print(f"  Discrete Input 0..12 : {[int(b) for b in rr.bits[:13]]}")
        except Exception as e:
            print(f"  Discrete Input 0..12 : 异常 {e}")
        print("")

    def setpos(reg, val):
        cli.write_register(reg, val)

    input("确认现场安全后按回车开始...")

    # 1) 先全部归零，记录基线
    print("\n[1] 四个寄存器全部归零，记录基线")
    for r in (0, 1, 2, 3):
        setpos(r, 0)
    time.sleep(3.0)
    dump("归零后")

    # 2) 把锁螺丝臂 X 伸到 8000（明显位置）
    print("[2] 锁螺丝臂 X (Holding Reg 0) 伸到 8000")
    setpos(0, 8000)
    time.sleep(3.0)
    dump("锁螺丝臂 X = 8000")

    # 3) 再把锁螺丝臂 X 收到 1000
    print("[3] 锁螺丝臂 X 收到 1000")
    setpos(0, 1000)
    time.sleep(3.0)
    dump("锁螺丝臂 X = 1000")

    # 4) 点胶臂 X 伸到 8000（换一个臂）
    print("[4] 点胶臂 X (Holding Reg 2) 伸到 8000")
    setpos(0, 0)
    setpos(2, 8000)
    time.sleep(3.0)
    dump("点胶臂 X = 8000")

    # 收尾
    print("[收尾] 全部归零")
    for r in (0, 1, 2, 3):
        setpos(r, 0)
    time.sleep(2.0)
    cli.close()

    print("""
判读：
  * Input Register 0..7 全是 0 或读取失败
        → 位置反馈没挂到 Modbus。请在 Factory IO 的场景里，
          把四个 "Position (V)" 点分配到 Input Register。
  * 某几个 Input Register 跟着机械臂动作变化
        → 那就是位置反馈！把它的编号告诉我，
          我在程序里加上"实际位置"的记录。
  * Holding Register 0..7 也读不到
        → 说明你的驱动里"读寄存器"配的是别的区，需要一起调整。
""")


if __name__ == "__main__":
    main()
