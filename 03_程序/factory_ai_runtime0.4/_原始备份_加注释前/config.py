# ========== 通信 ==========
MODBUS_HOST = "192.168.102.1"
MODBUS_PORT = 502
PROTOCOL = "modbus"       # virtual 或 modbus

# ========== Coil 输出（Python→Factory IO）==========
EMITTER_COIL = 0            # 发料器
BELT_0_COIL = 1             # 皮带机0（来料）
BELT_2_COIL = 2             # 皮带机2（过渡）
BELT_3_COIL = 3             # 皮带机3（出料）
TABLE_A_ROLL_P_COIL = 4     # 转盘A 滚轮正转
TABLE_A_ROLL_N_COIL = 5     # 转盘A 滚轮反转
TABLE_A_TURN_COIL = 6       # 转盘A 旋转
TABLE_B_ROLL_P_COIL = 7     # 转盘B 滚轮正转
TABLE_B_ROLL_N_COIL = 8     # 转盘B 滚轮反转
TABLE_B_TURN_COIL = 9       # 转盘B 旋转
ARM1_Z_COIL = 10            # 机械臂1 Z轴（锁螺丝/搬运）
ARM1_X_COIL = 11            # 机械臂1 X轴
ARM1_GRAB_COIL = 12         # 机械臂1 夹爪
ARM2_Z_COIL = 13            # 机械臂2 Z轴（点胶）
ARM2_X_COIL = 14            # 机械臂2 X轴
PUSHER_COIL = 15            # 推杆（已改为模拟量，保留旧地址兼容）

# ========== Holding Register（模拟量控制）==========
ARM1_X_REG = 0              # 机械臂1 X轴（锁螺丝/搬运）Set Point (V)  ※实际=机械臂2
ARM1_Z_REG = 1              # 机械臂1 Z轴（锁螺丝/搬运）Set Point (V)  ※实际=机械臂2
ARM2_X_REG = 2              # 机械臂2 X轴（点胶）Set Point (V)  ※实际=机械臂0
ARM2_Z_REG = 3              # 机械臂2 Z轴（点胶）Set Point (V)  ※实际=机械臂0
PUSHER_SET_REG = 4          # 推杆 Set Point (V)

# ========== Input Register（模拟量读取）==========
PUSHER_POS_REG = 0          # 推杆 Position (V)

# ========== Input 输入（Factory IO→Python）==========
VISION_0_INPUT = 0          # 视觉传感器0（来料检测 True=有料）
VISION_1_INPUT = 1          # 视觉传感器1（成品检测 True=OK False=NG）
TABLE_A_LIMIT_0_INPUT = 2   # 转盘A 限位0°
TABLE_A_LIMIT_90_INPUT = 3  # 转盘A 限位90°
TABLE_B_LIMIT_0_INPUT = 4   # 转盘B 限位0°
TABLE_B_LIMIT_90_INPUT = 5  # 转盘B 限位90°
ARM1_DETECT_INPUT = 6       # 机械臂1 检测到物体
ARM2_DETECT_INPUT = 7       # 机械臂2 检测到物体（未接线，Python模拟）
PUSHER_FRONT_INPUT = 7      # 推杆前限位
PUSHER_BACK_INPUT = 8       # 推杆后限位
ARM0_MOVING_X_INPUT = 9     # 机械臂0（点胶）Moving X 信号
ARM0_MOVING_Z_INPUT = 10    # 机械臂0（点胶）Moving Z 信号
ARM2_MOVING_X_INPUT = 11    # 机械臂2（锁螺丝）Moving X 信号
ARM2_MOVING_Z_INPUT = 12    # 机械臂2（锁螺丝）Moving Z 信号

# ================================================================
# ★ 命名对照表（重要！不改代码只对照，避免每次都被绕晕）
# ----------------------------------------------------------------
# 这个项目里机械臂有"三套名字"，指的是同一批硬件：
#
#   物理位置      现场元件名(Factory IO)        Python 寄存器     Python 信号
#   ----------    ------------------------     ------------      -------------
#   锁螺丝位      Two-Axis Pick & Place 2      ARM1_X/Z_REG      ARM2_MOVING_X/Z_INPUT
#   点胶位        Two-Axis Pick & Place 0      ARM2_X/Z_REG      ARM0_MOVING_X/Z_INPUT
#
# 为什么会错位：寄存器是早期按"机械臂1/机械臂2"起的名字，后来现场给
# 机械臂编了 0/2 的号，Moving 信号又按现场编号走，就错开了。
#
# 所以读代码时看到："ARM1_*_REG 配 ARM2_MOVING_*_INPUT" 是**正确的**，
# 不是笔误。main.py 里全篇一致，别去"顺手改统一"。
#
# 另外两个历史坑：
#   * ARM1_DETECT_INPUT / ARM2_DETECT_INPUT 的机械臂自带检测**没接线**，
#     读不到值。现场用漫反射(Diffuse Sensor)接在 Input 6 顶上：
#     ARM1_DETECT_INPUT = 6 实际是漫反射，不是机械臂检测。
#   * ARM2_DETECT_INPUT = 7 是废弃值，Input 7 真身是 PUSHER_FRONT_INPUT。
# ================================================================

# ========== 工站配置 ==========
STATIONS = {
    1: {"name": "视觉检测", "sensor": VISION_0_INPUT, "actuator": BELT_0_COIL, "yield_reg": 0},
    2: {"name": "锁螺丝",   "sensor": ARM1_DETECT_INPUT, "actuator": ARM1_GRAB_COIL, "yield_reg": 1},
    3: {"name": "点胶",     "sensor": ARM2_DETECT_INPUT, "actuator": ARM2_Z_COIL, "yield_reg": 2},
    4: {"name": "成品检测", "sensor": VISION_1_INPUT, "actuator": PUSHER_COIL, "yield_reg": 3},
}

# ========== 全局信号 ==========
TABLE_ROTATE_COIL = TABLE_A_TURN_COIL
TABLE_POSITION_REG = 0
INFEED_SENSOR = VISION_0_INPUT
SORT_OK_COIL = BELT_3_COIL
SORT_NG_COIL = PUSHER_COIL
ALARM_COIL = 20

TARGET_PRODUCTION_REG = 10
ACTUAL_PRODUCTION_REG = 11
# ========== 时序参数 ==========
LOOP_INTERVAL = 0.1
TABLE_INDEX_TIME = 0.5
PRODUCTION_CYCLE_TIME = 3.0

# ========== 机械臂运动时序（统一收口，便于调节拍）==========
# 背景：机械臂是"速度控制"不是位置闭环——写一个值它只是朝那个方向走，
#      没人告诉它"走到了没有"。所以每一步要么盲等固定时间，要么用
#      Moving 信号判断。下面这些常量就是所有运动等待的唯一出处。
# ★ 是否用机械臂 Moving 信号判断"动作到位" —— 已用探针实测，打开。
#   探针 test_arm_moving.py 结论（2026-09-28）：
#     * 信号语义 = "运动中为 1，停止为 0"，判据方向正确
#     * 抬起延迟稳定在 0.07~0.14s（所以 ARM_WAKE_TIME 必须 > 0.14，否则误判没起步）
#     * 满行程真实耗时：X 1.59~1.60s，Z 0.83s
#     * 信号"不响应"只发生在机械臂被卡在极限、物理上动不了的时候 → 那正是要用
#       熔断机制兜底的场景，不是信号本身坏
USE_ARM_MOVING_SIGNAL = True

ARM_MOVE_TIMEOUT = 2.5      # 等信号落下的上限。实测最长 1.60s，留 0.9s 余量
ARM_WAKE_TIME = 0.40        # 等信号抬起。实测 0.07~0.14s，取 0.40 保证不误判
# ========== 机械臂回原点（每个生产周期开头做一次）==========
# 动作就三步：轻微前伸/下探 → 保持 → 归零。不要再往上叠补丁。
# 目的：让机械臂每件都从真正的原点出发，不累积偏移。
#   偏移量沿用现场原来的 500（按用户确认，不改）。如果发现机构"只是抖一下
#   没真动"，再考虑加大——但一次只改一个变量。
ARM_HOME_PRESTRETCH = 500       # 前伸/下探的偏移量（0~10000）
ARM_HOME_PRESTRETCH_HOLD = 0.5  # 【前伸段】写 500 之后、写 0 之前的保持时间（沿用原值 0.5）
ARM_HOME_SETTLE = 1.9           # 【回零段】写 0 之后、本次回原点结束前的稳定时间
#
# ★ 两段管的事不一样，别搞混（我第一次就写错了注释）：
#     前伸段：写 500 → 写 0 之前        受 PRESTRETCH_HOLD 约束
#     回零段：写 0   → 下一次回原点之前   受 SETTLE 约束
#
# ★ SETTLE 必须 >= 回零段最坏行程：
#     机械臂做完活停在伸展位时（锁螺丝完成后 X=10000），回零是 10000→0 = 满行程，
#     X 满行程实测 1.59s → 取 1.9s（余量 0.31s）。
#     设小了会让 X 没缩回去就被当成"已归零"，下一件从半路出发、位置逐件累积偏移
#     —— 也就是"下个周期把极限当原点"。
#
# ⚠ 已知的截断（不打算现在改）：第 2、4 次回原点时机械臂停在伸展位，
#     前伸本身要走 1.51s / 0.72s，但 HOLD 只有 0.5s，所以前伸会被提前打断、
#     直接掉头回零。最终位置没问题（回零段 1.9s 管够），
#     但"前伸唤醒机构"的效果打了折扣。原始代码也是 HOLD=0.5s，属原有行为。
#     等回原点在现场验证稳定后，再单独处理这个（一次只改一个变量）。
# 兼容旧名字（旧代码/旧文档里出现过，保留避免 NameError）
ARM_HOME_OFFSET = ARM_HOME_PRESTRETCH
ARM_HOME_OFFSET_HOLD = ARM_HOME_PRESTRETCH_HOLD
ARM_GRAB_SETTLE = 0.4       # 吸嘴开/合后的稳定时间（原 1.0 / 0.5）
# 盲等时长模型（只在信号不可用时生效）：
#   等待 = max(fallback, ARM_TRAVEL_TIME × 行程比例 + ARM_MIN_MOVE_TIME)
#   ARM_TRAVEL_TIME = 满行程 0→10000 大约需要多久；先用现场"Z 下 1.5~2.0s 见效"倒推
# ★ 行程比例等待：默认关闭。
#   实测教训：原来那些固定等待（1.0~1.5s）是现场调到"刚好够用"的，
#   我用模型去"优化"反而让步骤2/3 变慢（step2 8.99→10.56s）。没有实测数据
#   支撑的调参就是赌博，所以先关掉，等 test_arm_moving.py 测出真实到位时间再开。
# ★ 行程比例等待：已按探针实测值校准，打开（作为信号不可用时的兜底）。
#   ★★ 重要发现：原代码给 X 轴只留 1.0s，但 X 满行程实测要 1.59s ——
#      这是【等待不足】，X 轴每次都没走完就被发下一个命令，位置越跑越偏。
#      Z 轴原留 1.0~1.5s，实测只要 0.83s，那里才是真的有余量。
USE_TRAVEL_WAIT = True

ARM_MOVE_FLOOR = 0.15       # 固定等待下限。实测信号抬起就要 0.07~0.14s
ARM_MIN_MOVE_TIME = 0.30    # 机构启动迟滞 + 停止判定余量
# 满行程耗时（探针实测）。★ X 和 Z 差别很大，必须分开，否则要么 X 等太久、要么 Z 等太短。
#   X: 0→10000 实测 1.59s，10000→0 实测 1.60s
#   Z: 0→8500 / 8500→0 实测 0.83s
# 只在信号失效时兜底用；信号正常时到位即走，不受这两个值影响。
ARM_TRAVEL_TIME = {
    "X": 1.70,              # 含 0.11s 余量
    "Z": 0.95,              # 含 0.12s 余量
}
# 兼容旧代码：万一别处还在用标量形式，取最慢的那个
ARM_TRAVEL_TIME_DEFAULT = 1.70
ARM_DISPENSE_TRAVEL = 1.6   # 点胶 Z 下到 8400 的行程等待
ARM_DISPENSE_DWELL = 0.4    # 点胶到位后的停留
                            #   ↑ 两段合计 2.0s，与原代码的 fallback=2.0 完全一致
#   ⚠ 注意 fallback 是"下限"不是"覆盖值"：等待 = max(fallback, 行程时间)。
#     所以给某个动作传一个很大的 fallback（比如 2.0）会让行程模型失效、
#     退化成固定 2 秒。只有在"这个动作确实需要固定工艺时间"时才这么传。
#     点胶 Z 下就是这种情况（见 ARM_DISPENSE_DWELL）。
ARM_MOVE_DEBUG = True       # True: 每次机械臂动作打印"信号确认/盲等兜底"，调节拍时很有用
                            # 信号稳定后可设 False 让控制台干净

# ========== 成品检测（视觉1）==========
# 等待视觉1 读到 True 的上限。原来写死 10 秒，料一旦没到位就白等 10 秒/件。
# 调小可以止血，但真正的解法是让料每次都到位（见 04_复原报告 §5）。
VISION_WAIT_TIMEOUT = 3.0
# ========== 异常阈值 ==========
YIELD_WARNING_THRESHOLD = 0.85
JAM_THRESHOLD_SECONDS = 3.0
LOW_EFFICIENCY_PPM = 5.0

# ========== LLM ==========
# ★★ 冻结开关：调试产线期间置 False。
#    理由：LLM 一直在调 PRODUCTION_CYCLE_TIME（日志里反复出现
#    "节拍已调整为 2.5/3.0/3.5 秒"），把节拍改来改去，
#    导致"改一个变量看效果"这件事根本做不到——你分不清变化是代码带来的还是 LLM 带来的。
#    调产线时冻结，等产线稳定了再打开。
LLM_ENABLED = False

LLM_ANALYSIS_INTERVAL = 30
LLM_MODEL = "gemma3:4B"
LLM_BASE_URL = "http://localhost:11434/api/generate"

