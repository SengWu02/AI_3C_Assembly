# -*- coding: utf-8 -*-
"""机械臂行程标定 —— 测出"写多少 -> 实际走到哪"的完整曲线

为什么必须做这个：
    现在代码里用的 500 / 5000 / 8400 / 8500 / 10000 全是拍脑袋的百分比，
    从来没人验证过它们对应机械臂的哪个物理位置。
    结果就是：不知道 10000 是不是顶到极限，也不知道 500 到底动没动。

这个脚本做一次阶梯标定：
    从小到大逐点写设定点，每个点停稳后读回实际位置，
    最后打印 设定点 -> 实际位置 的对照表。

用法：Factory IO 运行中，然后
      python test_arm_calibrate.py
机械臂会走满行程，确认现场安全。约 3 分钟。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

SETTLE = 2.5
LADDER = [0, 200, 500, 1000, 2000, 3000, 4000, 5000,
          6000, 7000, 8000, 9000, 9500, 10000]

AXES = [
    ("锁螺丝臂X", ARM1_X_REG, 0, ARM2_MOVING_X_INPUT),
    ("锁螺丝臂Z", ARM1_Z_REG, 1, ARM2_MOVING_Z_INPUT),
    ("点胶臂X",   ARM2_X_REG, 2, ARM0_MOVING_X_INPUT),
    ("点胶臂Z",   ARM2_Z_REG, 3, ARM0_MOVING_Z_INPUT),
]


def calibrate(mc, name, sp_reg, pos_reg, mv_addr):
    print("")
    print("=" * 72)
    print(f"标定 {name}   设定点 reg{sp_reg}   位置 input{pos_reg}   信号 input{mv_addr}")
    print("=" * 72)
    print(f"{'设定点':>8}{'实际位置':>10}{'回读':>8}{'信号':>6}{'耗时':>9}{'偏差':>8}")
    print("-" * 72)

    rows = []
    for sp in LADDER:
        t0 = time.time()
        mc.write_register(sp_reg, sp)
        rose = False
        tw = time.time()
        while time.time() - tw < 2.0:
            try:
                if mc.read_input(mv_addr):
                    rose = True
                    break
            except Exception:
                pass
            time.sleep(0.02)
        moved = None
        if rose:
            td = time.time()
            while time.time() - td < 8.0:
                try:
                    if not mc.read_input(mv_addr):
                        moved = time.time()
                        break
                except Exception:
                    pass
                time.sleep(0.02)
        if moved:
            extra = SETTLE - (time.time() - moved)
            if extra > 0:
                time.sleep(extra)
        else:
            time.sleep(SETTLE)

        elapsed = time.time() - t0
        pos = mc.read_input_register(pos_reg)
        rb = mc.read_register(sp_reg)
        dev = (pos - sp) if (pos is not None) else None
        rows.append((sp, pos, rb, rose, elapsed, dev))
        flag = "是" if rose else "否"
        print(f"{sp:>8}{str(pos):>10}{str(rb):>8}{flag:>6}{elapsed:>8.2f}s"
              f"{(str(dev) if dev is not None else '?'):>8}")

    valid = [(sp, p) for sp, p, _, _, _, _ in rows if p is not None]
    if valid:
        ps = [p for _, p in valid]
        print(f"  位置范围: 最小 {min(ps)}   最大 {max(ps)}")
        dead = []
        for i in range(1, len(valid)):
            if valid[i][1] == valid[i-1][1]:
                dead.append((valid[i-1][0], valid[i][0], valid[i][1]))
        if dead:
            print("  死区（设定点变了位置不动）:")
            for a, b, p in dead:
                print(f"      {a} -> {b}   位置一直是 {p}")
        sat = [sp for sp, p in valid if p >= 9900]
        if sat:
            print(f"  饱和（卡在 9900+）: 设定点 {sat}")

    mc.write_register(sp_reg, 0)
    time.sleep(2.0)
    return rows


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 72)
    print("机械臂行程标定（阶梯法）")
    print("=" * 72)
    print(f"  每个轴 {len(LADDER)} 个点，每点停稳 {SETTLE}s")
    print(f"  阶梯: {LADDER}")
    print("  机械臂会走满行程，确认现场安全")
    input("按回车开始...")

    allrows = {}
    for name, sp_reg, pos_reg, mv_addr in AXES:
        allrows[name] = calibrate(mc, name, sp_reg, pos_reg, mv_addr)

    print("")
    print("=" * 72)
    print("汇总：设定点 -> 实际位置（请把这段发回来）")
    print("=" * 72)
    header = f"{'设定点':>8}" + "".join(f"{n:>12}" for n in allrows)
    print(header)
    print("-" * len(header))
    for i, sp in enumerate(LADDER):
        line = f"{sp:>8}"
        for name in allrows:
            line += f"{str(allrows[name][i][1]):>12}"
        print(line)

    print("")
    print("判读：")
    print("  * 位置范围不是 0~10000 -> 10000 超出机械行程，之前写的值都要重算")
    print("  * 低设定点位置不动     -> 有死区，ARM_HOME_PRESTRETCH=500 可能没让它动")
    print("  * 位置卡在某个上限     -> 那个设定点以上就是撞限位")
    print("  * 每个点的耗时         -> 用来替换 ARM_TRAVEL_TIME 的猜测值")
    mc.close()


if __name__ == "__main__":
    main()
