# -*- coding: utf-8 -*-
"""点胶臂 Z 轴动作计数探针 —— 查"多余的 Z 动作"

做法：在后台高频采样 reg3（点胶臂 Z 设定点）和它的 Moving 信号（input10），
     把每一次"设定点变化"和每一次"信号抬起/落下"都打上时间戳记下来。

这样就能看出：
    · 我下发的命令序列（reg3 的变化）
    · 机械臂实际做了几次独立运动（信号的上升沿个数）
    · 有没有"一条命令导致多次运动"或"没命令却运动"的情况

用法：另开一个窗口跑 python main.py，再跑本脚本；
      跑完 2~3 件后 Ctrl+C 停止，把输出发回来。
"""

import time
import threading

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.05
STOP = False


def watcher(mc):
    last_sp = None
    last_sig = None
    n_cmd = 0
    n_move = 0
    t0 = time.time()
    while not STOP:
        try:
            sp = mc.read_register(ARM2_Z_REG)
            pos = mc.read_input_register(3)
            sig = bool(mc.read_input(ARM0_MOVING_Z_INPUT))
            el = time.time() - t0

            if sp != last_sp:
                n_cmd += 1
                print(f"[{el:7.2f}s] ★命令#{n_cmd}  reg3 -> {sp:<6}  (实际位置 {pos})")
                last_sp = sp

            if sig != last_sig:
                if sig:
                    n_move += 1
                    print(f"[{el:7.2f}s]   Z 运动开始 (第 {n_move} 次)  reg3={sp}  位置={pos}")
                else:
                    print(f"[{el:7.2f}s]   Z 运动结束           位置={pos}")
                last_sig = sig
        except Exception:
            pass
        time.sleep(POLL)


def main():
    global STOP
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return
    print("=" * 74)
    print("点胶臂 Z 轴动作计数   reg3 = 设定点   input10 = Moving 信号")
    print("=" * 74)
    print("  现在去另一个窗口跑 python main.py，跑 2~3 件后回到这里按 Ctrl+C")
    print("")
    th = threading.Thread(target=watcher, args=(mc,), daemon=True)
    th.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        STOP = True
        time.sleep(0.2)
    print("")
    print("判读：")
    print("  * 命令数 和 运动次数 一一对应        -> 正常")
    print("  * 一条命令触发了两次运动（两个上升沿）-> ★ 有重复动作，查 _arm_move 的等待逻辑")
    print("  * 没有命令却出现运动                  -> ★ 有别的写入源，或轴自己动")
    print("  * 命令后信号一直不落下                -> ★ 轴没走到位（等待时间不够或撞限位）")
    mc.close()


if __name__ == "__main__":
    main()
