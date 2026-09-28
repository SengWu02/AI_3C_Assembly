# -*- coding: utf-8 -*-
"""转盘A 转动探针 —— 只测一个动作：90° ↔ 0° 来回转，看限位到底能不能到位。

为什么单独测这个：
  现场日志里反复出现
      [table] 限位未到位: A→0°送料 (input 2 != True)
  也就是"转盘A 回 0° 时，0° 限位一直读不到 True"。
  这可能是
      (a) 转盘物理上没转回 0°（机构卡、驱动不够）
      (b) 转盘转回去了，但 0° 限位开关本身没触发/接线松
      (c) 时序问题：限位只是瞬间触发，我们问得太晚
  这个脚本把每一次转动的完整过程打出来（限位 + 滚轮状态 + 时间），
  连转 5 个来回，用数据判断是哪一种。

用法：Factory IO 处于运行状态（点过 Reset），然后
      python test_table_a.py
注意：转盘会真的转动，确认现场安全。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05


def limits(mc):
    return (bool(mc.read_input(TABLE_A_LIMIT_0_INPUT)),
            bool(mc.read_input(TABLE_A_LIMIT_90_INPUT)))


def turn(mc, label, expect_90, timeout=10.0):
    """点一次转盘A，观察两个限位的完整跳变过程。"""
    ls0, ls90 = limits(mc)
    print(f"\n--- {label} ---")
    print(f"  转动前:  0°={int(ls0)}  90°={int(ls90)}")

    mc.write_coil(TABLE_A_TURN_COIL, True)
    t0 = time.time()
    last = (ls0, ls90)
    seen_0 = seen_90 = False
    hit_target = False
    target_addr = TABLE_A_LIMIT_90_INPUT if expect_90 else TABLE_A_LIMIT_0_INPUT
    target_desc = "90°" if expect_90 else "0°"

    while time.time() - t0 < timeout:
        cur = limits(mc)
        if cur != last:
            el = time.time() - t0
            print(f"  t={el:5.2f}s  0°={int(cur[0])}  90°={int(cur[1])}")
            last = cur
        if cur[0]:
            seen_0 = True
        if cur[1]:
            seen_90 = True
        if mc.read_input(target_addr):
            hit_target = True
            break
        time.sleep(POLL)

    el = time.time() - t0
    mc.write_coil(TABLE_A_TURN_COIL, False)

    print(f"  结果: 目标 {target_desc} 限位 {'✅ 到位' if hit_target else '❌ 未到位'}  (耗时 {el:.2f}s)")
    print(f"        过程里见过 0°={seen_0}  90°={seen_90}")
    print(f"        松开线圈后: 0°={int(limits(mc)[0])}  90°={int(limits(mc)[1])}")
    return hit_target, seen_0, seen_90, el


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 62)
    print("转盘A 限位探针")
    print("=" * 62)
    print(f"  0° 限位  = input {TABLE_A_LIMIT_0_INPUT}")
    print(f"  90° 限位 = input {TABLE_A_LIMIT_90_INPUT}")
    print(f"  转动线圈 = coil  {TABLE_A_TURN_COIL}")
    print("\n⚠ 转盘会真的转动，确认现场安全后按回车")
    input("按回车开始...")

    print("\n" + "=" * 62)
    print("第 0 步：先看静止状态（不写任何东西）")
    print("=" * 62)
    ls0, ls90 = limits(mc)
    print(f"  当前: 0°={int(ls0)}  90°={int(ls90)}")
    if ls0 and ls90:
        print("  ⚠ 两个限位同时为 True —— 限位开关可能接错或短路")
    elif not ls0 and not ls90:
        print("  ⚠ 两个限位都是 False —— 转盘可能停在中间，或限位都没接")
    elif ls0:
        print("  → 转盘当前在 0°")
    else:
        print("  → 转盘当前在 90°")

    results = []
    for i in range(1, 6):
        print("\n" + "=" * 62)
        print(f"第 {i} 个来回")
        print("=" * 62)
        r1 = turn(mc, f"[{i}] A → 90°", expect_90=True)
        results.append(("→90°",) + r1)
        r2 = turn(mc, f"[{i}] A → 0° ", expect_90=False)
        results.append(("→0° ",) + r2)

    print("\n" + "=" * 62)
    print("汇总")
    print("=" * 62)
    print(f"  {'动作':<8}{'到位':<8}{'耗时':<8}{'过程见过0°':<12}{'过程见过90°'}")
    for tag, hit, s0, s90, el in results:
        print(f"  {tag:<8}{'✅' if hit else '❌':<8}{el:<8.2f}{str(s0):<12}{s90}")

    fail0 = [r for r in results if r[0] == "→0° " and not r[1]]
    fail90 = [r for r in results if r[0] == "→90°" and not r[1]]
    print("\n判读：")
    if not fail0 and not fail90:
        print("  两个方向都正常 → 转盘和限位都没问题，")
        print("  那生产流程里的'未到位'就是节拍/时序造成的（比如上一步没转完就发了下一条命令）。")
    elif fail90:
        print(f"  ⚠ A→90° 失败 {len(fail90)} 次 → 限位或驱动有问题，先查 input {TABLE_A_LIMIT_90_INPUT}")
    elif fail0:
        print(f"  ⚠ A→0° 失败 {len(fail0)} 次，但 A→90° 正常。")
        print("  重点看汇总里'过程见过0°'那一列：")
        print("    * 见过 = True 但最终没判到位 → 限位是瞬间触发，代码问得太晚（时序问题）")
        print("    * 见过 = False            → 转盘根本没转回 0°，或者 0° 限位开关坏了/没接")
    print("\n把这整段输出发回来。")
    mc.close()


if __name__ == "__main__":
    main()
