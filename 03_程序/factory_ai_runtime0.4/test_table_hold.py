# -*- coding: utf-8 -*-
"""转盘线圈行为探针 —— 只回答一个问题：

    "松开线圈（写 False）之后，转盘会不会自己转回 0°？"

为什么这一个问题决定成败：
    现场反馈"转盘转到 90° 后没等料进来就立马回 0°，导致卡料"。
    怀疑是 _table_index() 里最后那句 write_coil(turn_coil, False) 造成的
    —— 如果松开线圈 = 转盘自动回 0°，那"等料进入"的延时根本没意义，
    因为在我们开始等之前，转盘已经在往回走了。

    这个脚本把三种情况都试一遍，观察 15 秒内两个限位的变化：
      情况A：点一下线圈(True) → 到位 → 【松开(False)】   ← 现在程序的做法
      情况B：点一下线圈(True) → 到位 → 【保持 True 不放】
      情况C：点一下线圈(True) → 到位 → 松开(False) → 再点一次(True)

用法：Factory IO 运行中（点过 Reset），然后
      python test_table_hold.py
⚠ 转盘会真的转动，确认现场安全。整个过程约 2 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05


# ★ 先定义好这个字典，下面的函数才能用它做默认参数
#   （原来是函数在前、字典在后，默认参数求值时字典还不存在 → NameError）
TABLE_A = {'turn': TABLE_A_TURN_COIL, 'limit0': TABLE_A_LIMIT_0_INPUT, 'limit90': TABLE_A_LIMIT_90_INPUT}


def limits(mc, t=None):
    """读转盘A 的两个限位。返回 (限位0°, 限位90°)"""
    if t is None:
        t = TABLE_A
    return (bool(mc.read_input(t['limit0'])), bool(mc.read_input(t['limit90'])))


def watch(mc, seconds, label):
    """观察 seconds 秒内限位的变化，只打印变化时刻"""
    print(f"  --- {label}（观察 {seconds}s）---")
    t0 = time.time()
    last = None
    events = []
    while time.time() - t0 < seconds:
        cur = limits(mc)
        if cur != last:
            el = time.time() - t0
            print(f"    t={el:5.2f}s   0°={int(cur[0])}  90°={int(cur[1])}")
            events.append((round(el, 2), cur))
            last = cur
        time.sleep(POLL)
    if not events:
        print(f"    （{seconds}s 内没有任何变化）")
    return events


def pulse_to(mc, target90, timeout=12.0):
    """点一下线圈，等目标限位到位。返回 (到位?, 耗时)"""
    tgt_addr = TABLE_A['limit90'] if target90 else TABLE_A['limit0']
    tgt = "90°" if target90 else "0°"
    mc.write_coil(TABLE_A['turn'], True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if mc.read_input(tgt_addr):
            return True, time.time() - t0
        time.sleep(POLL)
    return False, time.time() - t0


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 66)
    print("转盘线圈行为探针 —— 松开线圈会不会自动回 0°？")
    print("=" * 66)
    print(f"  转盘A  线圈=coil {TABLE_A['turn']}   0°限位=input {TABLE_A['limit0']}   90°限位=input {TABLE_A['limit90']}")
    print("\n⚠ 转盘会真的转动，确认现场安全后按回车")
    input("按回车开始...")

    # 先回到一个已知状态
    print("\n[准备] 先让转盘回到 0°")
    ok, dt = pulse_to(mc, target90=False)
    mc.write_coil(TABLE_A['turn'], False)
    print(f"  回 0°：{'到位' if ok else '未到位'}（{dt:.2f}s）")
    watch(mc, 2, "松手后的静止状态")
    ls = limits(mc)
    print(f"  当前: 0°={int(ls[0])}  90°={int(ls[1])}")

    results = {}

    # ---------------- 情况 A：到位后松开（= 现在程序的做法）----------------
    print("\n" + "=" * 66)
    print("情况A：转到 90° → 到位 → 【松开线圈 False】")
    print("=" * 66)
    ok, dt = pulse_to(mc, target90=True)
    print(f"  到位：{'是' if ok else '否'}（{dt:.2f}s）")
    mc.write_coil(TABLE_A['turn'], False)
    print("  已写 False（松开）。下面观察 15 秒，看它会不会自己回去：")
    ev = watch(mc, 15, "松开线圈后")
    results['A'] = ('松开后自己回 0°' if any(e[1][0] for e in ev) else '松开后停在 90° 不动')

    # ---------------- 情况 B：到位后保持 True ----------------
    print("\n" + "=" * 66)
    print("情况B：转到 0° → 到位 → 再转到 90° → 【保持 True 不放】")
    print("=" * 66)
    pulse_to(mc, target90=False)
    mc.write_coil(TABLE_A['turn'], False)
    time.sleep(1)
    ok, dt = pulse_to(mc, target90=True)
    print(f"  到位：{'是' if ok else '否'}（{dt:.2f}s）")
    print("  线圈保持 True。观察 15 秒：")
    ev = watch(mc, 15, "保持线圈 True")
    results['B'] = ('保持 True 时自己回 0°' if any(e[1][0] for e in ev) else '保持 True 时停在 90°')

    # ---------------- 情况 C：松开后再点一次 ----------------
    print("\n" + "=" * 66)
    print("情况C：转到 90° → 到位 → 松开 → 隔 3 秒后再点一次 True")
    print("=" * 66)
    mc.write_coil(TABLE_A['turn'], False)
    time.sleep(1)
    pulse_to(mc, target90=False)
    mc.write_coil(TABLE_A['turn'], False)
    time.sleep(1)
    pulse_to(mc, target90=True)
    mc.write_coil(TABLE_A['turn'], False)
    print("  已到 90° 并松开。等 3 秒，然后再点一次 True：")
    time.sleep(3)
    ls = limits(mc)
    print(f"    3 秒后: 0°={int(ls[0])}  90°={int(ls[1])}")
    mc.write_coil(TABLE_A['turn'], True)
    print("  已写 True。观察 8 秒：")
    ev = watch(mc, 8, "再点一次 True")
    mc.write_coil(TABLE_A['turn'], False)

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 66)
    print("汇总（请把这段发回来）")
    print("=" * 66)
    print(f"  情况A（到位后松开）      → {results['A']}")
    print(f"  情况B（到位后保持True）  → {results['B']}")
    print("""
判读：
  * A = "松开后自己回 0°"  ⇒ 现在程序的做法有根本问题：
      松开线圈就等于命令转盘回去，所以"等料进入"的延时是白给的
      （在我们开始等之前，转盘已经往回走了）。
      修法：到位后不要松开，保持 True 直到料进完，再松开让它回去；
           或者干脆不靠线圈状态控制，改成"点一下 → 到位 → 料进完 → 再点一下回 0°"。

  * A = "松开后停在 90° 不动" ⇒ 松开不是问题，卡料另有原因
      （那就回到"料到底有没有进到转盘中心"这个方向上查）。

  * B = "保持 True 时自己回 0°" ⇒ 线圈不能保持，只能脉冲，
      那必须用"两次脉冲"的写法：一次去 90°，一次回 0°。
""")
    mc.close()


if __name__ == "__main__":
    main()
