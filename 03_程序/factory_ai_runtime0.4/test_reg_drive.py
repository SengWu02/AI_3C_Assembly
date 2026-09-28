# -*- coding: utf-8 -*-
"""寄存器 → 机械臂 驱动验证（专门查"TRACE 说写了 500，机械臂没动"）

背景：现场反馈
    [TRACE] 回原点[初始化机械臂2] 第1步-前伸: X reg0 -> 500, Z reg1 -> 500
    这个"X reg0 -> 500"是假的 —— 机械臂没有做出对应的动作。

所以要区分三件事：
    (a) 寄存器写没写进去？      → 回读寄存器值
    (b) 机械臂动没动？          → 看 Moving 信号 + 你用眼睛看
    (c) 两个臂的寄存器是不是反的？→ 分别驱动两个臂，看哪个动

用法：Factory IO 运行中（点过 Reset），然后
      python test_reg_drive.py
⚠ 机械臂会真的动，确认现场安全。约 2 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05


def rd(mc, reg):
    """回读寄存器，返回 (值 或 None, 说明)"""
    v = mc.read_register(reg)
    return v if v is not None else None


def moving(mc, addr):
    try:
        return bool(mc.read_input(addr))
    except Exception:
        return None


def drive_and_watch(mc, reg, value, moving_addr, label, seconds=4.0):
    """写一个寄存器，然后观察：回读值 + 对应 Moving 信号 + 对方 Moving 信号"""
    print(f"\n--- {label} ---")
    before = rd(mc, reg)
    print(f"  写之前回读 reg{reg} = {before}")

    mc.write_register(reg, value)
    t0 = time.time()
    time.sleep(0.15)                      # 等一下让 PLC 处理
    after = rd(mc, reg)
    print(f"  写 {value} 之后回读 reg{reg} = {after}"
          + ("   ✅ 写进去了" if after == value else "   ★★ 回读不符！写没进去"))

    # 观察 Moving 信号跳变
    last = None
    rose = False
    rose_t = None
    moved_any = False
    while time.time() - t0 < seconds:
        cur = (moving(mc, moving_addr), moving(mc, ARM2_MOVING_X_INPUT),
               moving(mc, ARM2_MOVING_Z_INPUT), moving(mc, ARM0_MOVING_X_INPUT),
               moving(mc, ARM0_MOVING_Z_INPUT))
        if cur != last:
            el = time.time() - t0
            print(f"    t={el:5.2f}s   2_X={int(bool(cur[1]))} 2_Z={int(bool(cur[2]))} "
                  f"0_X={int(bool(cur[3]))} 0_Z={int(bool(cur[4]))}")
            last = cur
            if any(cur):
                moved_any = True
            if cur[0] and not rose:
                rose = True
                rose_t = el
        time.sleep(POLL)
    print(f"  → 目标信号 {'抬起过' if rose else '★ 从未抬起（= 这个轴没动）'}")
    print(f"  → 有任何信号动过吗: {'是' if moved_any else '★ 否（四个轴全没动）'}")
    return after == value, rose


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 68)
    print("寄存器 → 机械臂 驱动验证")
    print("=" * 68)
    print(f"  锁螺丝臂(现场 Pick&Place 2): X reg{ARM1_X_REG}  Z reg{ARM1_Z_REG}")
    print(f"  点胶臂  (现场 Pick&Place 0): X reg{ARM2_X_REG}  Z reg{ARM2_Z_REG}")
    print("\n⚠ 机械臂会真的动，确认现场安全后按回车")
    input("按回车开始...")

    # 先确认回读功能本身可用
    print("\n[自检] 读一次寄存器，确认回读功能可用")
    v0 = rd(mc, ARM1_X_REG)
    v2 = rd(mc, ARM2_X_REG)
    print(f"  reg{ARM1_X_REG} = {v0}   reg{ARM2_X_REG} = {v2}")
    if v0 is None and v2 is None:
        print("  ★★ 回读全部失败 —— 你的 Factory IO 可能没开放 Holding Register 读，")
        print("     或者从站号/地址对不上。那后面只能靠眼睛看。")

    results = []

    # ---------- 锁螺丝臂 X ----------
    ok, rose = drive_and_watch(mc, ARM1_X_REG, 3000, ARM2_MOVING_X_INPUT,
                               "① 锁螺丝臂 X 写 3000（看它动不动、往哪动）")
    results.append(("锁螺丝臂 X=3000", ok, rose))
    print("\n  👉 请肉眼记住：锁螺丝臂现在伸出了多少？")
    input("     看完按回车继续...")

    # ---------- 点胶臂 X ----------
    ok, rose = drive_and_watch(mc, ARM2_X_REG, 3000, ARM0_MOVING_X_INPUT,
                               "② 点胶臂 X 写 3000（同一个值，看是哪个臂动）")
    results.append(("点胶臂 X=3000", ok, rose))
    print("\n  👉 请肉眼确认：这次动的是点胶臂吗？位置和刚才锁螺丝臂像不像？")
    input("     看完按回车继续...")

    # ---------- 点胶臂 X 写 500（复现你说的"假的 500"）----------
    print("\n" + "=" * 68)
    print("③ 复现现场那一行：点胶臂 X 写 500")
    print("=" * 68)
    print("  先把两个臂都归零")
    mc.write_register(ARM1_X_REG, 0)
    mc.write_register(ARM2_X_REG, 0)
    time.sleep(2.0)
    print(f"  归零后回读 reg{ARM1_X_REG}={rd(mc, ARM1_X_REG)}  reg{ARM2_X_REG}={rd(mc, ARM2_X_REG)}")

    ok, rose = drive_and_watch(mc, ARM2_X_REG, 500, ARM0_MOVING_X_INPUT,
                               "点胶臂 X 写 500", seconds=3.0)
    results.append(("点胶臂 X=500", ok, rose))
    print("\n  👉 关键问题：点胶臂有没有动？哪怕很轻微？")
    ans = input("     [1] 动了（轻微伸出）  [2] 完全没动  [3] 动了但是往回缩\n"
                "     输入 1/2/3: ").strip()

    # ---------- 收尾归零 ----------
    print("\n[收尾] 两个臂归零")
    mc.write_register(ARM1_X_REG, 0)
    mc.write_register(ARM1_Z_REG, 0)
    mc.write_register(ARM2_X_REG, 0)
    mc.write_register(ARM2_Z_REG, 0)
    time.sleep(2.0)

    # ---------- 汇总 ----------
    print("\n" + "=" * 68)
    print("汇总（请把这段发回来）")
    print("=" * 68)
    for name, wrote, rose in results:
        print(f"  {name:<20} 寄存器写入成功={'是' if wrote else '★否'}"
              f"   Moving信号抬起={'是' if rose else '★否'}")
    print(f"  点胶臂 X=500 的肉眼结果: {ans}  "
          f"({'动了（轻微）' if ans=='1' else '完全没动' if ans=='2' else '往回缩' if ans=='3' else '?'})")

    print("""
判读：
  * 写入成功=否            → 寄存器根本没写进去（通信/地址问题），跟机械臂无关
  * 写入成功=是 但没动       → 这个寄存器没驱动这个轴（映射错），或该轴机械卡死
  * 全部正常但 500 不动      → 500 太小，机构有启动死区，需要加大前伸量
  * 锁螺丝臂动、点胶臂不动   → 点胶臂的寄存器映射错，或该臂没接驱动
""")
    mc.close()


if __name__ == "__main__":
    main()
