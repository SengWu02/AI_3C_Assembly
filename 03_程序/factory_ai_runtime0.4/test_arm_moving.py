# -*- coding: utf-8 -*-
"""机械臂 Moving 信号探针 —— 只读观测，不改任何程序逻辑。

目的：搞清楚 Factory IO 里机械臂的 Moving X/Z 信号到底是什么行为，
      为什么"第1件有效、第2件起就没反应"。

它会做三件事：
  1. 空转观测 3 秒：不写任何寄存器，只看 4 个 Moving 输入平时是什么值
  2. 单轴动作观测：只动一个轴，50ms 采样，打印信号的完整跳变过程
  3. 双轴同时动作观测：X/Z 一起写，看两个信号怎么互动

用法：先让 Factory IO 处于运行状态（点过 Reset），然后
      python test_arm_moving.py
把整段输出发回来即可。

注意：这个脚本会真的让机械臂动起来，确认现场安全再跑。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

SAMPLE_MS = 50
SAMPLES = 120          # 6 秒

MOVING = [
    ("ARM2_MOVING_X", ARM2_MOVING_X_INPUT),   # 锁螺丝位 X
    ("ARM2_MOVING_Z", ARM2_MOVING_Z_INPUT),   # 锁螺丝位 Z
    ("ARM0_MOVING_X", ARM0_MOVING_X_INPUT),   # 点胶位 X
    ("ARM0_MOVING_Z", ARM0_MOVING_Z_INPUT),   # 点胶位 Z
]


def read_all(mc):
    out = []
    for name, addr in MOVING:
        try:
            out.append((name, addr, bool(mc.read_input(addr))))
        except Exception as e:
            out.append((name, addr, f"ERR {e}"))
    return out


def snapshot(mc):
    vals = read_all(mc)
    return " ".join(f"{n.replace('ARM','').replace('_MOVING','')}={'1' if v is True else ('0' if v is False else v)}"
                    for n, a, v in vals)


def observe(mc, seconds, label):
    """按固定周期采样，只打印"值发生变化"的时刻。"""
    print(f"\n--- {label} ---")
    t0 = time.time()
    last = None
    changes = 0
    while time.time() - t0 < seconds:
        cur = tuple(v for _, _, v in read_all(mc))
        if cur != last:
            el = time.time() - t0
            print(f"  t={el:6.2f}s  {snapshot(mc)}")
            last = cur
            changes += 1
        time.sleep(SAMPLE_MS / 1000.0)
    if changes == 0:
        print(f"  （{seconds} 秒内信号没有任何变化，恒定值：{snapshot(mc)}）")
    return changes


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败，检查 Factory IO 是否在运行、IP 是否正确")
        return

    print("=" * 62)
    print("机械臂 Moving 信号探针")
    print("=" * 62)
    print(f"采样周期 {SAMPLE_MS}ms   Modbus {MODBUS_HOST}:{MODBUS_PORT}")
    print("只打印信号发生变化的时刻，没变化就说明信号是死的")
    print("\n⚠ 下面机械臂会真的动起来，确认现场安全后按回车")
    input("按回车开始...")

    # ---------- 阶段0：静止观测 ----------
    print("\n" + "=" * 62)
    print("阶段0 静止观测（不写任何寄存器，看信号平时是什么值）")
    print("=" * 62)
    print(f"  当前值: {snapshot(mc)}")
    observe(mc, 3, "静止 3 秒")

    # ---------- 阶段1：锁螺丝臂单轴 ----------
    print("\n" + "=" * 62)
    print("阶段1 锁螺丝臂 单轴动作（ARM1_*_REG / 看 ARM2_MOVING_*_INPUT）")
    print("=" * 62)

    print("\n[1a] 先硬复位归零：X=500 Z=500 保持0.5s，再 X=0 Z=0")
    mc.write_register(ARM1_X_REG, 500)
    mc.write_register(ARM1_Z_REG, 500)
    time.sleep(0.5)
    mc.write_register(ARM1_X_REG, 0)
    mc.write_register(ARM1_Z_REG, 0)
    observe(mc, 4, "归零过程中信号变化")

    print("\n[1b] 只动 X：写 10000，看 6 秒")
    mc.write_register(ARM1_X_REG, 10000)
    observe(mc, 6, "X 单轴伸出")

    print("\n[1c] 只动 Z：写 8500，看 6 秒")
    mc.write_register(ARM1_Z_REG, 8500)
    observe(mc, 6, "Z 单轴下降")

    print("\n[1d] 只动 Z 回零：写 0，看 6 秒")
    mc.write_register(ARM1_Z_REG, 0)
    observe(mc, 6, "Z 单轴回零")

    print("\n[1e] 只动 X 回零：写 0，看 6 秒")
    mc.write_register(ARM1_X_REG, 0)
    observe(mc, 6, "X 单轴回零")

    # ---------- 阶段2：双轴同时 ----------
    print("\n" + "=" * 62)
    print("阶段2 双轴同时动作（关键：看两个信号会不会互相干扰）")
    print("=" * 62)
    print("\n[2a] X 和 Z 同时写 500")
    mc.write_register(ARM1_X_REG, 500)
    mc.write_register(ARM1_Z_REG, 500)
    observe(mc, 5, "X+Z 同时反向")

    print("\n[2b] X 和 Z 同时写 0")
    mc.write_register(ARM1_X_REG, 0)
    mc.write_register(ARM1_Z_REG, 0)
    observe(mc, 5, "X+Z 同时归零")

    time.sleep(0.5)

    # ---------- 阶段3：物理位置映射确认 ----------
    print("\n" + "=" * 62)
    print("阶段3 物理映射确认（这个必须用眼睛看，回答几个问题）")
    print("=" * 62)
    print("""
背景：现场反馈"每回合开头机械臂都把极限位当原点"。要判断是
      (a) 寄存器写 0 到底把轴带去哪个物理位置 —— 也就是 0 和 10000 的方向
      (b) 还是等待时间不够、轴没走完就被发下一条命令
      下面这一段每一步都会停下来等你确认物理位置。
""")
    answers = {}
    for label, reg, value, moving in [
        ("X 轴", ARM1_X_REG, 0,     ARM2_MOVING_X_INPUT),
        ("X 轴", ARM1_X_REG, 10000, ARM2_MOVING_X_INPUT),
        ("Z 轴", ARM1_Z_REG, 0,     ARM2_MOVING_Z_INPUT),
        ("Z 轴", ARM1_Z_REG, 10000, ARM2_MOVING_Z_INPUT),
    ]:
        print("\n" + "-" * 62)
        print(f"现在把 {label} 的寄存器写成 {value}")
        print("-" * 62)
        mc.write_register(reg, value)
        observe(mc, 4, f"{label} = {value} 的信号过程")
        pos = input(f"  请肉眼确认：{label} 现在停在哪？\n"
                    f"    [1] 最上/最里（原点侧）  [2] 最下/最外（极限侧）  [3] 中间某处\n"
                    f"    输入 1/2/3: ").strip()
        answers[(label, value)] = pos

    print("\n" + "=" * 62)
    print("阶段3 结果汇总（请把这段一起发回来）")
    print("=" * 62)
    for (label, value), pos in answers.items():
        desc = {"1": "原点侧(上/里)", "2": "极限侧(下/外)", "3": "中间"}.get(pos, f"未答({pos})")
        print(f"  {label} 写 {value:>5}  →  物理停在 {desc}")

    print("\n" + "=" * 62)
    print("探测结束。把上面完整输出发回来。")
    print("=" * 62)
    print("""
重点看三件事：
  1) 阶段0 静止时信号是 0 还是 1（如果是 1，说明我的判据从一开始就反了）
  2) 阶段1 单轴动作时，对应信号在几秒后跳变、跳了几次
     （如果从头到尾没变，说明这个轴根本没接出来）
  3) 阶段2 双轴时，两个信号是各跳各的还是有先后依赖
""")
    mc.close()


if __name__ == "__main__":
    main()
