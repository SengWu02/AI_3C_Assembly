import time
import threading
import json
import signal
import random

from config import *

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
running = True
task_done = False           # 产量完成标志
llm_running = False
last_llm_analysis = time.time()
table_position = 0          # 当前工位 0-3
production_count = 0
cycle_count = 0
start_time = None            # 生产开始时间

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
    """轮询等待 Input 达到目标值，超时返回 False"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if modbus_client.read_input(addr) == target:
                return True
        except Exception:
            # 读取失败时短暂等待并重试
            pass
        time.sleep(interval)
    return False


def _wait_move_done(modbus_client, moving_addr, timeout=None):
    """等机械臂 Moving 信号从 True 落到 False（= 动作做完了）。

    返回 True 表示信号可用并等到了；False 表示超时或信号没响应，
    调用方应退回盲等。两个 Moving 地址传 None 时直接返回 False。
    """
    if moving_addr is None:
        return False
    if timeout is None:
        timeout = ARM_MOVE_TIMEOUT
    start = time.time()
    while time.time() - start < timeout:
        try:
            if not modbus_client.read_input(moving_addr):
                return True
        except Exception:
            pass
        time.sleep(0.02)
    return False


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
    prev = _ARM_CMD.get(reg, 0)
    modbus_client.write_register(reg, value)
    _ARM_CMD[reg] = value
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
            wait = fallback          # 默认：与现场已验证的固定等待完全一致
        time.sleep(wait)
        return False

    # 等信号抬起来：机构起步需要一点时间，太早判断会把"还没动"当成"已经到"
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

    if not rose:
        _DEAD_SIGNALS.add(moving_addr)
        if ARM_MOVE_DEBUG:
            print(f"      [arm] input {moving_addr} 信号不响应，本次运行起全部改用盲等")
        time.sleep(fallback)
        return False

    if _wait_move_done(modbus_client, moving_addr, timeout):
        return True

    _DEAD_SIGNALS.add(moving_addr)
    if ARM_MOVE_DEBUG:
        print(f"      [arm] input {moving_addr} 等超时，本次运行起全部改用盲等")
    time.sleep(fallback)
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
    if ARM_MOVE_DEBUG:
        print(f"      [arm] 回原点：前伸/下探 {ARM_HOME_PRESTRETCH} → 归零 ({tag})")

    # 1) 轻微前伸/下探（X 往外、Z 往下），把机构从原点"唤醒"
    modbus_client.write_register(x_reg, ARM_HOME_PRESTRETCH)
    modbus_client.write_register(z_reg, ARM_HOME_PRESTRETCH)
    _ARM_CMD[x_reg] = ARM_HOME_PRESTRETCH
    _ARM_CMD[z_reg] = ARM_HOME_PRESTRETCH

    # 2) 保持一小段，确认机构真的动了
    time.sleep(ARM_HOME_PRESTRETCH_HOLD)

    # 3) 同时回零，然后等够稳定时间
    modbus_client.write_register(x_reg, 0)
    modbus_client.write_register(z_reg, 0)
    _ARM_CMD[x_reg] = 0
    _ARM_CMD[z_reg] = 0
    time.sleep(settle)


def _table_wait_limit(modbus_client, addr, target, timeout=8.0, what=""):
    """等转盘限位到位。到了返回 True，超时返回 False（并打印出来，便于定位）。"""
    if _wait_input(modbus_client, addr, target, timeout=timeout):
        return True
    print(f"      [table] 限位未到位: {what} (input {addr} != {target})")
    return False


def _table_index(modbus_client, turn_coil, limit_addr, timeout=8.0, what=""):
    """转盘转 90°（转到另一个限位位）。

    转盘是 Monostable 类型：写 True 触发动作，限位到位后要写回 False 释放。
    原来写成 True → 盲等 1s → False，1 秒根本不够转完，所以每次都走 8s 超时兜底。
    """
    modbus_client.write_coil(turn_coil, True)
    ok = _table_wait_limit(modbus_client, limit_addr, True, timeout, what)
    modbus_client.write_coil(turn_coil, False)
    return ok


def produce_one(modbus_client):
    """执行一次完整生产循环（仅动作模板，不记账）"""

    is_ok = False
    step_times = {}
    _step_start = time.time()

    # 本件在各工位是否走通（工位编号见 config.STATIONS）
    # 说明：目前只有工位4（成品检测）有真实视觉判定；工位1~3 按"动作走完即通过"记。
    # 把统计更新放回这里，是因为之前 produce_one 从"2参数带统计"改成"1参数"时，
    # 把统计那几行一起删掉了，导致 GUI/LLM 永远看到 0/0、良率100%。
    stations_passed = {1: False, 2: False, 3: False, 4: False}

    def _mark_step(name):
        """记录当前步骤耗时"""
        step_times[name] = round(time.time() - _step_start, 2)

    # ====== 步骤1: 转盘A接料 + 回0° + 送到皮带2 ======
    print(">>> 步骤1: 转盘A转90°接料 → 回0° → 送料到皮带2")
    _step_start = time.time()

    # 转盘A → 90°（接料位）
    _table_index(modbus_client, TABLE_A_TURN_COIL, TABLE_A_LIMIT_90_INPUT, what="A→90°接料")

    # 开滚轮+皮带1+发料，送料进转盘中心
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)
    modbus_client.write_coil(BELT_0_COIL, True)
    modbus_client.write_coil(EMITTER_COIL, True)
    time.sleep(3.5)  # 等转盘把料转到中心

    # 停滚轮+皮带1+发料
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)
    modbus_client.write_coil(BELT_0_COIL, False)
    modbus_client.write_coil(EMITTER_COIL, False)
    time.sleep(1.0)  # 等料在中心稳定

    # 转盘A → 0°（送料位）
    # ★ 这里原来是 write_coil(TABLE_A_TURN_COIL, True)，与上面第 1 步写成同一个值，
    #   结果又下发了一次 90° 命令——这就是"转盘转了又转、回零回不去"的根因。
    _table_index(modbus_client, TABLE_A_TURN_COIL, TABLE_A_LIMIT_0_INPUT, what="A→0°送料")

    # 开滚轮+皮带2同时送料
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)
    modbus_client.write_coil(BELT_2_COIL, True)
    # 等待料到位（漫反射传感器）
    if not _wait_input(modbus_client, ARM1_DETECT_INPUT, True, timeout=5.0):
        time.sleep(1.5)  # 超时保底（原3.0）
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)
    modbus_client.write_coil(BELT_2_COIL, False)
    time.sleep(0.3)

    
                # ====== 步骤2: 机械臂1搬运到转盘B ======
    print(">>> 步骤2: 机械臂1搬运到转盘B")
    _mark_step("step1")
    stations_passed[1] = True          # 步骤1 走完 = 视觉检测工位通过
    _step_start = time.time()
    
    # ===== 机械臂2（锁螺丝位）回零 =====
    _arm_home(modbus_client, ARM1_X_REG, ARM1_Z_REG,
              ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT, tag="取料前")

    # ===== 机械臂2 取料 =====
    modbus_client.write_coil(ARM1_GRAB_COIL, True)                     # 先开吸嘴
    time.sleep(ARM_GRAB_SETTLE)                                        # 等吸稳
    # 不再给每个动作手写 fallback：等待时长统一由行程模型按实测值算
    # （X 1.70 / Z 0.95 满行程），手写的固定值只会盖掉更准的模型。
    _arm_move(modbus_client, ARM1_Z_REG, 8500, ARM2_MOVING_Z_INPUT)    # Z下接触零件
    _arm_move(modbus_client, ARM1_Z_REG, 0,    ARM2_MOVING_Z_INPUT)    # Z上提起
    _arm_move(modbus_client, ARM1_X_REG, 10000, ARM2_MOVING_X_INPUT)   # X伸到转盘B上方

    # ===== 机械臂2 下料 =====
    _arm_move(modbus_client, ARM1_Z_REG, 8400, ARM2_MOVING_Z_INPUT)    # Z下放料
    modbus_client.write_coil(ARM1_GRAB_COIL, False)                    # 松吸嘴
    time.sleep(ARM_GRAB_SETTLE)

    # ===== 机械臂2 干完活回原点 =====
    # 和"取料前"用同一套动作（前伸/下探 → 归零）。做完工作就回原点，
    # 不要停在伸展位——停在伸展位就是"下个周期把极限当原点"的直接来源。
    _arm_home(modbus_client, ARM1_X_REG, ARM1_Z_REG,
              ARM2_MOVING_X_INPUT, ARM2_MOVING_Z_INPUT, tag="锁螺丝完成")
    

                # ======步骤3： 点胶工位:机械臂2点胶 ======
    print(">>> 步骤3： 点胶工位:机械臂2点胶")
    _mark_step("step2")
    stations_passed[2] = True          # 步骤2 走完 = 锁螺丝工位通过
    _step_start = time.time()  
    # ===== 机械臂0（点胶位）回零 =====
    _arm_home(modbus_client, ARM2_X_REG, ARM2_Z_REG,
              ARM0_MOVING_X_INPUT, ARM0_MOVING_Z_INPUT, tag="点胶前")

    # ===== 机械臂0 点胶 =====
    _arm_move(modbus_client, ARM2_X_REG, 5000, ARM0_MOVING_X_INPUT)    # X伸到点胶位
    # Z 下到点胶高度 + 停留。原代码是一段 2.0s 盲等（Z下和停留混在一起），
    # 这里拆成两段，合计仍是 2.0s（1.6 + 0.4），一点没省也没多。
    _arm_move(modbus_client, ARM2_Z_REG, 8400, ARM0_MOVING_Z_INPUT,
              fallback=ARM_DISPENSE_TRAVEL)                            # Z下到点胶高度
    time.sleep(ARM_DISPENSE_DWELL)                                     # 点胶停留

    # ===== 机械臂0 干完活回原点 =====
    _arm_home(modbus_client, ARM2_X_REG, ARM2_Z_REG,
              ARM0_MOVING_X_INPUT, ARM0_MOVING_Z_INPUT, tag="点胶完成")

    # 转盘B → 90°（点胶位）
    # 原来这里是 True → 等 8s 限位 → 兜底 sleep(5.0)，是全文件最后一处写死的大等待。
    # 换成限位驱动：到位就立刻释放，不再白等。
    _table_index(modbus_client, TABLE_B_TURN_COIL, TABLE_B_LIMIT_90_INPUT, what="B→90°点胶")


                # ====== 步骤4: 转盘B送料到皮带3（右视觉位） ======
    print(">>> 步骤4: 转盘B送料到皮带3")
    _mark_step("step3")
    stations_passed[3] = True          # 步骤3 走完 = 点胶工位通过
    _step_start = time.time()
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, True)
    time.sleep(1.5)
    modbus_client.write_coil(BELT_3_COIL, True)
    time.sleep(1.5)
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, False)
    time.sleep(0.5)  # 等料完全到视觉位



                        # ====== 步骤5: 右侧视觉检测 ======
    print(">>> 步骤5: 视觉检测 (VISION_1)")
    _mark_step("step4")
    _step_start = time.time()
   
    # 等待视觉触发（当前约定：True = OK）
    # ⚠ 这个方向还没在现场确认过：现场视觉是 NC 逻辑时 True 其实是 NG。
    #   先确认"料到底有没有走到视觉1"，再决定要不要反过来（见复盘报告 §5）。
    print(f"等待视觉触发（超时{VISION_WAIT_TIMEOUT}秒）...")
    start = time.time()
    detected = False
    while time.time() - start < VISION_WAIT_TIMEOUT:
        val = modbus_client.read_input(VISION_1_INPUT)
        if val == True:
            print("视觉触发！读到 True（当前约定=OK）")
            detected = True
            break
        time.sleep(0.05)

    if detected:
        print("停皮带3，推杆推出...")
        modbus_client.write_coil(BELT_3_COIL, False)
        modbus_client.write_coil(PUSHER_COIL, True)
        time.sleep(1)
        print("推杆收回...")
        modbus_client.write_coil(PUSHER_COIL, False)
        is_ok = True
    else:
        print("超时未触发，当前视觉值:", modbus_client.read_input(VISION_1_INPUT))
        modbus_client.write_coil(BELT_3_COIL, False)
        is_ok = False

                # ====== 步骤6: 返回结果 ======
    _mark_step("step5")
    stations_passed[4] = is_ok          # 工位4 的判定就是视觉结果

    return is_ok, step_times, stations_passed
    


# ========== LLM 线长（决策者） ==========
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

        # 应用节拍调整
        if "cycle_time" in adjustments:
            new_cycle = float(adjustments["cycle_time"])
            if 1.0 <= new_cycle <= 10.0:
                PRODUCTION_CYCLE_TIME = new_cycle
                event_manager.add_event("CYCLE_ADJUST", f"节拍调整为{new_cycle}秒")
                print(f"    节拍已调整为 {new_cycle} 秒")

        # 更新仪表盘 LLM 决策
        decision_text = f"{assessment} → {', '.join(actions) if actions else '无操作'}"
        if adjustments:
            decision_text += f" | 调整: {adjustments}"
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
        )

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


# ======== 初始化 ========
statistics = FactoryStatistics()
event_manager = EventManager()

print("")
print("=== 3C 组装岛 ===")
print("请输入今日产量目标")
print("")

import requests

user_input = input("请输入产量: ")
target = parse_production_input(user_input)
modbus_client = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)

# 写入目标产量到 PLC 寄存器
modbus_client.write_register(TARGET_PRODUCTION_REG, target)
print(f"\n目标产量: {target} 个\n")

# ======== 连接 ========
connected = modbus_client.connect()
if not connected:
    print("PLC连接失败")
    exit()
print("PLC连接成功\n")

# ========== 全复位：清除 Factory IO 缓存残留 ==========
print("执行全复位...")
for coil in [BELT_0_COIL, BELT_2_COIL, BELT_3_COIL,
             TABLE_A_ROLL_P_COIL, TABLE_A_ROLL_N_COIL, TABLE_A_TURN_COIL,
             TABLE_B_ROLL_P_COIL, TABLE_B_ROLL_N_COIL, TABLE_B_TURN_COIL,
             ARM1_GRAB_COIL, PUSHER_COIL, ALARM_COIL]:
    modbus_client.write_coil(coil, False)
for reg in [ARM1_X_REG, ARM1_Z_REG, ARM2_X_REG, ARM2_Z_REG, PUSHER_SET_REG]:
    modbus_client.write_register(reg, 0)
time.sleep(1.0)
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


# ========== 生产线程 ==========
def production_loop():
    global running, production_count, cycle_count, llm_running, last_llm_analysis, table_position, task_done

    # 爬坡日志
    climb_log = []
    climb_start = time.time()

    # 产量模式（无首件限制）
    while running:

        cycle_count += 1

        # --- 生产一个产品 ---
        last_result = None
        if production_count < target:
            print(f"\n=== 第 {production_count + 1} 件 ===")
            last_result, step_times, stations_passed = produce_one(modbus_client)
            production_count += 1

            # 更新各工位统计（GUI 良率 / LLM 分析都读这里）
            for sid, passed in stations_passed.items():
                st = station_stats.get(sid)
                if st is None:
                    continue
                st["total"] += 1
                if passed:
                    st["ok"] += 1
                st["yield_pct"] = round(st["ok"] / st["total"] * 100, 1)

            # 爬坡记录
            cycle_elapsed = time.time() - climb_start
            climb_log.append({
                "index": production_count,
                "cycle_time": round(cycle_elapsed, 2),
                "is_ok": last_result,
                "steps": step_times,
                "timestamp": time.strftime("%H:%M:%S")
            })
            climb_start = time.time()
            print(f"   爬坡: 第{production_count}件 | 节拍{cycle_elapsed:.2f}s | {'OK' if last_result else 'NG'}")

            # 产品输出后，工位4恢复待命色
            app.update_data(
                production_count=production_count,
                target=target,
                station_stats=station_stats,
                llm_status="工作中" if llm_running else "待命",
                ai_score=governance.get_status()["ai_score"],
                alarm=modbus_client.get_coil(ALARM_COIL),
                cycle=cycle_count,
                last_result=None,
            )
            # 节拍等待
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
        for sid, s in station_stats.items():
            yield_val = int(s["yield_pct"] * 100)
            modbus_client.write_register(STATIONS[sid]["yield_reg"], yield_val)

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

        # --- 紧急停线 ---
        safety_manager.evaluate(jam_status, {"push_timeout": False})
        safety_status = safety_manager.get_status()

        if safety_status["emergency_stop"]:
            event_manager.add_event("EMERGENCY_STOP", "系统紧急停线")
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


# ========== 启动生产线程 ==========
prod_thread = threading.Thread(target=production_loop, daemon=True)
prod_thread.start()

# ========== 启动仪表盘窗口（主线程） ==========
app.root.mainloop()
