# -*- coding: utf-8 -*-
"""位置读数可信度实验 —— 判断"寄存器说 0，机械臂是不是真的在 0"

要分开三种情况（它们的修法完全不同）：
    (1) 静止读数稳定、写 0 后收敛到 0、机械臂也确实在原点
            → 位置反馈可信，问题在别处
    (2) 读数稳定、写 0 后收敛到 0，但机械臂【仍在极限】
            → ★ 寄存器读数和物理位置脱节（读的是设定点，不是位置）
    (3) 读数乱跳 / 不收敛
            → ★ 读数不可信

做法：三次"连续读 20 次"，中间插一次"写 0 并等 8 秒"。
每次都把读数列出来，让你一眼看出稳定还是乱跳。

用法：Factory IO 运行中，然后
      python test_pos_truth.py
⚠ 机械臂会动一下。约 1 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

N = 20          # 连续读多少次
INT = 0.15      # 每次间隔（秒）


def read_both(mc):
    """读点胶臂 X / Z 的位置"""
    x = mc.read_input_register(ARM_POS_REG.get("P0_X"))
    z = mc.read_input_register(ARM_POS_REG.get("P0_Z"))
    return x, z


def burst(mc, label):
    """连读 N 次，列出所有值，并给出统计"""
    print(f"\n--- {label}：连续读 {N} 次（间隔 {INT}s）---")
    xs, zs = [], []
    for i in range(N):
        x, z = read_both(mc)
        xs.append(x)
        zs.append(z)
        print(f"    #{i+1:2d}   P0_X={x}   P0_Z={z}")
        time.sleep(INT)

    def stat(vals, name):
        good = [v for v in vals if v is not None]
        if not good:
            print(f"    {name}: 全部读不到")
            return
        uniq = sorted(set(good))
        print(f"    {name}: 最小={min(good)}  最大={max(good)}  "
              f"不同值个数={len(uniq)}  {'★乱跳' if len(uniq) > 3 else '稳定'}")
        if len(uniq) <= 6:
            print(f"         出现过的值: {uniq}")
    stat(xs, "P0_X")
    stat(zs, "P0_Z")
    return xs, zs


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 66)
    print("位置读数可信度实验（点胶臂）")
    print("=" * 66)
    print(f"  P0_X = Input Register {ARM_POS_REG.get('P0_X')}")
    print(f"  P0_Z = Input Register {ARM_POS_REG.get('P0_Z')}")
    input("\n确认现场安全后按回车开始...")

    # ---------- 第1轮：什么都不动 ----------
    burst(mc, "第1轮：静止不动（不要碰任何东西）")
    a = input("\n  👉 现在机械臂实际在哪？ [1]原点侧  [2]极限侧  [3]中间  [4]没注意\n"
              "     输入: ").strip()

    # ---------- 动作：写 0，等足 8 秒 ----------
    print("\n" + "=" * 66)
    print("动作：把点胶臂两个寄存器都写 0，然后等 8 秒（充分给时间）")
    print("=" * 66)
    mc.write_register(ARM2_X_REG, 0)
    mc.write_register(ARM2_Z_REG, 0)
    print("  已写 0。等 8 秒...")
    for s in range(8, 0, -1):
        x, z = read_both(mc)
        print(f"    还剩 {s}s   P0_X={x}  P0_Z={z}")
        time.sleep(1.0)

    # ---------- 第2轮：再连读 ----------
    burst(mc, "第2轮：写 0 并等 8 秒之后")
    b = input("\n  👉 现在机械臂实际在哪？ [1]原点侧  [2]极限侧  [3]中间  [4]没注意\n"
              "     输入: ").strip()

    # ---------- 第3轮：写 10000 看会不会变 ----------
    print("\n" + "=" * 66)
    print("动作：把 X 写成 10000，看读数和机械臂有没有跟上")
    print("=" * 66)
    mc.write_register(ARM2_X_REG, 10000)
    time.sleep(6.0)
    burst(mc, "第3轮：写 10000 并等 6 秒")
    c = input("\n  👉 现在机械臂 X 在哪？ [1]原点侧  [2]极限侧  [3]中间  [4]没注意\n"
              "     输入: ").strip()

    # ---------- 收尾 ----------
    mc.write_register(ARM2_X_REG, 0)
    mc.write_register(ARM2_Z_REG, 0)
    time.sleep(6.0)

    print("\n" + "=" * 66)
    print("汇总（请把这段发回来）")
    print("=" * 66)
    desc = {"1": "原点侧", "2": "极限侧", "3": "中间", "4": "没注意"}
    print(f"  第1轮（静止）      →  机械臂实际在: {desc.get(a, a)}")
    print(f"  第2轮（写0+等8秒） →  机械臂实际在: {desc.get(b, b)}")
    print(f"  第3轮（写10000）   →  机械臂实际在: {desc.get(c, c)}")
    print("""
判读：
  * 三轮读数都"稳定"，且第2轮收敛到 0，机械臂也真在原点
        → 位置反馈可信，问题不在读数
  * 第2轮读数收敛到 0，但机械臂【仍在极限】
        → ★ 寄存器读的是"设定点"不是"实际位置"，位置反馈是假的
  * 某轮读数"★乱跳"
        → ★ 读数不可信，需要换判据
  * 第3轮写 10000，读数跟到 10000，机械臂也去了极限
        → 寄存器→机械臂的控制链路是好的
""")
    mc.close()


if __name__ == "__main__":
    main()
