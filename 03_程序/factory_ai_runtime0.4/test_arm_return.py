# -*- coding: utf-8 -*-
"""机械臂"从极限位回原点"专项探针。

背景：现场反馈"机械臂取料后还是处在极限位置"，回原点没生效。
      之前 test_arm_moving.py 是从【原点】出发测的，测不出这个问题。
      这次专门从【伸展位】出发，一步一步验证写 0 到底有没有把它拉回来。

测什么：
  阶段1  确认起始位置：写到 X=10000 Z=8400（=取料/放料后的姿态）
  阶段2  只写 X=0，观察 X 缩回要多久、到底有没有缩回
  阶段3  只写 Z=0，观察 Z 抬起要多久
  阶段4  完整跑一次 _arm_home 的三步（前伸→保持→归零），
         并在每一步之后问你机械臂实际在哪

用法：Factory IO 运行中（点过 Reset），然后
      python test_arm_return.py
⚠ 机械臂会真的动，确认现场安全。整个过程约 1 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05


def state(mc, x_moving, z_moving):
    return (bool(mc.read_input(x_moving)), bool(mc.read_input(z_moving)))


def watch(mc, x_moving, z_moving, seconds, label):
    """观察 Moving 信号跳变，返回信号从抬起到落下的耗时（没抬起返回 None）。"""
    print(f"\n--- {label} ---")
    t0 = time.time()
    rose = False
    rose_at = None
    last = None
    while time.time() - t0 < seconds:
        cur = state(mc, x_moving, z_moving)
        if cur != last:
            el = time.time() - t0
            print(f"  t={el:5.2f}s  X_moving={int(cur[0])}  Z_moving={int(cur[1])}")
            last = cur
        if not rose and (cur[0] or cur[1]):
            rose = True
            rose_at = time.time() - t0
        if rose and not cur[0] and not cur[1]:
            done = time.time() - t0
            print(f"  → 信号抬起于 {rose_at:.2f}s，落下于 {done:.2f}s（运动时长 {done - rose_at:.2f}s）")
            return done - rose_at
        time.sleep(POLL)
    if not rose:
        print(f"  → {seconds}s 内信号从未抬起：机械臂根本没动")
        return None
    print(f"  → 信号抬起后 {seconds}s 内没落下：卡住了")
    return -1


def ask(what):
    return input(f"  请肉眼确认：{what}\n"
                 f"    [1] 原点侧(上/里)  [2] 极限侧(下/外)  [3] 中间  [4] 没动\n"
                 f"    输入 1/2/3/4: ").strip()


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    X_M, Z_M = ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT   # 锁螺丝位

    print("=" * 64)
    print("机械臂 回原点 专项探针（从伸展位出发）")
    print("=" * 64)
    print(f"  锁螺丝位: X 寄存器={ARM1_X_REG}  Z 寄存器={ARM1_Z_REG}")
    print(f"            X_moving=input {X_M}  Z_moving=input {Z_M}")
    print("\n⚠ 机械臂会真的动，确认现场安全后按回车")
    input("按回车开始...")

    # ---------- 阶段1：摆到伸展位 ----------
    print("\n" + "=" * 64)
    print("阶段1  把它摆到【伸展位】（模拟取料/放料刚做完的姿势）")
    print("=" * 64)
    print(f"  写 X={ARM1_X_REG} → 10000，Z={ARM1_Z_REG} → 8400")
    mc.write_register(ARM1_X_REG, 10000)
    mc.write_register(ARM1_Z_REG, 8400)
    watch(mc, X_M, Z_M, 6, "摆到伸展位的过程")
    a = ask("现在机械臂在哪？")
    print(f"  → 记录：{a}")

    if a == "4":
        print("\n机械臂在伸展位都没动，先不用往下测了——")
        print("问题不在回原点，在于写寄存器根本没让它动。")
        print("请检查 Factory IO 的驱动是否绑定到这两个寄存器。")
        mc.close()
        return

    # ---------- 阶段2：只写 X=0 ----------
    print("\n" + "=" * 64)
    print("阶段2  只把 X 写 0，看它缩不缩得回来")
    print("=" * 64)
    mc.write_register(ARM1_X_REG, 0)
    moved = watch(mc, X_M, Z_M, 8, "X → 0")
    b = ask("现在 X 轴在哪？（Z 应该还停在下面）")
    print(f"  → 记录：{b}")

    # ---------- 阶段3：只写 Z=0 ----------
    print("\n" + "=" * 64)
    print("阶段3  只把 Z 写 0，看它抬不抬得起来")
    print("=" * 64)
    mc.write_register(ARM1_Z_REG, 0)
    watch(mc, X_M, Z_M, 8, "Z → 0")
    c = ask("现在 Z 轴在哪？")
    print(f"  → 记录：{c}")

    # ---------- 阶段4：完整跑一次 _arm_home 的三步 ----------
    print("\n" + "=" * 64)
    print("阶段4  完整跑一次「前伸 → 保持 → 归零」")
    print("=" * 64)
    print(f"  先摆回伸展位 X=10000 Z=8400")
    mc.write_register(ARM1_X_REG, 10000)
    mc.write_register(ARM1_Z_REG, 8400)
    watch(mc, X_M, Z_M, 6, "摆回伸展位")

    print(f"\n  [4.1] 前伸：写 X={ARM_HOME_PRESTRETCH} Z={ARM_HOME_PRESTRETCH}")
    mc.write_register(ARM1_X_REG, ARM_HOME_PRESTRETCH)
    mc.write_register(ARM1_Z_REG, ARM_HOME_PRESTRETCH)
    watch(mc, X_M, Z_M, ARM_HOME_PRESTRETCH_HOLD + 1.5, "前伸过程")
    d = ask(f"前伸 {ARM_HOME_PRESTRETCH} 之后，机械臂往外/往下走了吗？")

    print(f"\n  [4.2] 保持 {ARM_HOME_PRESTRETCH_HOLD}s（程序里就是这段）")
    time.sleep(ARM_HOME_PRESTRETCH_HOLD)

    print(f"\n  [4.3] 归零：写 X=0 Z=0，然后等 {ARM_HOME_SETTLE}s")
    mc.write_register(ARM1_X_REG, 0)
    mc.write_register(ARM1_Z_REG, 0)
    watch(mc, X_M, Z_M, ARM_HOME_SETTLE + 2.0, "归零过程")
    e = ask("走完这一整套之后，机械臂回到原点了吗？")

    # ---------- 汇总 ----------
    print("\n" + "=" * 64)
    print("汇总（请把这段发回来）")
    print("=" * 64)
    desc = {"1": "原点侧", "2": "极限侧", "3": "中间", "4": "没动"}
    print(f"  阶段1 摆到伸展位后          → {desc.get(a, a)}")
    print(f" 阶段2 只写 X=0 之后         → {desc.get(b, b)}   (X 运动时长 {moved if moved is None else round(moved,2)}s)")
    print(f"  阶段3 只写 Z=0 之后          → {desc.get(c, c)}")
    print(f"  阶段4.1 前伸后是否动作       → {desc.get(d, d)}")
    print(f" 阶段4.3 整套跑完是否回原点   → {desc.get(e, e)}")

    print("""
判读：
  * 阶段2 显示"原点侧" → 写 0 能拉回来，问题在程序时序（回零前的前伸把它又推回去了）
  * 阶段2 显示"没动"/"极限侧" → 写 0 拉不回来，是机械/驱动问题，不是程序问题
  * 阶段4.3 显示"极限侧" 而阶段2 正常 → 就是"前伸 → 归零"这套动作本身把它留在了外面
""")
    mc.close()


if __name__ == "__main__":
    main()
