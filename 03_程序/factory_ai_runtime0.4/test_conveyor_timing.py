# -*- coding: utf-8 -*-
"""走带时间标定 —— 量出"料从发料器走到锁螺丝工位"到底要多久

为什么需要：
    原来代码靠"等漫反射传感器"判断料到位，但现场确认那个传感器是假的，
    一直在等满 5 秒。现在改成固定走带时间 BELT2_TRANSIT_WAIT，
    但这个值不能猜 —— 猜小了料没到位，猜大了白等。

★ 两个关键改进（第一版写错了，这里修掉）：
    1) 转盘必须【真的转起来】：光开滚轮没用，还要写 TABLE_A_TURN_COIL。
       完整接料序列和 main.py 步骤1 一致：
           转盘A 转 90°（保持）→ 开发料器+皮带0+滚轮 → 等料进来
           → 停 → 转盘A 回 0° → 开滚轮+皮带2 → 料走出去
    2) 采样必须【真的快】：第一版每次循环读 7 个输入 = 7 次 Modbus 往返，
       实际周期上百毫秒，料经过传感器的瞬间会整个漏掉。
       现在改成【一次批量读 13 个输入】（read_discrete_inputs count=13），
       一次往返拿全部，采样周期回到十几毫秒。

用法：Factory IO 运行中（点过 Reset），然后
      python test_conveyor_timing.py
约 40 秒。
"""

import time

from config import *                      # noqa: F401,F403
from modbus_client import FactoryModbusClient

POLL = 0.01          # 目标采样周期

# 一次性批量读回来的输入（0..12），和名字对应
INPUT_NAMES = {
    0:  "视觉0 来料检测",
    1:  "视觉1 成品检测",
    2:  "转盘A 0°限位",
    3:  "转盘A 90°限位",
    4:  "转盘B 0°限位",
    5:  "转盘B 90°限位",
    6:  "漫反射(input6)",
    7:  "推杆前限位",
    8:  "推杆后限位",
    9:  "点胶臂 MovingX",
    10: "点胶臂 MovingZ",
    11: "锁螺丝臂 MovingX",
    12: "锁螺丝臂 MovingZ",
}


def batch_read(mc):
    """★ 一次 Modbus 往返读回全部 13 个离散输入（0..12）。

    返回 {地址: bool}；失败返回 None。
    这是本探针能"真快"的关键：13 次往返 → 1 次往返。

    ★ 走 modbus_client 的正式接口 mc.read_inputs()，
      不要去摸 mc._backend.client —— client 是闭包变量，不是后端属性，
      那样写会直接抛异常然后被吞掉（第一版就是这么坏掉的：采样 0 次）。
    """
    vals = mc.read_inputs(0, 13)
    if vals is None:
        return None
    return {i: vals[i] for i in range(len(vals))}


def watch(mc, seconds, label, last, changes):
    """在 seconds 秒内高频采样，记录所有变化"""
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        el = time.time() - t0
        cur = batch_read(mc)
        if cur is not None:
            n += 1
            for a, v in cur.items():
                if a in last and v != last[a]:
                    nm = INPUT_NAMES.get(a, f"input{a}")
                    changes.append((label, el, a, nm, v))
                    print(f"  [{label} {el:6.2f}s] input{a:<3} {nm:<18} -> {v}")
                last[a] = v
        time.sleep(POLL)
    real = (time.time() - t0) / max(n, 1)
    print(f"  （{label} 段结束：采样 {n} 次，实际周期 {real*1000:.0f}ms）")
    return n


def main():
    mc = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
    if not mc.connect():
        print("PLC 连接失败")
        return

    print("=" * 72)
    print("走带时间标定（第二版：转盘真的转 + 批量快速采样）")
    print("=" * 72)

    # ---- 先测一下批量读到底多快，并确认真的读到了 ----
    #  ★ 第一版这里有个坑：读全失败了（返回 None）也照样算时间、还打"✓ 采样够快"，
    #    结果后面全程"采样 0 次"。现在必须先验证"读成功"再谈快慢。
    ok_n = 0
    t0 = time.time()
    for _ in range(50):
        if batch_read(mc) is not None:
            ok_n += 1
    per = (time.time() - t0) / 50
    print(f"  批量读 13 个输入：每次 {per*1000:.1f} ms，成功 {ok_n}/50 次")
    if ok_n == 0:
        print("  ★★ 批量读【全部失败】—— 后面采样不到任何东西！")
        print("     可能原因：")
        print("       1. Factory IO 的 Modbus 驱动没开「读离散输入」")
        print("       2. 从站号对不上（config.MODBUS_SLAVE）")
        print("       3. 地址 0..12 超出场景里的 BitInput 数量")
        print("     先解决这个，否则这个探针没有意义。")
        return
    if per > 0.05:
        print("  ⚠ 单次读太慢（>50ms），料经过传感器的瞬间可能漏掉")
        print("     -> 建议把 Factory IO 的通讯周期调小，或接受「只看得到长事件」")
    else:
        print("  ✓ 采样够快，能抓住料经过传感器的瞬间")

    input("\n确认现场安全后按回车开始...")

    last = batch_read(mc) or {}
    print("")
    print("[基线] 初始输入状态：")
    for a in sorted(last):
        print(f"    input{a:<3} {INPUT_NAMES.get(a, ''):<18} = {last[a]}")

    changes = []

    # ================= 完整接料序列（和 main.py 步骤1 一致）=================
    print("")
    print("=" * 72)
    print("① 转盘A 转到 90°（接料位）并保持")
    print("=" * 72)
    mc.write_coil(TABLE_A_TURN_COIL, True)          # ★ 第一版漏了这一句！
    watch(mc, 4.0, "转90°", last, changes)

    print("")
    print("=" * 72)
    print(f"② 开发料器 + 皮带0 + 转盘A滚轮，等 {TABLE_A_LOAD_WAIT}s 让料进来")
    print("=" * 72)
    mc.write_coil(TABLE_A_ROLL_P_COIL, True)
    mc.write_coil(BELT_0_COIL, True)
    mc.write_coil(EMITTER_COIL, True)
    watch(mc, TABLE_A_LOAD_WAIT, "进料", last, changes)

    print("")
    print("③ 停滚轮/皮带0/发料器，停稳")
    mc.write_coil(TABLE_A_ROLL_P_COIL, False)
    mc.write_coil(BELT_0_COIL, False)
    mc.write_coil(EMITTER_COIL, False)
    watch(mc, TABLE_A_REST, "停稳", last, changes)

    print("")
    print("=" * 72)
    print("④ 转盘A 松手回 0°（写 False = 回 0°），等 0° 限位")
    print("=" * 72)
    mc.write_coil(TABLE_A_TURN_COIL, False)         # ★ 松手 = 回 0°
    watch(mc, 4.0, "回0°", last, changes)

    print("")
    print("=" * 72)
    print("⑤ 开滚轮 + 皮带2，料走出去 —— ★ 这一段就是走带时间")
    print("=" * 72)
    mc.write_coil(TABLE_A_ROLL_P_COIL, True)
    mc.write_coil(BELT_2_COIL, True)
    watch(mc, 12.0, "走带", last, changes)

    print("")
    print("⑥ 停滚轮/皮带2")
    mc.write_coil(TABLE_A_ROLL_P_COIL, False)
    mc.write_coil(BELT_2_COIL, False)
    watch(mc, 1.0, "收尾", last, changes)

    # ================= 汇总 =================
    print("")
    print("=" * 72)
    print("汇总")
    print("=" * 72)
    if changes:
        print(f"  共捕获 {len(changes)} 次输入变化：")
        for label, el, a, nm, v in changes:
            print(f"    [{label:<6} {el:6.2f}s] input{a:<3} {nm:<18} -> {v}")
    else:
        print("  ★ 所有输入【都没有变化】")
        print("    = 这台设备上没有任何能感知【料到了】的信号")
        print("    → 只能靠【固定时间 + 目视】来定 BELT2_TRANSIT_WAIT")

    print("")
    print("─" * 72)
    print("怎么看这个结果：")
    print("  1) 看 steps 段里有没有 input0（视觉0）出现 -> True")
    print("       有 -> 料经过来料视觉的时刻就是那个时间戳")
    print("  2) 看 走带 段里 input0 什么时候从 True 变回 False")
    print("       从「料到达视觉」到「料离开视觉」的时长，可以用来估算皮带线速度")
    print("  3) 如果全程没有任何输入变化：")
    print("       -> 目视「料在皮带2 上最终停在哪」")
    print("          还没到锁螺丝工位 -> BELT2_TRANSIT_WAIT 加大")
    print("          早就到了还在空转 -> BELT2_TRANSIT_WAIT 减小")
    mc.close()


if __name__ == "__main__":
    main()
