# -*- coding: utf-8 -*-
"""监视 reg2（点胶臂 X 设定点）—— 抓"谁把它写成了 9999"

背景：
    main.py 里没有任何一处写 ARM2_X_REG（全是注释），
    但点胶臂 X 位置从 0 爬到了 9999。
    → 所以有某个写入路径没被发现。

这个探针每 0.1 秒同时读三样东西：
    Holding Register 2   ← 点胶臂 X 的【设定点】（谁在写它）
    Input Register 2     ← 点胶臂 X 的【实际位置】
    Input Register 0     ← 锁螺丝臂 X 的实际位置（对照）

★ 关键判据：
    如果 reg2 一直是 0，而位置爬到 9999
        → 不是寄存器写的问题，是别的东西（比如另一个臂的电压串到它身上）
    如果 reg2 被写成了别的值
        → 抓到写入时刻，对照 arm_trace.log 找是谁写的

用法：先启动 main.py（另开一个窗口），然后运行本探针。
      或者单独跑本探针 + 在 Factory IO 里手动观察。
      python test_watch_reg2.py
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.1
DURATION = 180          # 最多监视 3 分钟


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 74)
    print("监视 reg2（点胶臂 X 设定点）—— 抓谁把它写成 9999")
    print("=" * 74)
    print(f"  Holding Register {ARM2_X_REG}  = 点胶臂 X 设定点（谁在写）")
    print(f"  Input   Register 2             = 点胶臂 X 实际位置")
    print(f"  Input   Register 0             = 锁螺丝臂 X 实际位置")
    print(f"  每 {POLL}s 采一次，最多 {DURATION}s")
    print("")
    print("  提示：现在去【另一个窗口跑 python main.py】")
    print("       抓到变化后按 Ctrl+C 停止")
    print("")
    input("按回车开始监视...")

    print("")
    print(f"{'时间':<14}{'reg2设定点':>12}{'P0_X实际':>12}{'P2_X实际':>12}")
    print("-" * 52)

    t0 = time.time()
    last = None
    try:
        while time.time() - t0 < DURATION:
            sp = mc.read_register(ARM2_X_REG)              # 点胶臂 X 设定点
            p0 = mc.read_input_register(2)                 # 点胶臂 X 实际
            p2 = mc.read_input_register(0)                 # 锁螺丝臂 X 实际
            cur = (sp, p0, p2)
            el = time.time() - t0
            if cur != last:
                mark = ""
                if last is not None and sp != last[0]:
                    mark = "   ← ★ reg2 被写了！"
                print(f"{el:>7.2f}s      {str(sp):>8}{str(p0):>12}{str(p2):>12}{mark}")
                last = cur
            time.sleep(POLL)
    except KeyboardInterrupt:
        print("\n已停止")
    print("")
    print("判读：")
    print("  · reg2 一直是 0，P0_X 却爬到 9999  → 设定点没变，是别的来源（电压/联动）")
    print("  · reg2 被写成了非 0 的值            → 抓到写入值，去 arm_trace.log 找对应时刻")
    mc.close()


if __name__ == "__main__":
    main()
