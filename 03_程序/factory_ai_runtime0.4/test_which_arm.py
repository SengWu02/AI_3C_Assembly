# -*- coding: utf-8 -*-
"""决定性测试：哪个寄存器驱动哪个机械臂？

背景（test_reg_drive.py 的结果）：
    写 reg0 = 3000  →  写入成功，但四个 Moving 信号全没动，没有任何轴运动
    写 reg2 = 3000  →  写入成功，input9 (0_X) 抬起，你确认点胶臂动了
    写 reg2 = 500   →  同样有信号，你确认点胶臂动了

    也就是说 reg0 驱动不了任何东西，而 reg2 能驱动一个真实的臂。
    但我们一直认为 reg0 = 锁螺丝臂 X、reg2 = 点胶臂 X。
    → 这个对应关系很可能是错的，或者 reg0 那个通道没接。

这个脚本用【大动作】逐个试四个寄存器，每个都让你肉眼确认"哪个臂动了、动多少"。
大动作（走满 10000）比 3000 明显得多，不会看错。

用法：Factory IO 运行中（点过 Reset），然后
      python test_which_arm.py
⚠ 机械臂会大幅运动，确认现场安全。约 2 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05
AXES = [
    ("reg0  (config 里叫 ARM1_X_REG / 锁螺丝臂X)", ARM1_X_REG, ARM2_MOVING_X_INPUT),
    ("reg1  (config 里叫 ARM1_Z_REG / 锁螺丝臂Z)", ARM1_Z_REG, ARM2_MOVING_Z_INPUT),
    ("reg2  (config 里叫 ARM2_X_REG / 点胶臂X)",   ARM2_X_REG, ARM0_MOVING_X_INPUT),
    ("reg3  (config 里叫 ARM2_Z_REG / 点胶臂Z)",   ARM2_Z_REG, ARM0_MOVING_Z_INPUT),
]


def all_moving(mc):
    return (bool(mc.read_input(ARM2_MOVING_X_INPUT)),
            bool(mc.read_input(ARM2_MOVING_Z_INPUT)),
            bool(mc.read_input(ARM0_MOVING_X_INPUT)),
            bool(mc.read_input(ARM0_MOVING_Z_INPUT)))


def zero_all(mc):
    for r in (ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG):
        mc.write_register(r, 0)
    time.sleep(2.5)


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 70)
    print("决定性测试：哪个寄存器驱动哪个机械臂？")
    print("=" * 70)
    print("  每个寄存器都会走满行程（写 10000），动作很大，不会看错。")
    print("  每次都会问你：哪个臂动了？动了多少？")
    print("\n⚠ 机械臂会大幅运动，确认现场安全后按回车")
    input("按回车开始...")

    answers = {}
    for label, reg, moving_addr in AXES:
        print("\n" + "=" * 70)
        print(f"测试 {label}")
        print("=" * 70)
        zero_all(mc)
        print(f"  已把四个寄存器全归零。回读 reg{reg} = {mc.read_register(reg)}")

        print(f"  现在写 reg{reg} = 10000（走满行程）")
        mc.write_register(reg, 10000)
        rb = mc.read_register(reg)
        print(f"  回读 reg{reg} = {rb}" + ("   ✅" if rb == 10000 else "   ★★ 回读不符"))

        # 观察信号
        t0 = time.time()
        last = None
        rose = False
        while time.time() - t0 < 4.0:
            cur = all_moving(mc)
            if cur != last:
                el = time.time() - t0
                print(f"    t={el:5.2f}s  2_X={int(cur[0])} 2_Z={int(cur[1])} "
                      f"0_X={int(cur[2])} 0_Z={int(cur[3])}")
                last = cur
                if any(cur):
                    rose = True
            time.sleep(POLL)
        print(f"  → 信号: {'抬起过' if rose else '★ 从未抬起（没有任何轴在动）'}")

        ans = input(
            "  👉 请肉眼确认（可多选，直接输数字连着写，例如 12）：\n"
            "     [1] 靠近皮带的那个臂（锁螺丝位）动了\n"
            "     [2] 靠近转盘B 的那个臂（点胶位）动了\n"
            "     [3] 两个臂都没动\n"
            "     [4] 动的不是机械臂（是转盘/皮带/别的）\n"
            "     输入: ").strip()
        answers[label] = (rb, rose, ans)

        # 归零再测下一个
        zero_all(mc)

    print("\n" + "=" * 70)
    print("汇总（请把这段发回来）")
    print("=" * 70)
    print(f"  {'测试对象':<44}{'回读':<8}{'信号':<8}{'肉眼结果'}")
    for label, (rb, rose, ans) in answers.items():
        print(f"  {label[:42]:<44}{str(rb):<8}{'有' if rose else '★无':<8}{ans}")

    print("""
判读（看"肉眼结果"那一列）：
  * 只有 1 和 3 出现 → 锁螺丝臂只由 reg0/reg1 驱动，reg2/reg3 可能是空通道
  * 只有 2 和 4 出现 → ★ 映射反了：reg2/reg3 才是锁螺丝臂，reg0/reg1 是点胶臂
  * 三个以上都出现    → 多个寄存器接到了同一批轴，或 reg0/reg1 悬空
  * 全部是 3          → 寄存器都没接驱动，问题在 Factory IO 的驱动配置

★ 最要紧的是确认：**reg0 写 10000 时，到底有没有任何东西动？**
""")
    zero_all(mc)
    mc.close()


if __name__ == "__main__":
    main()
