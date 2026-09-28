# -*- coding: utf-8 -*-
"""点胶臂"从 5000 回 0"轨迹探针 —— 验证回零是不是冲过了 0

背景（从 arm_trace.log + arm_pos.log 推出的假设）：
    点胶臂 X 写到 5000，到位读数 4992；
    之后写 0 回零，下一次读到的是 9999。
    → 假设：从 5000 往 0 回的时候【冲过了 0】，一路撞到另一端限位 9999。

这个探针全程 0.2 秒采样一次，把"回零"这段轨迹完整画出来：
    如果轨迹是 5000 → 3000 → 1000 → 0        = 正常回零
    如果轨迹是 5000 → 1000 → 0 → 9999         = ★ 冲过头（假设成立）
    如果轨迹是 5000 → 9999（跳变）             = 读数是假的

用法：Factory IO 运行中，然后
      python test_dispense_return.py
约 1 分钟。机械臂会动。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.2
XREG = ARM_POS_REG.get("P0_X")            # 点胶臂 X 位置（Input Register 2）
ZREG = ARM_POS_REG.get("P0_Z")


def pos(mc):
    return mc.read_input_register(XREG), mc.read_input_register(ZREG)


def watch(mc, seconds, label):
    """连续采样，打印轨迹"""
    print(f"\n--- {label}（每 {POLL}s 采样一次，共 {seconds}s）---")
    t0 = time.time()
    hist = []
    while time.time() - t0 < seconds:
        x, z = pos(mc)
        el = time.time() - t0
        hist.append((el, x, z))
        print(f"    t={el:5.2f}s   P0_X={x}   P0_Z={z}")
        time.sleep(POLL)
    return hist


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 68)
    print("点胶臂 回零轨迹探针")
    print("=" * 68)
    print(f"  点胶臂 X = Holding Register {ARM2_X_REG} / 位置 Input Register {XREG}")
    print(f"  点胶臂 Z = Holding Register {ARM2_Z_REG} / 位置 Input Register {ZREG}")
    input("\n确认现场安全后按回车开始...")

    # ---------- 阶段1：归零，建立起点 ----------
    print("\n[阶段1] 先写 0 归零，等 4 秒")
    mc.write_register(ARM2_X_REG, 0)
    mc.write_register(ARM2_Z_REG, 0)
    watch(mc, 4.0, "归零后（起点应该是 0）")

    # ---------- 阶段2：伸到 5000 ----------
    print("\n[阶段2] 写 X = 5000（点胶位），等 5 秒")
    mc.write_register(ARM2_X_REG, 5000)
    watch(mc, 5.0, "伸到 5000 的过程")

    # ---------- 阶段3：★ 回零，重点看这一段 ----------
    print("\n" + "=" * 68)
    print("★ [阶段3] 写 X = 0（回零）—— 重点看它冲不冲过 0")
    print("=" * 68)
    mc.write_register(ARM2_X_REG, 0)
    hist = watch(mc, 8.0, "从 5000 回 0 的全过程")

    # ---------- 分析 ----------
    print("\n" + "=" * 68)
    print("轨迹分析")
    print("=" * 68)
    xs = [h[1] for h in hist if h[1] is not None]
    if xs:
        print(f"  起点 {xs[0]}  →  终点 {xs[-1]}  →  最大值 {max(xs)}  最小值 {min(xs)}")
        # 找有没有"越过 0 之后又变大"
        overshoot = None
        for i in range(1, len(xs)):
            if xs[i-1] is not None and xs[i] is not None:
                if xs[i-1] < 500 and xs[i] > 3000:
                    overshoot = (i, xs[i-1], xs[i])
                    break
        if overshoot:
            i, a, b = overshoot
            print(f"  ★★★ 发现冲过头：第 {i} 个采样点从 {a} 跳到 {b}")
            print(f"      = 臂从 {a} 直接窜到 {b}，说明回零冲过了 0")
        elif max(xs) > 5000:
            print(f"  ★ 最大值 {max(xs)} 超过了命令值 5000")
        else:
            print("  没有发现冲过头，轨迹平滑收敛")
    print("")
    print("  判读：")
    print("    · 轨迹平滑 5000→0，终点 0     → 回零正常，9999 另有原因")
    print("    · 轨迹出现 0→9999 的跳变        → ★ 回零冲过头（假设成立）")
    print("    · 轨迹卡在中间不动              → 轴被卡住")

    # 收尾
    print("\n[收尾] 写 0")
    mc.write_register(ARM2_X_REG, 0)
    mc.write_register(ARM2_Z_REG, 0)
    time.sleep(3.0)
    x, z = pos(mc)
    print(f"  最终位置 P0_X={x} P0_Z={z}")
    mc.close()


if __name__ == "__main__":
    main()
