# ============================================================================
#  3C组装岛 —— 产线主程序（逐行注释版）
# ----------------------------------------------------------------------------
#  阅读顺序建议：
#    1) config.py        所有地址、时间常数都在这里，先看它
#    2) modbus_client.py 怎么写/怎么读（跟 Factory IO 打交道的一层）
#    3) 本文件 _arm_move / _arm_home / _table_index  三个基础动作
#    4) 本文件 produce_one()  一件产品的完整流程 —— 调产线主要改这里
#    5) 本文件 production_loop()  主循环，管产量、统计、界面刷新
#
#  修改原则（现场踩出来的）：
#    * 一次只改一个变量，改完立刻跑，别一次改几处
#    * 时间常数只改 config.py，不要在本文件里写死数字
#    * 调产线时把 config.LLM_ENABLED 设为 False，否则 LLM 会一直改节拍
# ============================================================================

import time          # 计时、sleep
import threading     # 生产线程 / LLM 线程
import json          # 解析 LLM 返回的 JSON、写爬坡日志
import signal        # 捕获 Ctrl+C，让产线安全停止
import random        # ⚠ 已无实际用途（历史遗留），可以删，但删了要确认没人引用

from config import *   # ★ 所有地址和时间常数都从 config.py 来（第 7 行）
                       #   所以本文件里出现的 TABLE_A_TURN_COIL 之类，
                       #   都可以在 config.py 里找到定义和注释

from modbus_client import FactoryModbusClient

from statistics import FactoryStatistics

from event_manager import EventManager

from jam_detector import JamDetector

from efficiency_detector import EfficiencyDetector

from safety_manager import SafetyManager

from ai_governance import AIGovernance

from llm_manager import LLMManager

from dashboard import DashboardApp




# ========== 全局状态 ==========
running = True               # 总开关。Ctrl+C 时被 signal_handler 置 False，主循环退出
task_done = False            # 产量达标标志，避免重复触发收尾逻辑
llm_running = False          # LLM 是否正在分析（防止同时起多个 LLM 线程）
last_llm_analysis = time.time()   # 上次 LLM 分析的时刻，用来控制分析间隔
table_position = 0           # 当前工位 0-3（历史遗留，现在基本没用到）
production_count = 0         # 已生产件数（产量）
cycle_count = 0              # 主循环轮数（比 production_count 大，含空转轮）
start_time = None            # 生产开始时刻，用来算效率（件/分钟）

# ========== 机械臂"实际位置"读取 ==========
# 从 Input Register 读四个轴的真实位置 —— 这是唯一能知道"臂现在到底在哪"的通道。
# ★ 当前读不到（实测恒为 0），需要先在 Factory IO 里把四个 Position (V) 点
#   分配到 Input Register，详见 config.ARM_POS_REG 上方注释。
# 读不到时返回一句说明，不影响生产。
_POS_DEAD = False          # 一旦判定读不到，本次运行就不再重复尝试


def _arm_pos(modbus_client, keys):
    """读若干轴的实际位置，返回可打印的字符串。keys 例如 ("P2_X", "P2_Z")。"""
    global _POS_DEAD
    if not ARM_POS_ENABLED or _POS_DEAD:
        return "未启用/不可用"
    parts = []
    got_any = False
    for k in keys:
        reg = ARM_POS_REG.get(k)
        if reg is None:
            parts.append(f"{k}=?")
            continue
        v = modbus_client.read_input_register(reg)
        if v is None:
            parts.append(f"{k}=读不到")
        else:
            parts.append(f"{k}={v}")
            got_any = True
    if not got_any:
        _POS_DEAD = True      # 一个都读不到 → 本次运行不再尝试
        return "读不到(Input Register 没挂位置反馈)"
    return " ".join(parts)


# ========== 机械臂运动流水账 ==========
# 每一次"写机械臂寄存器"都会记一行，方便事后追溯"最后是谁把臂写到了哪个值"。
# 控制台打 [TRACE]，同时追加到 config.ARM_TRACE_LOG 指定的文件。
def _arm_trace(msg):
    """记一条机械臂运动流水账（控制台 + 文件）。"""
    if not ARM_TRACE:
        return
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(f"      [TRACE] {msg}")
    try:
        with open(ARM_TRACE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass          # 写文件失败不影响生产


def _arm_pos_sampler(modbus_client):
    """后台线程：每 ARM_POS_POLL 秒记一次【点胶臂】的实际位置。

    为什么单独盯点胶臂：现场反馈"点胶臂从第二件开始 X 伸到极限"，
    按点记录（只在动作前后记）会漏掉动作之间的空档，所以改成连续记录。

    输出：控制台打印 + 追加写入 config.ARM_POS_TRACE_LOG。
    只在位置【发生变化】时打印，没变化就只写文件，避免刷屏。
    """
    f = None
    try:
        f = open(ARM_POS_TRACE_LOG, "a", encoding="utf-8")
        f.write(f"\n===== 位置采样开始 {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"(每 {ARM_POS_POLL}s 一次) =====\n")
        f.write("时间          reg0  reg2 | P2_X  P0_X   (reg0/reg2=设定点  P2_X/P0_X=实际位置)\n")
        f.flush()
    except Exception as e:
        print(f"[pos] ★无法打开位置日志 {ARM_POS_TRACE_LOG}: {e}")
        return

    last = None
    err_count = 0
    while running:
        try:
            # ★ 同时读【设定点】和【实际位置】——两者对照就能看出是谁在动
            sp0 = modbus_client.read_register(ARM1_X_REG)      # 锁螺丝臂 X 设定点
            sp2 = modbus_client.read_register(ARM2_X_REG)      # 点胶臂   X 设定点
            p2x = modbus_client.read_input_register(0)         # 锁螺丝臂 X 实际位置
            p0x = modbus_client.read_input_register(2)         # 点胶臂   X 实际位置
            s = lambda v: "  --  " if v is None else f"{v:6d}"
            line = (f"{time.strftime('%H:%M:%S')}.{int(time.time()*1000)%1000:03d}  "
                    f"{s(sp0)} {s(sp2)} | {s(p2x)} {s(p0x)}")
            f.write(line + "\n")
            f.flush()
            # 只在"设定点或位置"变化时打到控制台
            cur = (sp0, sp2, p2x, p0x)
            if cur != last:
                print(f"      [监视] reg0={s(sp0).strip()} reg2={s(sp2).strip()} | "
                      f"锁螺丝臂X={s(p2x).strip()}  点胶臂X={s(p0x).strip()}")
                last = cur
            err_count = 0
        except Exception as e:
            # ★ 原来是 except: pass —— 把错误全吞了，导致日志里只有表头、一行数据都没有，
            #   让人误以为"采样正常但机械臂没动"。现在把错误暴露出来，只报前 5 次。
            err_count += 1
            if err_count <= 5:
                msg = f"[pos] ★采样出错({err_count}): {type(e).__name__}: {e}"
                print(f"      {msg}")
                try:
                    f.write(msg + "\n")
                    f.flush()
                except Exception:
                    pass
        time.sleep(ARM_POS_POLL)
    try:
        f.close()
    except Exception:
        pass


# 判定为"不可用"的 Moving 输入地址（本进程内永久停用信号路径，避免重复付等待代价）
_DEAD_SIGNALS = set()

# 各轴的"当前命令值"缓存——盲等时长按实际行程算，不搞一刀切
_ARM_CMD = {}


def signal_handler(sig, frame):
    """Ctrl+C 安全关闭"""
    global running
    print("\n收到关闭信号，正在安全停止产线...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


def stop_rotary_table(modbus_client):
    """停止转盘"""
    modbus_client.write_coil(TABLE_ROTATE_COIL, False)


def sort_product(modbus_client, passed: bool):
    """分拣成品：OK走绿色通道，NG走红色通道"""
    if passed:
        modbus_client.write_coil(SORT_OK_COIL, True)
        time.sleep(0.3)
        modbus_client.write_coil(SORT_OK_COIL, False)
    else:
        modbus_client.write_coil(SORT_NG_COIL, True)
        time.sleep(0.3)
        modbus_client.write_coil(SORT_NG_COIL, False)


def _wait_input(modbus_client, addr, target=True, timeout=5.0, interval=0.05):
    """【基础工具】轮询等待某个 Input 变成目标值。

    参数：
      addr    : 要读的输入地址（如 TABLE_A_LIMIT_90_INPUT）
      target  : 期望值，默认 True（等它变 1）
      timeout : 最多等多久（秒）。★ 调产线时最常改的就是这个
      interval: 每两次读取之间歇多久（秒）。0.05 = 每秒问 20 次

    返回：
      True  = 等到了
      False = 超时了（不代表出错，只代表这段时间内没变成目标值）

    注意：这是"死等"式轮询，没有别的副作用。
    """
    start = time.time()                              # 记下开始时刻
    while time.time() - start < timeout:             # 只要还没超时，就一直问
        try:
            if modbus_client.read_input(addr) == target:   # 读到目标值了吗
                return True                          # 是 → 立刻返回，不等满 timeout
        except Exception:
            # 单次读取失败（网络抖动之类）不算致命，忽略，下一轮再试
            pass
        time.sleep(interval)                         # 歇一下再问，别把 PLC 问爆
    return False                                     # 超时了


def _wait_move_done(modbus_client, moving_addr, timeout=None):
    """【基础工具】等机械臂"运动信号"从 1 落到 0（= 这个轴走完了）。

    现场实测（test_arm_moving.py）：Moving 信号的语义是
        "这个轴正在动 = 1，停下来 = 0"
    所以"等它变 0"就等于"等这个轴到位"。

    参数：
      moving_addr : Moving 输入地址（如 ARM2_MOVING_X_INPUT）
      timeout     : 最长等多久，默认取 config.ARM_MOVE_TIMEOUT

    返回：
      True  = 信号落下了（动作确实完成了）
      False = 超时，或地址是 None，或压根读不到
              调用方应该退回"盲等固定时间"，别卡死在这里
    """
    if moving_addr is None:               # 没给地址就别等了
        return False
    if timeout is None:                   # 没给超时就取 config 里的默认值
        timeout = ARM_MOVE_TIMEOUT
    start = time.time()
    while time.time() - start < timeout:
        try:
            if not modbus_client.read_input(moving_addr):   # 读到 0 → 停下来了
                return True
        except Exception:
            pass                          # 单次读取失败忽略
        time.sleep(0.02)                  # 20ms 问一次，比 input 轮询更快
    return False                          # 超时


def _verify_reg(modbus_client, reg, expect):
    """【排除法诊断】动作之后回读寄存器，看它是不是还等于我们写的值。

    这是分清两件事的关键：
      · 寄存器被改写了  → 回读 != 期望值  ★寄存器被改
      · 寄存器没变但轴跑了 → 回读 == 期望值 ★轴自己跑的

    只在 ARM_POS_ENABLED 打开时做（诊断用，会多一次 Modbus 读）。
    """
    if not ARM_POS_ENABLED:
        return
    got = modbus_client.read_register(reg)
    if got is None:
        _arm_trace(f"    ↩ 回读 reg{reg}: 读不到")
    elif int(got) != int(expect):
        _arm_trace(f"    ↩ 回读 reg{reg}: 【{got}】 ≠ 写入的【{expect}】  ★★★寄存器被改写")
    else:
        _arm_trace(f"    ↩ 回读 reg{reg}: 【{got}】 = 写入值 ✓")


def _pos_reg_of(reg):
    """设定点寄存器 → 对应的【位置反馈】寄存器号（Input Register）。

    用途：动作后靠位置反馈判断"轴是不是真的停稳了"。
    对应关系来自 config.ARM_POS_REG（和 Factory IO 场景一一对应）。
    """
    m = {
        ARM1_X_REG: ARM_POS_REG.get("P2_X"),
        ARM1_Z_REG: ARM_POS_REG.get("P2_Z"),
        ARM2_X_REG: ARM_POS_REG.get("P0_X"),
        ARM2_Z_REG: ARM_POS_REG.get("P0_Z"),
    }
    return m.get(reg)


def _wait_axis_settled(modbus_client, reg, timeout=ARM_SETTLE_TIMEOUT):
    """等某个轴【真正停稳】—— 读位置反馈，连续 N 次读数不变才算停稳。

    ★★ 为什么需要这个（2026-09-28 探针实测）：
       Moving 信号会【提前落下】！实测 reg3 写 8000 时：
           信号在位置 7441 就落下了，轴随后还在继续跑（7627 → 7874）
       程序只等信号的话，会在轴只走了一半时就往下执行，
       于是"轴自己继续跑"看起来就像"多做了一个动作"。

    返回 (是否停稳, 最后读到位置)。
    读不到位置反馈时立刻返回 (True, None) —— 不能因为读不到就把产线卡住。
    """
    pr = _pos_reg_of(reg)
    if pr is None or not ARM_POS_ENABLED:
        return True, None
    last = None
    same = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = modbus_client.read_input_register(pr)
        if v is None:
            return True, None          # 读不到就不阻塞
        if last is not None and v == last:
            same += 1
            if same >= ARM_SETTLE_SAMPLES:
                return True, v
        else:
            same = 0
        last = v
        time.sleep(ARM_SETTLE_POLL)
    return False, last                 # 超时


def _pos_key(reg):
    """把寄存器编号翻译成"实际位置"的键（给 _arm_pos 用）。"""
    if reg == ARM1_X_REG:
        return "P2_X"
    if reg == ARM1_Z_REG:
        return "P2_Z"
    if reg == ARM2_X_REG:
        return "P0_X"
    if reg == ARM2_Z_REG:
        return "P0_Z"
    return None


def _arm_move(modbus_client, reg, value, moving_addr=None, fallback=ARM_MOVE_FLOOR, timeout=None):
    """写机械臂模拟量并等待动作完成。

    等待方式二选一：
      * USE_ARM_MOVING_SIGNAL = True ：等 Moving 信号抬起/落下，动作做完立刻返回
      * USE_ARM_MOVING_SIGNAL = False：直接盲等 fallback 秒（当前默认）

    ⚠ 为什么默认关掉信号：
      实测 Moving 信号只在每次运行的第一件可靠，第二件起就不响应。原来那版会在
      信号不可用时"先白等 ARM_WAKE_TIME、再白等 fallback"，等于双倍开销，
      比原来的纯盲等还慢（step2 +1.6s / step3 +2.2s）。
      现在信号路径一旦判定不可用就本进程内永久停用，不再重复付这个代价。
    """
    # 取这个寄存器上一次被写成的值（用来估算这次要走多远；没有记录就当 0）
    prev = _ARM_CMD.get(reg, 0)
    # ★ 流水账：记下"这一次把哪个寄存器、从多少写到了多少"
    _arm_trace(f"_arm_move: reg{reg}  {prev} -> {value}"
               + (f"  (信号 input{moving_addr})" if moving_addr is not None else "  (无信号)"))
    # ★ 真正下发命令：把模拟量写进寄存器。这一行就是"让机械臂动"
    modbus_client.write_register(reg, value)
    _ARM_CMD[reg] = value          # 记下当前命令值
    # 判断走哪条路：只要满足下面任意一条，就走"盲等固定时间"
    #   a) 没给 Moving 地址
    #   b) config.USE_ARM_MOVING_SIGNAL 关掉了
    #   c) 这个地址已经被判定为"不可用"（见下面的熔断）
    if moving_addr is None or not USE_ARM_MOVING_SIGNAL or moving_addr in _DEAD_SIGNALS:
        if USE_TRAVEL_WAIT:
            # 按实际行程给时间：走 8400 和走 500 不该等一样久。
            # X 和 Z 满行程耗时差别很大（实测 1.59s vs 0.83s），按寄存器查表取。
            axis = "X" if reg in (ARM1_X_REG, ARM2_X_REG) else "Z"
            full = ARM_TRAVEL_TIME.get(axis, ARM_TRAVEL_TIME_DEFAULT) \
                if isinstance(ARM_TRAVEL_TIME, dict) else ARM_TRAVEL_TIME
            travel = abs(value - prev) / 10000.0
            wait = max(fallback, full * travel + ARM_MIN_MOVE_TIME)
        else:
            # 【当前实际走的这条】盲等固定时间。这个值来自调用方传的 fallback，
            # 或者函数定义里的默认值 ARM_MOVE_FLOOR
            wait = fallback
        time.sleep(wait)               # ← 就等在这里
        # ★ 等轴真正停稳（Moving 信号会提前落下，光等信号不够）
        _wait_axis_settled(modbus_client, reg)
        # ★ 记实际位置：命令写下去了，机械臂到底走到哪？
        _verify_reg(modbus_client, reg, value)      # 排除法：回读寄存器有没有被改写
        _pk = _pos_key(reg)
        if _pk:
            _arm_trace(f"    ↳ 到位后实际位置: {_arm_pos(modbus_client, (_pk,))}  (命令 {value})")
        return False                   # 返回 False 表示"没用到信号"

    # 走到这里说明要用信号判断了。分两段等：
    #   第一段：等信号"抬起来"，确认机构真的起步了
    #   （不能一写完就判断，机构有启动迟滞，太早看会误判成"已经到位"）
    rose = False
    start = time.time()
    while time.time() - start < ARM_WAKE_TIME:
        try:
            if modbus_client.read_input(moving_addr):
                rose = True
                break
        except Exception:
            pass
        time.sleep(0.02)

    # 信号一直没抬起来 → 说明这个地址不能用
    if not rose:
        # ★ 熔断：记进 _DEAD_SIGNALS，本次运行后面所有动作都不再走信号路径，
        #   避免每次都白等一遍 ARM_WAKE_TIME
        _DEAD_SIGNALS.add(moving_addr)
        if ARM_MOVE_DEBUG:
            print(f"      [arm] input {moving_addr} 信号不响应，本次运行起全部改用盲等")
        time.sleep(fallback)
        _wait_axis_settled(modbus_client, reg)
        _verify_reg(modbus_client, reg, value)
        _pk = _pos_key(reg)
        if _pk:
            _arm_trace(f"    ↳ 信号失效盲等后实际位置: {_arm_pos(modbus_client, (_pk,))}  (命令 {value})")
        return False

    # 信号抬起来了 → 等它落下去（= 这个轴走完）
    if _wait_move_done(modbus_client, moving_addr, timeout):
        # ★★ 关键修正（2026-09-28 探针实测）：Moving 信号会【提前落下】！
        #    reg3 写 8000 时，信号在位置 7441 就落了，轴还在继续跑到 7874。
        #    原来这里直接 return True，程序就带着"只走了一半"的轴往下执行，
        #    轴自己继续跑的那一段看起来就是"机械臂多做了一个动作"。
        #    现在必须等位置反馈真正停住才继续。
        _settled, _final = _wait_axis_settled(modbus_client, reg)
        if not _settled and _final is not None:
            _arm_trace(f"    ⚠ 等停稳超时，最后位置 {_final}（命令 {value}）")
        # ★ 记实际位置：信号说"走完了"，实际停在哪个数值？
        _verify_reg(modbus_client, reg, value)      # 排除法：回读寄存器有没有被改写
        _pk = _pos_key(reg)
        if _pk:
            _arm_trace(f"    ↳ 信号确认到位后实际位置: {_arm_pos(modbus_client, (_pk,))}  (命令 {value})")
        return True                    # 用信号确认到位了

    _DEAD_SIGNALS.add(moving_addr)
    if ARM_MOVE_DEBUG:
        print(f"      [arm] input {moving_addr} 等超时，本次运行起全部改用盲等")
    time.sleep(fallback)
    _wait_axis_settled(modbus_client, reg)
    return False


def _arm_home(modbus_client, x_reg, z_reg, x_moving=None, z_moving=None,
              tag="", settle=None):
    """机械臂回原点 —— 先轻微前伸/下探一下，再回零。

    【为什么要"先伸一下"】机械臂是速度控制不是位置闭环：
    如果它已经贴着原点，直接写 0 等于什么都没做，机构可能纹丝不动，
    位置就从上一轮的残留状态开始跑，逐件累积偏移，
    最后表现为"下个周期开头把伸出极限当成了原点"。
    先给一个轻微的前伸/下探（ARM_HOME_PRESTRETCH），把机构从原地"唤醒"，
    再写 0 归零，才能保证它真的回到了原点。

    【动作序列 —— 就这三步，不要再往上叠补丁】
      1. X、Z 同时轻微前伸/下探（同一个反向偏移值）
      2. 保持一小段，让机构真的动起来
      3. X、Z 同时写 0 归零，然后等一段稳定时间

    为什么是"同时"而不是"Z 先 X 后"：
      Z 先起步那套是为了绕开工装碰撞加的，叠加之后整体时序变复杂、
      反而引出了转盘限位的新问题。先把回原点这一个问题做干净，
      设备之间的配合节拍留到后面单独处理——两个问题叠在一起会互相掩盖。

    【时间开销】ARM_HOME_PRESTRETCH_HOLD + ARM_HOME_SETTLE，
    其中 SETTLE 必须 >= X 满行程实测 1.59s，否则 X 没缩回去就被当成归零完成。
    """
    if settle is None:
        settle = ARM_HOME_SETTLE

    # ★ 诊断：把"动作前，程序以为这两个轴在哪"打出来。
    #   这个值来自 _ARM_CMD 缓存，就是上一次写给这个寄存器的命令值。
    #   如果这里显示的不是 0，说明上一轮结束时轴停在了半路（残留行程），
    #   这就是"臂0 带着残留行程进入下一个周期"的直接证据。
    if ARM_MOVE_DEBUG:
        print(f"      [arm] 回原点 ({tag})  动作前缓存值: "
              f"X={_ARM_CMD.get(x_reg, 0)}  Z={_ARM_CMD.get(z_reg, 0)}")

    # ---------- 第 0 步：先清掉残留行程，让两轴真的回到 0 ----------
    # ★ 为什么加这一步：如果上一轮结束时轴停在半路（比如 X 还停在 5000），
    #   直接做"前伸 500 → 归零"会从那个残留位置开始跑，看起来就是
    #   "一上来就伸到极限"。先把两个轴都写成 0 并等够时间，
    #   再开始正常的"前伸→归零"，每次就都从真正的原点出发。
    _arm_trace(f"回原点[{tag}] 第0步-清残留: X reg{x_reg} -> 0, Z reg{z_reg} -> 0 "
               f"(清之前 X={_ARM_CMD.get(x_reg, 0)} Z={_ARM_CMD.get(z_reg, 0)})")
    modbus_client.write_register(x_reg, 0)
    modbus_client.write_register(z_reg, 0)
    _ARM_CMD[x_reg] = 0
    _ARM_CMD[z_reg] = 0
    time.sleep(settle)          # 等它真的回到 0（最坏 X 满行程 1.59s）

    if ARM_MOVE_DEBUG:
        print(f"      [arm] 回原点：前伸/下探 {ARM_HOME_PRESTRETCH} → 归零 ({tag})")

    # ---------- 第 1 步：轻微前伸/下探 ----------
    # X 往外伸一点、Z 往下探一点。幅度很小（ARM_HOME_PRESTRETCH，默认 500 = 5%），
    # 目的是让机构"动起来"，避免它本来就贴着原点时写 0 等于没写。
    #
    # ★★★ 关于记录里那个 500 —— 说明白它是什么、不是什么：
    #     下面是【命令值】（= config.ARM_HOME_PRESTRETCH 这个常量），
    #     不是机械臂的实际位置。这两个轴没有位置反馈（场景里的
    #     "X/Z Position (V)" 没映射到 Modbus），所以程序根本读不到臂在哪。
    #     能验证的只有两级：
    #       1) 寄存器有没有真的变成 500   → 用 read_register 回读
    #       2) 机械臂有没有响应（动没动） → 用 Moving 信号代理判断
    # ★ 先记一次"动作前的实际位置"（想读实际位置，必须先在 Factory IO 里
    #   把四个 Position (V) 点挂到 Input Register，见 config.ARM_POS_REG 注释）
    _px = "P2_X" if x_reg == ARM1_X_REG else "P0_X"
    _pz = "P2_Z" if z_reg == ARM1_Z_REG else "P0_Z"
    _arm_trace(f"回原点[{tag}] 前伸前·实际位置: {_arm_pos(modbus_client, (_px, _pz))}")

    _arm_trace(f"回原点[{tag}] 第1步-前伸【命令值】: X reg{x_reg} -> {ARM_HOME_PRESTRETCH}, "
               f"Z reg{z_reg} -> {ARM_HOME_PRESTRETCH}")
    modbus_client.write_register(x_reg, ARM_HOME_PRESTRETCH)   # X 往外
    modbus_client.write_register(z_reg, ARM_HOME_PRESTRETCH)   # Z 往下
    _ARM_CMD[x_reg] = ARM_HOME_PRESTRETCH
    _ARM_CMD[z_reg] = ARM_HOME_PRESTRETCH

    # ★ 校验①：回读 —— 确认寄存器里真的是 500（而不是写失败）
    for _r in (x_reg, z_reg):
        _back = modbus_client.read_register(_r)
        if _back is not None and _back != ARM_HOME_PRESTRETCH:
            _arm_trace(f"★回读不符! reg{_r} 应为 {ARM_HOME_PRESTRETCH}，实际读到 {_back}")
        elif _back is None:
            _arm_trace(f"回读 reg{_r} 失败（读不到或后端不支持）")

    # ★ 校验②：响应 —— 写完之后这个轴的 Moving 信号有没有抬起来？
    #
    #  ★★ 2026-09-28 节拍优化：这一段【默认关闭】（ARM_HOME_RESP_PROBE = False）。
    #     它每次调用要等 ARM_WAKE_TIME + 0.3 ≈ 0.7 秒，一个周期调 6 次 = 白花 4.2 秒。
    #     当初加它是为了排查"前伸 500 到底动没动"，那个问题已经查清了
    #     （标定确认：写 500 位置确实到 499）。
    #     以后要是怀疑"机械臂没响应"，把 config.ARM_HOME_RESP_PROBE 设回 True 即可。
    if ARM_HOME_RESP_PROBE:
        for _reg, _mv, _nm in ((x_reg, x_moving, "X"), (z_reg, z_moving, "Z")):
            if _mv is None:
                continue
            _moved = False
            _t0 = time.time()
            while time.time() - _t0 < ARM_WAKE_TIME + 0.3:
                try:
                    if modbus_client.read_input(_mv):
                        _moved = True
                        break
                except Exception:
                    pass
                time.sleep(0.02)
            if not _moved:
                _arm_trace(f"★前伸无响应! {_nm} 轴 (reg{_reg}) 写了 {ARM_HOME_PRESTRETCH} "
                           f"但 Moving(input{_mv}) 从未抬起 = 机械臂没动")
            else:
                _arm_trace(f"前伸有响应: {_nm} 轴 Moving(input{_mv}) 抬起过（机械臂确实动了）")

    # ---------- 第 2 步：保持一小段 ----------
    # 等前伸动作真的发生。★ 这段时间偏短（0.5s），机械臂停在伸展位时
    # 前伸走不完就被第 3 步打断了——不影响最终位置，但"唤醒"效果打折。
    # 想调就改 config.ARM_HOME_PRESTRETCH_HOLD
    # ★ 流水账记这一步，是为了配合探针判断"前伸够不够时间走完"：
    #   前伸 500 只需要 0.08s，但从伸展位回 500 可能要 1.5s。
    _arm_trace(f"回原点[{tag}] 第2步-保持 {ARM_HOME_PRESTRETCH_HOLD}s "
               f"(前伸动作在这段时间里发生)")
    time.sleep(ARM_HOME_PRESTRETCH_HOLD)

    # ---------- 第 3 步：回零 ----------
    # ★★ 这里是整个"回原点"的核心：写 0 = 命令两个轴回到原点。
    #    能否真的回去，取决于下面 sleep(settle) 够不够长。
    _arm_trace(f"回原点[{tag}] 第3步-归零【命令值】: X reg{x_reg} -> 0, Z reg{z_reg} -> 0")
    modbus_client.write_register(x_reg, 0)                     # X 缩回原点
    modbus_client.write_register(z_reg, 0)                     # Z 抬回原点
    _ARM_CMD[x_reg] = 0                # 同步命令值缓存
    _ARM_CMD[z_reg] = 0
    # ★★ 等它走完。这个时间必须 >= "回零这段路"的耗时，
    #    最坏情况是机械臂停在 X=10000 时（满行程实测 1.59s），
    #    config.ARM_HOME_SETTLE 默认 1.9s。
    #    设小了 → X 没缩回去就被当成"已归零" → 下一件从半路出发 → 位置逐件偏移。
    time.sleep(settle)
    # ★ 归零之后读一次实际位置 —— 这是判断"到底有没有回到原点"的唯一证据。
    #   命令写的是 0，如果这里读到的不是 0，说明机械臂没有真的回去。
    _arm_trace(f"回原点[{tag}] 第3步-归零后·实际位置: "
               f"{_arm_pos(modbus_client, (_px, _pz))}  (命令 X=0 Z=0)")


def _table_wait_limit(modbus_client, addr, target, timeout=8.0, what=""):
    """等转盘限位到位。到了返回 True，超时返回 False（并打印出来，便于定位）。"""
    if _wait_input(modbus_client, addr, target, timeout=timeout):
        return True
    print(f"      [table] 限位未到位: {what} (input {addr} != {target})")
    return False


def _arm_home_both(modbus_client, tag="初始化双臂"):
    """★ 两个臂【同时】回原点（节拍优化 2026-09-28）

    为什么做这个：
        原来两个臂是【串行】回零：臂2 走完 3.4s，再轮到臂0 走 3.4s，合计约 6.8s。
        但两个臂是两个【独立】的执行机构，各有一套寄存器和 Moving 信号，
        完全可以同时下发命令、并行等待 —— 时间直接减半。

    动作序列（和 _arm_home 完全一样，只是两个臂一起做）：
        0. 两臂 X/Z 全部写 0，等 SETTLE
        1. 两臂 X/Z 全部写 500（前伸唤醒）
        2. 保持 PRESTRETCH_HOLD
        3. 两臂 X/Z 全部写 0，等 SETTLE

    ★ 注意：SETTLE 仍然是 1.9s（不是 0.95s）。因为它是"等机械动作完成"的
      绝对时间，两臂并行时各自都需要这么久，不会因为并行而变快。
      省下的是"第二个臂的那一整套 SETTLE + HOLD"。

    ⚠ 如果以后发现"两臂同时动时有一个走不到位"（比如电流不够/机械打架），
      把调用处换回两次 _arm_home 串行即可（注释里保留了写法）。
    """
    _arm_trace(f"=== 双臂同时回零 [{tag}] 开始 ===")
    _arm_trace(f"    臂2 起始: {_arm_pos(modbus_client, ('P2_X', 'P2_Z'))}   "
               f"臂0 起始: {_arm_pos(modbus_client, ('P0_X', 'P0_Z'))}")

    _t0 = time.time()
    # --- 第0步：两臂都清残留到 0 ---
    for _r in (ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG):
        modbus_client.write_register(_r, 0)
        _ARM_CMD[_r] = 0
    time.sleep(ARM_HOME_SETTLE)

    # --- 第1步：两臂同时轻微前伸/下探（唤醒机构）---
    for _r in (ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG):
        modbus_client.write_register(_r, ARM_HOME_PRESTRETCH)
        _ARM_CMD[_r] = ARM_HOME_PRESTRETCH
    _arm_trace(f"    双臂前伸 {ARM_HOME_PRESTRETCH}（唤醒）")

    # --- 第2步：保持，让机构真的动起来 ---
    time.sleep(ARM_HOME_PRESTRETCH_HOLD)

    # --- 第3步：两臂同时归零 ---
    for _r in (ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG):
        modbus_client.write_register(_r, 0)
        _ARM_CMD[_r] = 0
    time.sleep(ARM_HOME_SETTLE)

    _used = time.time() - _t0
    _arm_trace(f"    臂2 结束: {_arm_pos(modbus_client, ('P2_X', 'P2_Z'))}   "
               f"臂0 结束: {_arm_pos(modbus_client, ('P0_X', 'P0_Z'))}")
    _arm_trace(f"=== 双臂同时回零 [{tag}] 完成，用时 {_used:.2f}s "
               f"（串行约需 2 倍）===")


def _table_pulse(modbus_client, turn_coil, limit_addr, timeout=8.0, what=""):
    """★ 点一下转盘，等它转到目标限位。【不松手】

    探针实测（test_table_hold.py）转盘的真实行为：
        写 True  → 开始转
        到 90°   → 90°限位亮
        写 False → **0.11 秒后就开始往回转，约 2.4 秒回到 0°**

    ★★ 也就是说"松开线圈"本身就是一条"回 0°"命令。
       所以这个函数故意【不松手】——松手的时机交给调用方，
       这样"转到位 → 等料进来 → 再松手回去"才有意义。
       （原来在函数里就松手了，等于我们还没开始等料，转盘已经在往回走了。）

    返回 True = 到位；False = 超时没到位（会打印出来）
    """
    modbus_client.write_coil(turn_coil, True)      # 点一下，开始转
    # 等到位。转盘机械上转 90° 大约 2.4 秒
    ok = _table_wait_limit(modbus_client, limit_addr, True, timeout, what)
    if ARM_MOVE_DEBUG:
        print(f"      [table] {what}: 到位并保持（线圈不放）" if ok
              else f"      [table] {what}: 未到位")
    return ok


def _table_release(modbus_client, turn_coil, limit0_addr=None, timeout=8.0, what=""):
    """★ 松开转盘线圈 —— 这会让它转回 0°。

    必须等到真的松手才能调用（也就是"料已经进/出完了"之后）。

    参数 limit0_addr：如果给了，等 0° 限位确认回到位；不给就不等。
    """
    modbus_client.write_coil(turn_coil, False)     # 松手 → 转盘开始回 0°
    if ARM_MOVE_DEBUG:
        print(f"      [table] {what}: 已松手，转盘开始回 0°")
    if limit0_addr is None:
        return True
    return _table_wait_limit(modbus_client, limit0_addr, True, timeout, what)


def _table_index(modbus_client, turn_coil, limit_addr, timeout=8.0, what=""):
    """【兼容旧调用】点一下转盘 → 等到位 → 立刻松手。

    ⚠ 这个函数会在到位后马上松手 = 立刻命令它回 0°。
      只适合"转过去马上回来"的场景（比如转盘B 那一下）。
      如果需要在目标位置停留等料，必须改用 _table_pulse + _table_release。
    """
    ok = _table_pulse(modbus_client, turn_coil, limit_addr, timeout, what)
    modbus_client.write_coil(turn_coil, False)
    return ok


def produce_one(modbus_client):
    """★【核心】生产一件产品的完整流程。

    这是整个产线的"动作模板"——调产线 90% 的时间都在改这个函数。

    流程（5 个步骤）：
      步骤1  转盘A 转90°接料 → 回0° → 滚轮+皮带2 把料送到机械臂2 工位
      步骤2  机械臂2 回原点 → 取料 → 搬到转盘B → 放料 → 再回原点
      步骤3  机械臂0 回原点 → 点胶 → 再回原点 → 转盘B 转90°
      步骤4  转盘B 滚轮 + 皮带3，把料送到视觉1
      步骤5  视觉1 判定 OK/NG → OK 推杆推出 → 结束

    参数：
      modbus_client : 已经 connect() 好的 Modbus 客户端

    返回：(is_ok, step_times, stations_passed) 三个值
      is_ok          : True=良品, False=不良品（由步骤5 的视觉决定）
      step_times     : {"step1": 12.5, "step2": 8.8, ...} 每步耗时，写进爬坡日志
      stations_passed: {1: True, 2: True, 3: True, 4: False} 各工位是否通过
    """

    is_ok = False                     # 本件最终判定（True=良品），步骤5 会改写
    # ★ 三分类结论（2026-09-28）：良品 / 不良 / 漏料
    #   为什么单独拿出来：is_ok 只有 True/False 两态，
    #   而"不良"和"漏料"要分开统计（现场要看的是这两个数各是多少）。
    verdict = "未知"                  # 步骤5 会改成 良品/不良/漏料
    step_times = {}                   # 各步骤耗时，给爬坡日志用
    _step_start = time.time()         # 当前步骤的起始时刻（下面每步开头会重置）

    # 本件在各工位是否走通（工位编号见 config.STATIONS）
    # 说明：目前只有工位4（成品检测）有真实视觉判定；工位1~3 按"动作走完即通过"记。
    # 把统计更新放回这里，是因为之前 produce_one 从"2参数带统计"改成"1参数"时，
    # 把统计那几行一起删掉了，导致 GUI/LLM 永远看到 0/0、良率100%。
    stations_passed = {1: False, 2: False, 3: False, 4: False}

    def _mark_step(name, next_step=None):
        """记录当前步骤耗时。

        ★ 2026-09-28 新增 next_step：同时通知仪表盘"接下来做第几步"。
          这样 GUI 右边的步骤进度栏能实时跟着走，而不是只有最后的结果。
          next_step=None 表示这一件做完了（回到空闲）。
        """
        step_times[name] = round(time.time() - _step_start, 2)
        if next_step is not None:
            try:
                app.set_step(next_step)
            except Exception:
                pass          # GUI 出问题不影响生产

    # ==========================================================================
    #  步骤1：转盘A 接料 → 转回 0° → 送料到皮带2
    #  实测约 13.7 秒，其中约 7.4 秒是转盘机械转动时间（转 90° 要 3~4 秒/次）
    # ==========================================================================
    print(">>> 步骤1: 转盘A转90°接料 → 回0° → 送料到皮带2")
    _step_start = time.time()         # ★ 重置计时起点，本步耗时从这里算
    try:
        app.set_step(1)               # ★ 通知仪表盘：开始步骤1
    except Exception:
        pass
    # ★ 两个臂【同时】初始化回零（节拍优化：原来串行约 6.8s，并行约 3.4s）
    #   两臂是独立的执行机构，互不干涉，可以同时下发命令、并行等待。
    _arm_home_both(modbus_client, tag="初始化双臂")
    # 如果以后发现"两臂同时动会互相影响"（走不到位/打架），
    # 就把上面一行换成下面这个串行版本：
    # _arm_home(modbus_client, ARM1_X_REG, ARM1_Z_REG,
    #           ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT, tag="初始化机械臂2")
    # _arm_home(modbus_client, ARM2_X_REG, ARM2_Z_REG,
    #           ARM0_MOVING_X_INPUT, ARM0_MOVING_Z_INPUT, tag="初始化机械臂0")
    

    # --- 1.1 转盘A 转到 90°（接料位），★ 到位后【保持不放】---
    # 为什么不能马上松手：探针实测，写 False 会在 0.11 秒内让转盘开始往回走，
    # 约 2.4 秒就回到 0° —— 那样料根本没时间进来，就是卡料的根因。
    # 所以这里只用 _table_pulse（点到 90° 就停住保持），
    # 松手（回 0°）留到 1.4 步、料进完之后再做。
    _table_pulse(modbus_client, TABLE_A_TURN_COIL, TABLE_A_LIMIT_90_INPUT, what="A→90°接料")

    # --- 1.2 发料 + 皮带1 + 转盘滚轮，把料送进转盘中心 ---
    # 三个动作同时开：
    #   EMITTER      发料器吐出零件
    #   BELT_0       皮带机0（来料皮带，从发料器送到转盘A 门口）
    #   TABLE_A_ROLL 转盘A 滚轮正转，把料从门口拉进中心
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)    # 转盘A 滚轮正转
    modbus_client.write_coil(BELT_0_COIL, True)            # 皮带机0
    modbus_client.write_coil(EMITTER_COIL, True)           # 发料器
    # ★ 这段时间就是"料从发料器走到转盘中心"的总时间。
    #   转盘已经停在 90°（接料位），滚轮+皮带把料拉进来。
    #   ★★ 没等够就转回 0° = 料卡在盘边 —— 卡料的首要原因。
    #   改这里：config.TABLE_A_LOAD_WAIT
    time.sleep(TABLE_A_LOAD_WAIT)

    # --- 1.3 停发料器和滚轮，皮带0 再多转一会儿 ---
    #  ★★★ 2026-09-28 现场反馈（两次，方向相反，记录下来避免来回改）★★★
    #    第1次："皮带1 有时送料不到位" -> 让皮带0 多转（对）
    #    第2次："转盘滚轮时间太长，走的很不顺" -> 滚轮不能跟着延长（错）
    #
    #  ★ 为什么滚轮【不能】转太久：
    #      滚轮的作用是"把料从门口拉进转盘中心"。拉到中心之后就该停，
    #      再转就是把料往中心之外推 —— 料会被推偏、或者顶在盘边，
    #      下一步转盘一转就蹭，表现为"走得不顺"。
    #      所以：滚轮按原时间（TABLE_A_LOAD_WAIT）停，只有皮带0 多转。
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)   # 停滚轮（按原时间）
    modbus_client.write_coil(EMITTER_COIL, False)          # 停发料器
    time.sleep(BELT0_EXTRA_TIME)                           # ★ 只有皮带0 继续转
    modbus_client.write_coil(BELT_0_COIL, False)           # 停皮带0
    # ★ 料刚进中心还有惯性，要停稳再转盘，否则转的时候料会偏、蹭到盘边
    time.sleep(TABLE_A_REST)

    # --- 1.4 转盘A 回 0°（送料位）---
    # ★ 这里不用再"点一下转 0°"：只要把线圈松开（写 False），转盘自己就会回 0°。
    #   （探针实测：松手后 0.11s 开始回，约 2.4s 到 0°）
    #   之前写成 write_coil(TABLE_A_TURN_COIL, True) 是错的——那是"再转一次 90°"。
    _table_release(modbus_client, TABLE_A_TURN_COIL, TABLE_A_LIMIT_0_INPUT, what="A→0°送料")

    # --- 1.5 转盘滚轮 + 皮带2，把料送到机械臂2 工位 ---
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)    # 转盘A 滚轮正转（把料推出去）
    modbus_client.write_coil(BELT_2_COIL, True)            # 皮带机2（送到锁螺丝工位）
    # 【2026-09-28】已删除"等漫反射传感器"—— 现场确认那个传感器是假的，
    #   原来只会白等 5 秒（再 +1.5 秒保底）。现在改成固定走带时间。
    #   ★ 值来自现场实测：发料 → 料撞挡板 共 14 秒（路径见 config 注释）。
    time.sleep(BELT2_TRANSIT_WAIT)
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)   # 停滚轮
    modbus_client.write_coil(BELT_2_COIL, False)           # 停皮带2
    time.sleep(BELT2_STOP_SETTLE)                          # 收尾稳定

    
                # ====== 步骤2: 机械臂1搬运到转盘B ======
    print(">>> 步骤2: 机械臂1搬运到转盘B")
    _mark_step("step1", 2)      # 步骤1 走完 → 开始步骤2
    stations_passed[1] = True          # 步骤1 走完 = 视觉检测工位通过
    _step_start = time.time()
    
    # 【节拍优化】已删除"取料前"回零 —— 冗余动作
    #   理由：步骤1 开头刚做过"初始化机械臂2"回零，之后这个臂【一次都没动过】
    #         （中间只有转盘A 和皮带在动作）。臂本来就在 0，再回一次零：
    #           · 白花 4.8 秒
    #           · 而且 _arm_home 会把臂推到 500 再回 0 —— 等于把已归零的臂又动一遍
    #   如果以后发现"取料时位置不对"，把下面两行取消注释即可恢复：
    # _arm_home(modbus_client, ARM1_X_REG, ARM1_Z_REG,
    #           ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT, tag="取料前")

    # ===== 机械臂2 取料 =====
    modbus_client.write_coil(ARM1_GRAB_COIL, True)                     # 先开吸嘴
    time.sleep(ARM_GRAB_SETTLE)                                        # 等吸稳
    # 不再给每个动作手写 fallback：等待时长统一由行程模型按实测值算
    # （X 1.70 / Z 0.95 满行程），手写的固定值只会盖掉更准的模型。
    _arm_move(modbus_client, ARM1_Z_REG, ARM1_Z_CONTACT, ARM2_MOVING_Z_INPUT)  # Z下接触零件
    _arm_move(modbus_client, ARM1_Z_REG, 0,    ARM2_MOVING_Z_INPUT)    # Z上提起
    _arm_move(modbus_client, ARM1_X_REG, ARM1_X_TARGET, ARM2_MOVING_X_INPUT)  # X伸到转盘B上方

    # ===== 机械臂2 下料 =====
    _arm_move(modbus_client, ARM1_Z_REG, ARM1_Z_WORK, ARM2_MOVING_Z_INPUT)     # Z下放料
    modbus_client.write_coil(ARM1_GRAB_COIL, False)                    # 松吸嘴
    time.sleep(ARM_GRAB_SETTLE)

    _arm_home(modbus_client, ARM1_X_REG, ARM1_Z_REG,
              ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT, tag="锁螺丝完成")
    

                # ======步骤3： 点胶工位:机械臂2点胶 ======
    print(">>> 步骤3： 点胶工位:机械臂2点胶")
    _mark_step("step2", 3)      # 步骤2 走完 → 开始步骤3
    stations_passed[2] = True          # 步骤2 走完 = 锁螺丝工位通过
    _step_start = time.time()  
    # 【节拍优化】已删除"点胶前"回零 —— 冗余动作
    #   理由同"取料前"：步骤1 开头刚做过"初始化机械臂0"回零，
    #   之后这个臂一次都没动过，本来就在 0，再回一次白花 4.8 秒。
    #   要恢复就把下面两行取消注释：
    # _arm_home(modbus_client, ARM2_X_REG, ARM2_Z_REG,
    #           ARM0_MOVING_X_INPUT, ARM0_MOVING_Z_INPUT, tag="点胶前")

    # ===== 机械臂0 点胶 =====
    # ★ 点胶臂只需要简单的两个动作，不要照搬锁螺丝臂的"两段 Z"：
    #     X 伸出到点胶位 → Z 下探到工作高度（只下这一次）→ 停留
    #   现场明确：8100 就是点胶的工作高度，不需要先探一下再抬起来。
    #   （之前那段 "Z下接触 → Z上提起" 是照搬锁螺丝臂形状加的多余动作，已删除）
    _arm_move(modbus_client, ARM2_X_REG, ARM2_X_TARGET, ARM0_MOVING_X_INPUT)  # X伸到点胶位
    _arm_move(modbus_client, ARM2_Z_REG, ARM2_Z_WORK, ARM0_MOVING_Z_INPUT,
              fallback=ARM_DISPENSE_TRAVEL)                            # Z下到工作高度（一次）
    time.sleep(ARM_DISPENSE_DWELL)                                     # 点胶停留

    _arm_home(modbus_client, ARM2_X_REG, ARM2_Z_REG,
              ARM0_MOVING_X_INPUT, ARM0_MOVING_Z_INPUT, tag="点胶完成")

    # 转盘B → 90°（把料从机械臂放料位转到出料位），★ 到位后【保持不放】
    # ★ 与转盘A 完全同一套逻辑：
    #     _table_pulse  → 转到 90° 并保持（松手会立刻让它回 0°，所以先不松）
    #     ...在 90° 位置把料推出去（下面步骤4.1）...
    #     _table_release → 料推完了再松手，让它回 0°（步骤4.2）
    _table_pulse(modbus_client, TABLE_B_TURN_COIL, TABLE_B_LIMIT_90_INPUT, what="B→90°出料")


                # ====== 步骤4: 转盘B送料到皮带3（右视觉位） ======
    print(">>> 步骤4: 转盘B送料到皮带3")
    _mark_step("step3", 4)      # 步骤3 走完 → 开始步骤4
    stations_passed[3] = True          # 步骤3 走完 = 点胶工位通过
    _step_start = time.time()
    # --- 4.1 转盘B 滚轮 + 皮带3，把料送到视觉1 ---
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, True)    # 转盘B 滚轮正转（把料推出去）
    modbus_client.write_coil(BELT_3_COIL, True)            # 皮带机3（送到视觉1）
    # ★★★ 2026-09-28 新增：记下皮带3 的启动时刻 ★★★
    #   现场反馈"NG 时皮带3 不能及时停"。根因不是响应慢（轮询 50ms），
    #   而是皮带3 原来要一路转到视觉判定，总时长 12.9 秒 ——
    #   料在视觉位被看到时，已经冲过推杆位置，停皮带也救不回来。
    #   现在给它一个独立的运行上限 BELT3_RUN_TIME，到点就停。
    _belt3_t0 = time.time()
    # ★★ 这里原来是 time.sleep(.0) —— 等于没等，滚轮只转了 1.5 秒就被下面的
    #    write_coil(..., False) 停掉，料根本来不及从转盘走到皮带3，
    #    结果料留在转盘上、步骤5 等不到视觉 → 卡料。
    #    现在给足时间：改这里看 config.TABLE_B_PUSH_WAIT
    time.sleep(TABLE_B_PUSH_WAIT)
    # --- 4.2 料已推出，停滚轮；皮带3 继续走，把料送到视觉位 ---
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, False)   # 停转盘滚轮
    # --- 4.3 料已推出，松手让转盘B 回 0°（和转盘A 的 1.4 步同一套）---
    #   松手 = 命令回 0°，约 2.4 秒回到位。这里等它确认到位再往下走，
    #   否则下一步（转盘B 又要接料）会赶上它还在转。
    _table_release(modbus_client, TABLE_B_TURN_COIL, TABLE_B_LIMIT_0_INPUT, what="B→0°复位")
    # 皮带3 继续走一段，确保料走到视觉1 的正下方
    time.sleep(TABLE_B_SETTLE)
    # ★ 到这里皮带3 已经转了 (TABLE_B_PUSH_WAIT + 转盘B回0° + TABLE_B_SETTLE) 秒，
    #   把剩余允许时间算出来，交给步骤5 用（超时就停皮带，别让它一直转）
    _belt3_left = BELT3_RUN_TIME - (time.time() - _belt3_t0)
    if ARM_MOVE_DEBUG:
        print(f"      [belt3] 已转 {time.time() - _belt3_t0:.1f}s，"
              f"还剩 {_belt3_left:.1f}s 到上限 {BELT3_RUN_TIME}s")



                        # ====== 步骤5: 右侧视觉检测 ======
    print(">>> 步骤5: 视觉检测 (VISION_1)")
    _mark_step("step4", 5)      # 步骤4 走完 → 开始步骤5
    _step_start = time.time()
   
    # ==========================================================================
    # ★★★ 视觉极性（2026-09-28 现场确认）★★★
    #     VISION_1_INPUT = True   → 蓝色料 = NG → 停皮带3 + 推杆推出去
    #     VISION_1_INPUT = False  → 绿色料 = OK → 不停，正常走过去
    #
    #  ⚠ 之前代码是反的（把 True 当 OK、False 当 NG），已纠正。
    #     之前"读到的全是 NG"是因为现场只放了绿料、没放蓝料，
    #     传感器本身是好的 —— 不是传感器坏。
    # ==========================================================================
    print(f"等待料通过视觉位（超时{VISION_WAIT_TIMEOUT}秒）...")
    # ★★★ 判定口径（2026-09-28 现场确认）★★★
    #     VISION_1 = True   -> 蓝色料 -> 不良
    #     VISION_1 = False  -> 绿色料 -> 良品
    #     一直读不到（超时/料没到）-> 漏料 -> 也算一件，计入总数
    #
    #  ⚠ 坑：VISION_1 = False 在"绿料经过"和"根本没有料"两种情况下都成立，
    #     所以不能一读到 False 就判良品 —— 必须确认"确实有料经过视觉位"。
    #     判据：只要在等待窗口内读到过至少一次有效电平变化（或稳定读到），
    #     且没有一直读不到的情况，就算"料到了"。
    #     实现上用一个"看到过料"的标记：
    #       · 读到 True（蓝）      -> 料到了，且是不良
    #       · 读到 False（绿）     -> 料到了，且是良品
    #       · 全程只有 False 且从未变过 -> 无法区分"绿料"和"没料"
    #         这时用 VISION_MISS_GRACE 之后仍未出现任何变化 来判定漏料
    saw_ng = False        # 看到过"蓝料"（= True）
    saw_ok = False        # 看到过"绿料"（= False）
    last_val = None
    _val_changes = 0      # 电平变化次数（用来判断"到底有没有料经过"）
    start = time.time()   # ★ 等待窗口的起点（原来这行被注释块盖掉了，会 NameError）
    # ★★ 皮带3 的运行上限（2026-09-28 修正）★★
    #   用【从皮带启动时刻算的绝对时刻】：皮带3 在 _belt3_t0 开的，
    #   所以它最多转到 _belt3_t0 + BELT3_RUN_TIME。
    #   ⚠ 之前写的是 start + max(_belt3_left, 0.5)：
    #       _belt3_left 已经是负数（步骤4 结束时皮带就超过上限了），
    #       max(负数, 0.5) = 0.5 -> 皮带在步骤5 开始后 0.5 秒就停了，
    #       而那时料还没走到视觉位 —— 直接导致"皮带根本没停、料冲过去"。
    _belt3_deadline = _belt3_t0 + BELT3_RUN_TIME
    _belt3_stopped = False
    if ARM_MOVE_DEBUG:
        print(f"      [belt3] 步骤5 开始时皮带已转 {start - _belt3_t0:.2f}s，"
              f"上限 {BELT3_RUN_TIME}s（还剩 {_belt3_deadline - start:.2f}s）")
    # ★★ 循环退出条件（2026-09-28 修正）★★
    #   只有两种情况才退出：
    #     ① 读到 True（不良）—— 有结论了
    #     ② 等满 VISION_WAIT_TIMEOUT —— 时间到，按已有信息判定
    #   ★ 皮带停了也【不退出】：料被拦停后可能还要一会儿才滑到视觉位，
    #     这段等待必须继续看着，否则会把"料还没到"误判成"绿料/良品"。
    _loop_t = 0.0
    while (not saw_ng) and (time.time() - start < VISION_WAIT_TIMEOUT):
        val = bool(modbus_client.read_input(VISION_1_INPUT))
        if val != last_val:
            # ★ 只有"从有到无/从无到有"才算一次变化。
            #   第一次读到不算（机器刚上电时本来就有个初值）。
            if last_val is not None:
                _val_changes += 1
            _c = "蓝=不良" if val else "绿=良品"
            _arm_trace(f"[视觉] VISION_1 -> {val}  ({_c})"
                       f"  (皮带3 已转 {time.time() - _belt3_t0:.1f}s)")
            last_val = val
        if val:
            # ---- 读到 True = 蓝色 = 不良 ----
            saw_ng = True
            # ★ 精确计时：量出"读到 NG"到"停皮带指令发出"中间花了多久。
            #   现场反馈"检测到不良皮带3 不能立即停止"，光看代码看不出慢在哪，
            #   所以把这一段时间打出来（毫秒级）。
            _t_see = time.time()
            modbus_client.write_coil(BELT_3_COIL, False)   # 立刻停皮带，等推杆
            _t_cmd = time.time()
            _belt3_stopped = True
            print(f"★ 视觉读到 True（蓝色 = 不良）→ 停皮带3"
                  f"（皮带3 共转 {_t_see - _belt3_t0:.2f}s，"
                  f"从读见到停皮带指令 {(_t_cmd - _t_see) * 1000:.0f}ms）")
            # ★ 这里【不 break】，靠 while 的条件 (not saw_ng) 自然退出。
            #   为什么：break 会立刻跳出，而"料到视觉位"和"皮带到停止点"
            #   可能正好挤在同一次循环里。不 break 的话，下一轮条件判断
            #   会再读一次（虽然不执行循环体，但已经拿到结论了），
            #   避免边界情况漏判。
        else:
            # ---- 读到 False ----
            #   ⚠ False 可能是"绿料经过"，也可能是"根本没有料"。
            #      所以这里【只记录】，不急着下结论 —— 真正的良品判定在循环外面，
            #      而且要配合"电平变化过"才算数。
            if not _belt3_stopped:
                saw_ok = True
        # ★ 皮带3 转够时间了就先停（料要停在推杆够得着的位置）
        if time.time() > _belt3_deadline and not _belt3_stopped:
            _t_cmd = time.time()
            modbus_client.write_coil(BELT_3_COIL, False)
            _belt3_stopped = True
            print(f"  [belt3] 到运行上限 {BELT3_RUN_TIME}s（实测 "
                  f"{_t_cmd - _belt3_t0:.2f}s），先停皮带3，继续等视觉结果")
            # ★★★ 2026-09-28 修正：停皮带后【不退出循环】，继续看到超时 ★★★
            #   原来这里只在 VISION_STOP_SETTLE(0.3s) 内再看一眼，然后 break。
            #   但料被拦停后可能还要一会儿才滑到视觉位 —— 0.3 秒根本不够，
            #   而这段时间读到的 False 被当成了"绿料"，于是蓝料被判成良品、
            #   皮带不停、推杆不推，直接进了良品仓。
            #   现在：这里什么都不做，让 while 继续转 —— 它会一直看到
            #         "读到 True"（有结论）或者"等满超时"（时间到）。
            #   ★ 注意：停皮带后读到的 False 不能再计入 saw_ok（上面已经拦住了）
        time.sleep(0.05)

    # ★★★ 三分类判定（2026-09-28）★★★
    #   良品 / 不良 / 漏料 —— 三种都要计数，良率才算得准。
    _final_val = bool(modbus_client.read_input(VISION_1_INPUT))
    # 判"到底有没有料经过"：读过 True，或者电平至少变过一次
    _saw_piece = saw_ng or (_val_changes >= 1)

    if saw_ng:
        # ================= 不良（蓝色）=================
        time.sleep(VISION_STOP_SETTLE)                 # 停稳再推，避免料还在滑
        modbus_client.write_coil(PUSHER_COIL, True)    # 推杆推出
        time.sleep(PUSHER_PUSH_TIME)
        modbus_client.write_coil(PUSHER_COIL, False)   # 推杆收回
        time.sleep(PUSHER_BACK_TIME)
        is_ok = False
        verdict = "不良"
        print(f"判定：不良（蓝色） | 电平变化 {_val_changes} 次")
    elif _saw_piece:
        # ================= 良品（绿色）=================
        is_ok = True
        verdict = "良品"
        print(f"判定：良品（绿色） | 电平变化 {_val_changes} 次"
              f" | 皮带3 共转 {time.time() - _belt3_t0:.1f}s")
        time.sleep(BELT3_PASS_TIME)                     # 让料走离视觉位再停
        modbus_client.write_coil(BELT_3_COIL, False)
    else:
        # ================= 漏料 =================
        #  说明：VISION_1 全程一直是同一个值、从没变过，
        #        也没读到过 True —— 无法确认有料经过，判为漏料。
        #        ★ 漏料也算一件，计入总数（不然良率会虚高）。
        is_ok = False
        verdict = "漏料"
        print(f"★ 判定：漏料 | 全程电平未变（最终值 {_final_val}）"
              f" | 皮带3 共转 {time.time() - _belt3_t0:.1f}s")
        modbus_client.write_coil(BELT_3_COIL, False)

                # ====== 步骤6: 返回结果 ======
    _mark_step("step5")         # 本件结束 → 回到空闲
    stations_passed[4] = is_ok          # 工位4 的判定就是视觉结果

    # ★ 返回值：判定结果、分步耗时、各工位通过情况、三分类结论
    return is_ok, step_times, stations_passed, verdict
    


# ========== LLM 线长（决策者） ==========
def _llm_decision_to_human(decision, assessment, actions, adjustments,
                           cycle_before, cycle_after, verdict_counts,
                           overall_yield, efficiency_ppm):
    """★ 把 LLM 的 JSON 决策翻译成【人话】（2026-09-28）

    为什么不让模型直接说人话：
      4B 模型输出自由文本时容易跑偏、幻觉、不说重点。
      而它输出 JSON 很稳（实测 3/3）。所以：
        · 让模型负责【判断】（它的强项）
        · 让它按固定 JSON 格式回来
        · 由这里把结构化结果翻译成人话（这样措辞永远可控）

    返回两行文本：(摘要行, 详情行)
    """
    # ---------- 第一行：结论 ----------
    mood = {
        "正常": "产线正常",
        "需要优化": "产线需要优化",
        "异常": "产线异常",
    }.get(str(assessment), f"产线状态：{assessment}")

    # ---------- 第二行：判断依据 + 动作 + 调整 ----------
    bits = []

    # 生产数据
    vc = verdict_counts or {}
    tot = sum(vc.values()) if vc else 0
    if tot:
        bits.append(f"已生产 {tot} 件（良品 {vc.get('良品', 0)}、"
                    f"不良 {vc.get('不良', 0)}、漏料 {vc.get('漏料', 0)}）")
    bits.append(f"良率 {overall_yield}%")
    bits.append(f"效率 {efficiency_ppm} 件/分")

    # 动作翻译
    act_cn = {
        "rotate": "让转盘转一位",
        "alarm_on": "打开报警灯",
        "alarm_off": "关闭报警灯",
        "stop": "停线",
        "continue": "继续生产",
    }
    if actions:
        names = [act_cn.get(a, a) for a in actions]
        # "继续生产"是最常见的、没信息量的动作，放最后且不重复说
        bits.append("动作：" + "、".join(names))

    # 节拍调整（说清楚"从多少改到多少"，以及为什么）
    if cycle_after is not None and cycle_before is not None \
            and abs(cycle_after - cycle_before) >= 0.05:
        direction = "压快" if cycle_after < cycle_before else "放慢"
        bits.append(f"节拍{direction}：{cycle_before}s → {cycle_after}s")
    elif adjustments and "cycle_time" in adjustments:
        bits.append(f"节拍维持 {cycle_before}s（建议值 {adjustments['cycle_time']}s 与当前接近）")

    return mood, "；".join(bits)


def _update_llm_label(app, mood, detail):
    """把两行文本写到 GUI 的 LLM 决策栏（失败不影响产线）"""
    try:
        app.update_data(
            production_count=production_count,
            target=target,
            station_stats=station_stats,
            llm_status="工作中" if llm_running else "待命",
            ai_score=governance.get_status()["ai_score"],
            alarm=modbus_client.get_coil(ALARM_COIL),
            cycle=cycle_count,
            llm_decision=f"{mood}｜{detail}",
        )
    except Exception as e:
        print("刷新 LLM 显示失败:", e)


def parse_production_input(text):
    """用LLM解析用户输入的产量目标"""
    prompt = f"""你是一个3C组装岛调度系统。
你的任务是从人类的指令中，提取出需要生产的目标数量。
指令："{text}"
请输出一个 JSON 对象，包含键 "target" (整数)。
不要输出任何其他解释文字。
示例: {{"target": 50}}
"""
    try:
        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }
        response = requests.post(LLM_BASE_URL, json=payload, timeout=60)
        response.raise_for_status()
        decision = json.loads(response.json()["response"])
        return int(decision.get("target", 0))
    except Exception as e:
        print("LLM产量解析失败，默认目标0:", e)
        return 0


def run_llm_line_leader(llm, event_manager, governance, modbus_client, station_stats, target, alarm_on, dashboard_app):
    """LLM 线长：分析产线状态并做出决策"""
    global llm_running, PRODUCTION_CYCLE_TIME

    # 双保险：调试期间 LLM_ENABLED=False 时直接返回，绝不去改 PRODUCTION_CYCLE_TIME
    if not LLM_ENABLED:
        llm_running = False
        return

    try:
        recent_events = event_manager.get_recent_events(limit=20)

        # 构建产线状态摘要给 LLM
        status_lines = []
        for sid, s in station_stats.items():
            status_lines.append(
                f"  工位{sid}({s['name']}): 通过{s['ok']}/{s['total']} 良率{s['yield_pct']}%"
            )
        status_summary = "\n".join(status_lines)

        # 计算总体良率和效率
        total_ok = sum(s["ok"] for s in station_stats.values())
        total_all = sum(s["total"] for s in station_stats.values())
        overall_yield = round(total_ok / total_all * 100, 1) if total_all > 0 else 100.0

        elapsed_min = max((time.time() - start_time) / 60, 0.1)
        efficiency_ppm = round(production_count / elapsed_min, 1)

        prompt = f"""你是3C组装岛的线长。当前生产状态：

产量: {production_count}/{target}  报警: {"是" if alarm_on else "否"}  AI评分: {governance.get_status()['ai_score']}

各工位:
{status_summary}

总体良率: {overall_yield}%  效率: {efficiency_ppm} 件/分钟  当前节拍: {PRODUCTION_CYCLE_TIME}秒

近期事件:
{json.dumps(recent_events, ensure_ascii=False, indent=2)}

请分析产线状态，输出一个 JSON 决策（不要输出其他文字）:
{{
  "assessment": "正常/需要优化/异常",
  "actions": [
    // "rotate", "alarm_on", "alarm_off", "stop", "continue"
  ],
  "adjustments": {{
    // 可选: 调整生产节拍(秒)，范围1.0~10.0
    // "cycle_time": 2.5
  }}
}}
"""

        payload = {
            "model": LLM_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False
        }
        response = requests.post(LLM_BASE_URL, json=payload, timeout=60)
        response.raise_for_status()
        decision = json.loads(response.json()["response"])

        actions = decision.get("actions", [])
        assessment = decision.get("assessment", "未知")
        adjustments = decision.get("adjustments", {})

        print(f"\n--- LLM 线长评估: {assessment} ---")
        print(f"    决策: {actions}")
        if adjustments:
            print(f"    调整: {adjustments}")

        # ★ 记下调整前的节拍（人话总结里要说"从多少改到多少"）
        _cycle_before = PRODUCTION_CYCLE_TIME

        # 应用节拍调整（★ 2026-09-28 加了护栏）
        if "cycle_time" in adjustments:
            try:
                want = float(adjustments["cycle_time"])
            except (TypeError, ValueError):
                want = None
                print(f"    ★ LLM 给的 cycle_time 不是数字: {adjustments['cycle_time']!r}，忽略")

            if want is not None:
                # 护栏①：单次调整幅度限制（4B 模型有随机性，不能让它一步调飞）
                delta = want - PRODUCTION_CYCLE_TIME
                if abs(delta) > LLM_CYCLE_MAX_STEP:
                    want = PRODUCTION_CYCLE_TIME + (
                        LLM_CYCLE_MAX_STEP if delta > 0 else -LLM_CYCLE_MAX_STEP)
                    print(f"    （LLM 想调到 {adjustments['cycle_time']}s，"
                          f"超过单次上限 ±{LLM_CYCLE_MAX_STEP}s，已收敛到 {want:.1f}s）")
                # 护栏②：硬夹到允许区间
                want = max(LLM_CYCLE_MIN, min(LLM_CYCLE_MAX, want))

                if abs(want - PRODUCTION_CYCLE_TIME) >= 0.1:   # 变化太小就不动
                    old_c = PRODUCTION_CYCLE_TIME
                    PRODUCTION_CYCLE_TIME = round(want, 1)
                    event_manager.add_event(
                        "CYCLE_ADJUST",
                        f"节拍 {old_c}s → {PRODUCTION_CYCLE_TIME}s（LLM 决策）")
                    print(f"    节拍已调整: {old_c}s → {PRODUCTION_CYCLE_TIME}s")
                else:
                    print(f"    LLM 建议 {want:.1f}s，与当前 {PRODUCTION_CYCLE_TIME}s 相差不大，不调整")

        # ★ 更新仪表盘 LLM 决策 —— 翻译成人话（2026-09-28）
        #   原来显示的是 "需要优化 → continue | 调整: {'cycle_time': 2.5}"，
        #   又长又难懂。现在翻译成：
        #       "产线需要优化｜已生产 24 件（良品 18、不良 5、漏料 1）；
        #        良率 75.0%；效率 1.2 件/分；继续生产；节拍压快：3.0s → 2.5s"
        _mood, _detail = _llm_decision_to_human(
            decision, assessment, actions, adjustments,
            cycle_before=_cycle_before, cycle_after=PRODUCTION_CYCLE_TIME,
            verdict_counts=verdict_counts,
            overall_yield=overall_yield, efficiency_ppm=efficiency_ppm)
        decision_text = f"{_mood}｜{_detail}"
        print(f"    → 人话总结: {decision_text}")
        dashboard_app.update_data(
            production_count=production_count,
            target=target,
            station_stats=station_stats,
            llm_status="工作中" if llm_running else "待命",
            ai_score=governance.get_status()["ai_score"],
            alarm=modbus_client.get_coil(ALARM_COIL),
            cycle=cycle_count,
            last_result=None,
            llm_decision=decision_text,
            verdict_counts=dict(verdict_counts),
        )
        # 这条也进事件日志栏（方便回看 LLM 每次说了什么）
        event_manager.add_event("LLM_DECISION", decision_text)

        # 执行 LLM 决策
        for action in actions:
            match action:
                case "rotate":
                    modbus_client.write_coil(TABLE_ROTATE_COIL, True)
                    time.sleep(TABLE_INDEX_TIME)
                    modbus_client.write_coil(TABLE_ROTATE_COIL, False)
                    event_manager.add_event("TABLE_INDEX", "转盘旋转到下一工位")
                case "alarm_on":
                    modbus_client.write_coil(ALARM_COIL, True)
                    event_manager.add_event("ALARM_ON", "蜂鸣器报警")
                case "alarm_off":
                    modbus_client.write_coil(ALARM_COIL, False)
                    event_manager.add_event("ALARM_OFF", "蜂鸣器关闭")
                case "stop":
                    stop_rotary_table(modbus_client)
                    event_manager.add_event("LINE_STOP", "LLM 线长执行停线")
                case "continue":
                    event_manager.add_event("LINE_CONTINUE", "LLM 线长决定继续生产")

        # 基于良率和效率评分，而不是简单看 stop
        governance.evaluate(overall_yield, efficiency_ppm)

    except Exception as e:
        print("LLM线长决策错误:", e)
    llm_running = False


# ============================================================================
#  以下是"脚本直接跑"时才执行的初始化与启动代码
#  （本文件被 import 时不会执行到下面这些）
# ============================================================================

# ======== 初始化：各个功能模块的对象 ========
statistics = FactoryStatistics()     # 产量统计（目前主流程没用到，历史遗留）
event_manager = EventManager()       # 事件管理：add_event() 会往控制台打 [EVENT]

print("")
print("=== 3C 组装岛 ===")
print("请输入今日产量目标")
print("")

import requests

user_input = input("请输入产量: ")            # 等你在控制台输入产量目标
target = parse_production_input(user_input)   # ★ 注意：这个函数名有歧义——
                                              #   它其实只是把输入转成整数，
                                              #   并不调用 LLM。看函数定义就明白。
modbus_client = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)   # 建客户端对象（还没连）

# 写入目标产量到 PLC 寄存器（给 Factory IO 那边看，纯记录用）
modbus_client.write_register(TARGET_PRODUCTION_REG, target)
print(f"\n目标产量: {target} 个\n")

# ======== 连接 ========
connected = modbus_client.connect()
if not connected:
    print("PLC连接失败")
    exit()
print("PLC连接成功\n")

# ========== 全复位：清除 Factory IO 缓存残留 ==========
# 背景：Factory IO 会记住上一次运行的状态，程序还没启动某些工位就会自己动。
#       所以启动前把所有输出线圈清 0、所有机械臂模拟量写 0。
#       ★ 如果你在 Factory IO 里手动改过状态，跑程序前也应该先点一次 Reset。
print("执行全复位...")
# 把所有输出线圈（皮带/转盘/夹爪/推杆/报警）统统写 False
for coil in [BELT_0_COIL, BELT_2_COIL, BELT_3_COIL,
             TABLE_A_ROLL_P_COIL, TABLE_A_ROLL_N_COIL, TABLE_A_TURN_COIL,
             TABLE_B_ROLL_P_COIL, TABLE_B_ROLL_N_COIL, TABLE_B_TURN_COIL,
             ARM1_GRAB_COIL, PUSHER_COIL, ALARM_COIL]:
    modbus_client.write_coil(coil, False)
# 把所有机械臂模拟量寄存器写 0（= 两个轴都回原点）
for reg in [ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG, PUSHER_SET_REG]:
    modbus_client.write_register(reg, 0)
time.sleep(1.0)              # 等这些复位动作生效
print("全复位完成\n")

# ========== 检测器 ==========
jam_detector = JamDetector()
efficiency_detector = EfficiencyDetector()
safety_manager = SafetyManager()
governance = AIGovernance()
llm = LLMManager()

# ========== 站台状态 ==========
station_stats = {}
for sid, scfg in STATIONS.items():
    station_stats[sid] = {
        "name": scfg["name"],
        "ok": 0,
        "total": 0,
        "yield_pct": 100.0,
    }

print("组装岛已启动，按 Ctrl+C 安全停止\n")

start_time = time.time()



# ========== 创建仪表盘窗口 ==========
app = DashboardApp()

# ★ 把事件流接到 GUI 日志栏（2026-09-28）
#   event_manager.add_event() 产生的每条事件，除了打控制台，
#   也会追加到仪表盘右下角的"事件日志"里。
event_manager.sink = app.log
app.log("系统启动 · 仪表盘就绪")


# ★★★ 人工介入回调（GUI 右上角面板 -> 产线）★★★
#  为什么走回调：dashboard 不能直接 import main（会循环依赖），
#  所以由 main 把函数挂上去，GUI 按钮点了就调这些函数。
def _ui_set_cycle(seconds):
    """人工设定节拍（秒）——GUI 面板"设定节拍"。"""
    global PRODUCTION_CYCLE_TIME
    try:
        v = float(seconds)
    except (TypeError, ValueError):
        return
    # 和 LLM 用同一套护栏，避免"人工能设、别处又拦掉"的不一致
    v = max(LLM_CYCLE_MIN, min(LLM_CYCLE_MAX, v))
    old = PRODUCTION_CYCLE_TIME
    PRODUCTION_CYCLE_TIME = round(v, 1)
    event_manager.add_event("MANUAL_CYCLE",
                            f"人工设定节拍 {old}s → {PRODUCTION_CYCLE_TIME}s")
    print(f"\n[人工] 节拍已设定: {old}s → {PRODUCTION_CYCLE_TIME}s\n")


def _ui_stop():
    """人工紧急停线——GUI 面板"紧急停线"。"""
    safety_manager.request_stop()
    # 立刻把设备停掉，不等主循环下一轮（安全第一）
    try:
        for coil in (BELT_0_COIL, BELT_2_COIL, BELT_3_COIL,
                     TABLE_A_ROLL_P_COIL, TABLE_A_ROLL_N_COIL, TABLE_A_TURN_COIL,
                     TABLE_B_ROLL_P_COIL, TABLE_B_ROLL_N_COIL, TABLE_B_TURN_COIL,
                     EMITTER_COIL):
            modbus_client.write_coil(coil, False)
        modbus_client.write_coil(ALARM_COIL, True)
    except Exception as e:
        print("人工停线时关设备出错:", e)
    print("\n" + "!" * 50)
    print("[人工] 紧急停线！产线已停止，点「恢复」才能继续")
    print("!" * 50 + "\n")


def _ui_resume():
    """人工恢复——GUI 面板"恢复"。"""
    safety_manager.clear_stop()
    safety_manager.clear_pause()
    try:
        modbus_client.write_coil(ALARM_COIL, False)
    except Exception:
        pass
    event_manager.add_event("MANUAL_RESUME", "人工恢复生产")
    print("\n[人工] 已恢复生产\n")


def _ui_pause():
    """人工暂停——件与件之间生效，不会把工件扔在半路。"""
    safety_manager.request_pause()
    print("\n[人工] 暂停请求已收到（当前件做完后停住）\n")


def _ui_continue():
    """人工继续——解除暂停。"""
    safety_manager.clear_pause()
    event_manager.add_event("MANUAL_CONTINUE", "人工继续生产")
    print("\n[人工] 已继续生产\n")


app.on_set_cycle = _ui_set_cycle
app.on_stop = _ui_stop
app.on_resume = _ui_resume
app.on_pause = _ui_pause
app.on_continue = _ui_continue
app.cycle_entry.delete(0, "end")
app.cycle_entry.insert(0, f"{PRODUCTION_CYCLE_TIME:.1f}")

# ★★★ 三分类计数器（2026-09-28）★★★
#   良品 / 不良 / 漏料 —— 三种都算一件，良率才有意义。
#   ★ 为什么"漏料"也要计入总数：
#       料根本没到视觉位，如果只统计"看到的那些"，良率会被算高。
#       实际损失必须体现出来，否则数字好看但不对。
verdict_counts = {"良品": 0, "不良": 0, "漏料": 0}


def _current_verdict_summary():
    """给 GUI / 日志用的一句话汇总"""
    ok_n = verdict_counts["良品"]
    ng_n = verdict_counts["不良"]
    miss_n = verdict_counts["漏料"]
    tot = ok_n + ng_n + miss_n
    yld = round(ok_n / tot * 100, 1) if tot else 0.0
    return (f"良品 {ok_n} / 不良 {ng_n} / 漏料 {miss_n}"
            f"（共 {tot} 件，良率 {yld}%）")


# ========== 生产线程 ==========
def production_loop():
    """★【主循环】跑在生产线程里，负责：调 produce_one、记产量、算统计、刷界面。

    和 produce_one 的分工：
      produce_one  只管"一件产品怎么走完 5 个工位"（纯动作，不记账）
      production_loop 管"做多少件、良率多少、什么时候收工"

    调产线时如果只是改动作节拍 → 改 produce_one；
    如果要改产量逻辑/统计口径 → 改这里。
    """
    # 声明这些是全局变量，函数里赋值会影响外面（不加 global 会变成局部变量）
    global running, production_count, cycle_count, llm_running, last_llm_analysis, table_position, task_done

    # 爬坡日志：把每一件的节拍和分步耗时攒起来，产量达标时写成 JSON 文件
    climb_log = []
    climb_start = time.time()      # 本件的起始时刻，用来算 cycle_time

    # 产量模式（无首件限制）：只要 running 还是 True 就一直循环
    while running:

        cycle_count += 1           # 主循环轮数 +1（含没生产的空转轮）

        # --- 生产一个产品 ---
        last_result = None         # 本件判定，先置空（界面用来决定工位4 填充色）
        if production_count < target:          # 还没做够目标件数才生产
            print(f"\n=== 第 {production_count + 1} 件 ===")
            # ★★ 调用核心流程。这一句就是"做一件产品"，
            #    里面的耗时决定整个节拍。返回四个值：
            #      last_result     本件是否良品（True/False）
            #      step_times      每步耗时（写进爬坡日志）
            #      stations_passed 各工位是否通过（更新统计用）
            #      verdict         ★ 三分类结论：良品 / 不良 / 漏料
            last_result, step_times, stations_passed, verdict = \
                produce_one(modbus_client)
            production_count += 1
            try:
                app.set_step(0)       # ★ 本件结束，仪表盘回到"空闲"
            except Exception:
                pass

            # ★ 三分类计数（2026-09-28）
            #   良品 / 不良 / 漏料 三种都要数，良率才有意义。
            #   ★ 漏料也计入总数 —— 不然"料根本没到"不会被算作损失，良率会虚高。
            if verdict == "良品":
                verdict_counts["良品"] += 1
            elif verdict == "不良":
                verdict_counts["不良"] += 1
            else:
                verdict_counts["漏料"] += 1

            # 更新各工位统计（GUI 良率 / LLM 分析都读这里）
            for sid, passed in stations_passed.items():
                st = station_stats.get(sid)      # 取出这个工位的统计字典
                if st is None:
                    continue                     # 没这个工位就跳过（防 KeyError）
                st["total"] += 1                 # 该工位过料数 +1
                if passed:
                    st["ok"] += 1                # 通过数 +1
                # ★ 顺便记下这个工位的三分类（只有成品检测工位有真实三态）
                if sid == 4:
                    if verdict == "良品":
                        st["ok_kind"] = st.get("ok_kind", 0) + 1
                    elif verdict == "不良":
                        st["ng_kind"] = st.get("ng_kind", 0) + 1
                    else:
                        st["miss_kind"] = st.get("miss_kind", 0) + 1
                # 良率 = 通过 / 总数。★ 注意分母是"过了这个工位的件数"，不是总产量
                st["yield_pct"] = round(st["ok"] / st["total"] * 100, 1)

            # 爬坡记录：一件一行，产量达标时整个列表写进 climb_log_N件.json
            cycle_elapsed = time.time() - climb_start   # 本件总耗时（含尾部等待）
            climb_log.append({
                "index": production_count,       # 第几件
                "cycle_time": round(cycle_elapsed, 2),  # 整节拍（秒）
                "is_ok": last_result,            # 本件是否良品（True/False）
                "verdict": verdict,              # ★ 三分类：良品/不良/漏料
                "steps": step_times,             # ★ 分步耗时，调产线主要看这个
                "timestamp": time.strftime("%H:%M:%S")
            })
            climb_start = time.time()            # 重置，开始算下一件
            print(f"   爬坡: 第{production_count}件 | 节拍{cycle_elapsed:.2f}s | {verdict}")
            print(f"         累计: {_current_verdict_summary()}")

            # 产品输出后，工位4恢复待命色
            app.update_data(
                production_count=production_count,
                target=target,
                station_stats=station_stats,
                llm_status="工作中" if llm_running else "待命",
                ai_score=governance.get_status()["ai_score"],
                alarm=modbus_client.get_coil(ALARM_COIL),
                cycle=cycle_count,
                last_result=(verdict == "良品"),  # ★ 界面按三分类上色
                cycle_time=cycle_elapsed,        # ★ 本件节拍（画趋势图）
                params=_current_params(),        # ★ 当前关键参数一览
                verdict_counts=dict(verdict_counts),   # ★ 三分类计数
            )
            # 记一条到 GUI 日志栏
            app.log(f"第{production_count}件完成 | 节拍 {cycle_elapsed:.1f}s | {verdict}"
                    f" | {_current_verdict_summary()}")
            # 节拍等待：每件之间固定歇一下。
            # ★ 这个值会被 LLM 改（所以调产线时要把 config.LLM_ENABLED 设为 False），
            #   默认值在 config.PRODUCTION_CYCLE_TIME（3.0 秒）
            time.sleep(PRODUCTION_CYCLE_TIME)

        # --- 产量完成收尾 ---
        if production_count >= target and not task_done:
            task_done = True
            stop_rotary_table(modbus_client)
            modbus_client.write_coil(ALARM_COIL, False)
            # 保存爬坡日志
            import json
            log_path = f"climb_log_{target}件.json"
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(climb_log, f, ensure_ascii=False, indent=2)
            print(f"\n爬坡日志已保存: {log_path}")
            event_manager.add_event("TASK_COMPLETE", f"产量达标 {production_count}/{target}")
            print(f"\n=== 产量达标 {production_count}/{target} 个，产线完成 ===")
            running = False
            break

        # --- 更新模拟量 ---
        modbus_client.write_register(ACTUAL_PRODUCTION_REG, production_count)
        # ★★★ 已删除"良率写 PLC"（2026-09-28）★★★
        #  原来这里是：
        #      for sid, s in station_stats.items():
        #          yield_val = int(s["yield_pct"] * 100)
        #          modbus_client.write_register(STATIONS[sid]["yield_reg"], yield_val)
        #
        #  为什么要删：
        #      config.STATIONS 里 yield_reg 原来是 0/1/2/3，而 0/1/2/3 正好是
        #      四个机械臂轴的设定点寄存器（ARM1_X/Z、ARM2_X/Z）。
        #      于是每做完一件，就把"良率 x100"当成电压写给机械臂：
        #          良率 100% -> 写 10000 -> 机械臂伸到极限
        #          良率  50% -> 写 5000  -> 机械臂走到一半
        #      表现就是"把所有机械臂动作代码都删了，机械臂还是自己跑到极限"。
        #
        #  现在良率【只写 GUI】（dashboard 读 station_stats），不再碰任何 PLC 寄存器。
        #  ⚠ 不要改写到 Input Register 或 Coil：
        #      Input Register 是只读的（Modbus 客户端不能写 3x 区）；
        #      Coil 是开关量，只有 True/False，装不下良率数值。

        jam_detector.update(False)  # modbus模式不检测卡堵
        jam_status = jam_detector.get_status()

        efficiency_detector.update(
            production_count / max((time.time() - start_time) / 60, 0.1)
        )
        efficiency_status = efficiency_detector.get_status()

        # --- 事件 ---
        if jam_detector.has_changed() and jam_status["is_blocked"]:
            event_manager.add_event("BLOCK_DETECTED", "转盘卡堵")
            modbus_client.write_coil(ALARM_COIL, True)

        if efficiency_detector.has_changed() and efficiency_status["low_efficiency"]:
            event_manager.add_event("LOW_EFFICIENCY", "产能下降")

        # --- 紧急停线 / 人工介入 ---
        safety_manager.evaluate(jam_status, {"push_timeout": False})
        safety_status = safety_manager.get_status()

        # ★★ 人工紧急停线（GUI 按钮）：一直停到人工点"恢复"为止。
        #    只报一次事件，不然每 0.1 秒刷一条会把日志刷爆。
        if safety_manager.manual_stop:
            if not getattr(production_loop, "_manual_stop_notified", False):
                production_loop._manual_stop_notified = True
                event_manager.add_event("MANUAL_STOP", "人工紧急停线（等待人工恢复）")
                print("\n! 人工停线：产线已停止，点「恢复」继续\n")
            stop_rotary_table(modbus_client)
            modbus_client.write_coil(ALARM_COIL, True)
            time.sleep(LOOP_INTERVAL)
            continue                      # ★ 卡在这里，不做任何生产动作
        production_loop._manual_stop_notified = False

        # ★★ 人工暂停：在"件与件之间"生效，不会把工件扔在半路
        if safety_manager.manual_pause:
            if not getattr(production_loop, "_manual_pause_notified", False):
                production_loop._manual_pause_notified = True
                event_manager.add_event("MANUAL_PAUSE", "人工暂停（当前件已做完）")
                print("\n|| 人工暂停：件与件之间停住，点「继续」恢复\n")
            time.sleep(LOOP_INTERVAL)
            continue
        production_loop._manual_pause_notified = False

        # 自动检测到的卡堵（原逻辑）
        if safety_status["emergency_stop"]:
            stop_rotary_table(modbus_client)
            print("! 紧急停线！转盘卡堵")

        # --- LLM 线长定时决策 ---
        # ★ LLM_ENABLED=False 时整段跳过：不调用模型、不改节拍。
        #   调试产线期间必须冻结，否则 LLM 会一直改 PRODUCTION_CYCLE_TIME，
        #   让"改一个变量看效果"失效。
        if not LLM_ENABLED:
            if not getattr(production_loop, "_llm_frozen_notified", False):
                production_loop._llm_frozen_notified = True
                print("\n[LLM] 已冻结（config.LLM_ENABLED=False），节拍固定为 "
                      f"{PRODUCTION_CYCLE_TIME} 秒，不再由 LLM 调整\n")
        else:
            current_time = time.time()
            if (
                current_time - last_llm_analysis > LLM_ANALYSIS_INTERVAL
                and not llm_running
            ):
                last_llm_analysis = current_time
                llm_running = True
                alarm_on = modbus_client.get_coil(ALARM_COIL)
                llm_thread = threading.Thread(
                    target=run_llm_line_leader,
                    args=(llm, event_manager, governance, modbus_client, station_stats, target, alarm_on, app)
                )
                llm_thread.daemon = True
                llm_thread.start()

                # --- 更新仪表盘 ---
        app.update_data(
            production_count=production_count,
            target=target,
            station_stats=station_stats,
            llm_status="工作中" if llm_running else "待命",
            ai_score=governance.get_status()["ai_score"],
            alarm=modbus_client.get_coil(ALARM_COIL),
            cycle=cycle_count,
            last_result=last_result,
        )

        time.sleep(LOOP_INTERVAL)

    # 生产结束，安全退出
    stop_rotary_table(modbus_client)
    modbus_client.close()
    print("\n组装岛已安全停止")


# ========== 启动【位置采样】线程 ==========
# 每 ARM_POS_POLL 秒把四个轴的实际位置写一行到 config.ARM_POS_TRACE_LOG。
# 用途：抓"机械臂什么时候、被哪个动作驱动到了极限"——
#       按点记录会漏掉动作之间的空档，而问题常常就出在空档里。
# 不需要时把 config.ARM_POS_TRACE 设为 False 即可。
if ARM_POS_TRACE:
    pos_thread = threading.Thread(target=_arm_pos_sampler, args=(modbus_client,), daemon=True)
    pos_thread.start()
    print(f"位置采样已启动：每 {ARM_POS_POLL}s 一次 → {ARM_POS_TRACE_LOG}\n")

def _current_params():
    """★ 给 GUI"当前参数"栏用的关键参数一览（只读，方便一眼看到现在用的值）。

    只列调产线时最常改的几个，不要列太多（面板放不下）。
    """
    return {
        "节拍等待": f"{PRODUCTION_CYCLE_TIME}s",
        "锁螺丝X": ARM1_X_TARGET,
        "锁螺丝Z(接触/放料)": f"{ARM1_Z_CONTACT}/{ARM1_Z_WORK}",
        "点胶X": ARM2_X_TARGET,
        "点胶Z": ARM2_Z_WORK,
        "回零前伸": f"{ARM_HOME_PRESTRETCH} ({ARM_HOME_SETTLE}s)",
        "转盘A进料/停稳": f"{TABLE_A_LOAD_WAIT}/{TABLE_A_REST}s",
        "皮带2走带": f"{BELT2_TRANSIT_WAIT}s",
        "转盘B推料/稳定": f"{TABLE_B_PUSH_WAIT}/{TABLE_B_SETTLE}s",
        "视觉等待": f"{VISION_WAIT_TIMEOUT}s",
        "LLM": "已激活" if LLM_ENABLED else "已冻结",
    }


# ========== 启动生产线程 ==========
prod_thread = threading.Thread(target=production_loop, daemon=True)
prod_thread.start()

# ========== 启动仪表盘窗口（主线程） ==========
app.root.mainloop()
