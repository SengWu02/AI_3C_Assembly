# AI 3C Assembly — 3C 组装岛（Factory IO + Python 数字孪生产线）

用 **Factory IO** 做被控现场、**Python 通过 Modbus TCP** 做控制的 3C 产品装配产线，
产线上挂了一个"AI 线长"（本地 Ollama LLM + 评分治理）负责盯产量、良率、异常和节拍。

![Factory IO](https://img.shields.io/badge/Factory%20IO-2.5.6-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green) ![Modbus](https://img.shields.io/badge/Modbus-TCP-orange)

---

## 一、工艺流程

```
Emitter 发料
   ↓
皮带机0 ── Vision Sensor 0（来料检测）
   ↓
转盘A  0° 接料 → 滚轮把料送到中心 → 转 90°
   ↓
皮带机2 → 停到【锁螺丝位】机械臂2
   ↓
机械臂2  下压（锁螺丝）→ 抓起 → 搬运到转盘B
   ↓
转盘B  0° → 转 90°（点胶位）
   ↓
机械臂0  下探（点胶）→ 抬起
   ↓
转盘B  转回 0° → 皮带机3 ── Vision Sensor 1（成品检测）
   ↓
Pusher 推杆分拣 ── NG → 斜坡滑道 → 不良仓位
                └─ OK → 继续往后 → 良品仓位
```

> **命名约定（重要，容易踩坑）**
> 现场的机械臂编号是 `Two-Axis Pick & Place 0/2`，而 Python 里叫 `ARM1`/`ARM2`：
> - `ARM2`（Python） = **锁螺丝位** = 现场 `Two-Axis Pick & Place 2`
> - `ARM0`（Python） = **点胶位**   = 现场 `Two-Axis Pick & Place 0`
>
> 代码注释里保留了历史命名（`ARM1` 旧称）。**改代码前先看 `config.py` 的注释。**

---

## 二、快速开始

```powershell
# 1. 进入程序目录（爬坡日志会写在这里）
cd 03_程序/factory_ai_runtime0.4

# 2. 建虚拟环境、装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pymodbus requests

# 3. 开 Factory IO，打开场景，驱动设成 Modbus TCP Server
#    场景：02_场景/3C assembly1.factoryio
#    确认 Server 监听端口 502

# 4. 确认 config.py 里的 IP 是你这台机器的
notepad config.py       # MODBUS_HOST = "192.168.102.1"

# 5. 起程序
python main.py          # 会问"请输入产量"，填 3
```

**先做单点验证再跑全线：**

```powershell
python test_which_arm.py       # 确认哪个寄存器驱动哪个臂（强烈建议先跑这个）
python test_arm_calibrate.py   # 标定"设定点 -> 实际位置"曲线
python test_table_hold.py      # 确认转盘线圈行为（写 False = 回 0°）
```

---

## 三、目录结构

```
AI_3C_Assembly/
├── 01_交接说明.md              项目交接说明（先看这个）
├── 04_复原报告.md              复原方法、可信度、遗留缺陷清单
├── 05_运行与接线速查.md         跑起来要做的几步 + 完整点表
├── 02_场景/
│   ├── 3C assembly1.factoryio  ★ Factory IO 场景（当前版本）
│   ├── 3C assembly.factoryio   上一版场景（存档）
│   └── 场景与IO对照表.md        现场元件 ↔ Modbus 地址（已从场景文件核对）
├── 03_程序/
│   ├── factory_ai_runtime0.4/  ★ 产线控制程序
│   │   ├── main.py             主程序 + 状态机 + 爬坡节拍记录
│   │   ├── config.py           ★ 全部 Modbus 地址 / 时间常数（改参数只改这里）
│   │   ├── modbus_client.py    Modbus / 虚拟 PLC 双后端驱动
│   │   ├── dashboard.py        ★ 赛博工业风 Tkinter GUI（转盘布局图）
│   │   ├── mock_plc.py         虚拟 PLC（PROTOCOL="virtual" 时用）
│   │   ├── statistics.py / event_manager.py / jam_detector.py
│   │   ├── efficiency_detector.py / safety_manager.py / ai_governance.py
│   │   ├── llm_manager.py      Ollama 调用封装
│   │   ├── test_*.py           各种单点探针（见下节）
│   │   ├── workflow/           7 份"AI 线长"岗位职责文档
│   │   └── _原始备份_加注释前/  加注释之前的原始代码（对照用）
│   └── webots/                 上一阶段 Webots 世界的残留（非本项目主线）
└── 99_复原过程产物/
    ├── 会话记录_transcript.jsonl   从 346MB 会话 JSON 抽出的对话（含全部代码快照）
    ├── 场景IO解析_scene_map.json   从场景 XML 解出的组件与 IO 表
    └── 会话内临时脚本/            会话里用过的临时代码（仅存档）
```

---

## 四、硬件接线（Python ↔ Factory IO）

### Python 写（Coil，0x 区）

| Coil | 干什么 | 常量 |
|---:|---|---|
| 0 | 发料 | `EMITTER_COIL` |
| 1 | 皮带机0（来料） | `BELT_0_COIL` |
| 2 | 皮带机2（转盘A→锁螺丝） | `BELT_2_COIL` |
| 3 | 皮带机3（出料） | `BELT_3_COIL` |
| 4 / 5 | 转盘A 滚轮 正/反 | `TABLE_A_ROLL_P/N_COIL` |
| 6 | 转盘A 旋转 | `TABLE_A_TURN_COIL` |
| 7 / 8 | 转盘B 滚轮 正/反 | `TABLE_B_ROLL_P/N_COIL` |
| 9 | 转盘B 旋转 | `TABLE_B_TURN_COIL` |
| 12 | 锁螺丝位夹爪/吸嘴 | `ARM1_GRAB_COIL` |
| 15 | 推杆 | `PUSHER_COIL` |

### Python 读（Discrete Input，1x 区）

| Input | 读什么 | 常量 |
|---:|---|---|
| 0 | 视觉0 来料检测 | `VISION_0_INPUT` |
| 1 | 视觉1 成品检测 | `VISION_1_INPUT` |
| 2 / 3 | 转盘A 0°/90° 限位 | `TABLE_A_LIMIT_0/90_INPUT` |
| 4 / 5 | 转盘B 0°/90° 限位 | `TABLE_B_LIMIT_0/90_INPUT` |
| 6 | 漫反射（代替机械臂检测） | `ARM1_DETECT_INPUT` |
| 7 / 8 | 推杆 前/后 限位 | `PUSHER_FRONT/BACK_INPUT` |
| 9 / 10 | 点胶位机械手 Moving X/Z | `ARM0_MOVING_X/Z_INPUT` |
| 11 / 12 | 锁螺丝位机械手 Moving X/Z | `ARM2_MOVING_X/Z_INPUT` |

### 寄存器（Holding Register 4x / Input Register 3x）

| 寄存器 | 写（4x）= 设定点 | 读（3x）= 实际位置 |
|---:|---|---|
| 0 | 锁螺丝臂 X 设定点 | 锁螺丝臂 X 实际位置 |
| 1 | 锁螺丝臂 Z 设定点 | 锁螺丝臂 Z 实际位置 |
| 2 | 点胶臂 X 设定点 | 点胶臂 X 实际位置 |
| 3 | 点胶臂 Z 设定点 | 点胶臂 Z 实际位置 |

**寄存器数值含义：** `ScaleFactor = 1000` ⇒ 寄存器值就是**毫伏**，`10000 = 10.0V`。

```
值 = 0      → 原点侧（X 缩回 / Z 抬起，最高）
值 = 10000  → 极限侧（X 伸出 / Z 下降到最低）
```

> ⚠️ **Input Register 需要在 Factory IO 场景里手动挂载**（`NumericInput0~3`），
> 否则读回来恒为 0。详见 `config.py` 里 `ARM_POS_REG` 上方的注释。

---

## 五、探针（`test_*.py`）怎么用

这些探针是调产线时真正靠得住的东西 —— **每个都只测一件事，用实测数据代替猜测**。

| 探针 | 回答什么问题 |
|---|---|
| `test_which_arm.py` | 哪个寄存器驱动哪个机械臂（写 10000，问你看哪个臂动了）|
| `test_arm_calibrate.py` | "设定点 → 实际位置"的完整曲线（阶梯法，14 个点）|
| `test_arm_moving.py` | Moving 信号的响应时序（抬起/落下延迟、满行程耗时）|
| `test_table_hold.py` | 转盘线圈行为：写 False 是"回 0°"还是"松手" |
| `test_table_a.py` | 转盘A 限位探针 |
| `test_reg_drive.py` | 寄存器值是否真的写进 PLC（回读校验）|
| `test_read_position.py` | 位置反馈挂在哪个 Input Register |
| `test_pos_truth.py` | 位置读数可信度（静止时稳不稳、收敛到哪）|
| `test_z_moves.py` | 数出某个轴"实际发生了几次独立运动"（抓多余动作）|
| `test_watch_reg2.py` | 监视某个寄存器的设定点 + 实际位置（抓"谁在写它"）|
| `test_dispense_return.py` | 点胶臂回零轨迹（会不会冲过头）|

**通用用法：** Factory IO 跑着的时候另开一个窗口执行，按提示确认现场安全后回车。

---

## 六、调试过程中确认的关键事实

下面这些**全部是实测得出的**（探针脚本可复现），不是推断：

### 1. 转盘：写线圈 False = 命令回 0°

`Turntable` 是 `Monostable`（单稳态）：
- 写 `True` → 转到 90° 并**保持**
- 写 `False` → **立刻开始回 0°**（0.11s 内起步，约 2.4s 到位）

所以"接到位后马上松手"会让料卡在盘边 —— 必须**先保持住，等料进/出完再松手**。

### 2. 机械臂：Moving 信号会【提前落下】

实测（`reg3` 写 8000）：

```
命令 reg3 = 8000
  Z 运动开始   位置=262
  Z 运动结束   位置=7441   ← ★ 信号落下了，但轴只走到 7441
  Z 运动开始   位置=7627   ← 没人下命令，轴自己继续跑
  Z 运动结束   位置=7874
```

**只等信号的话，程序会在轴只走了一半时就往下执行，
于是"轴自己继续跑"看起来就像"机械臂多做了一个动作"。**

✅ 修法：动作结束后**读位置反馈，连续 N 次读数相同才算停稳**（`_wait_axis_settled`）。

### 3. 寄存器地址会撞车（本项目踩过最大的坑）

`config.STATIONS` 里的 `yield_reg` 原来是 `0/1/2/3` —— 而这四个地址**正好是四个机械臂轴的设定点**。
每做完一件，程序就把"良率 × 100"当成电压写给机械臂：

| 良率 | 写入值 | 机械臂动作 |
|---|---|---|
| 100% | `10000` | **伸到极限** |
| 50% | `5000` | 走到一半 |
| 0% | `0` | 回原点 |

**现象就是"把所有机械臂动作代码都删了，机械臂还是自己跑到极限"。**

✅ 修法：良率**只写 GUI**，不再碰任何 PLC 寄存器。

> 教训：**加新的寄存器地址前，先 grep 一遍有没有撞车。**

### 4. 用探针代替猜测

整个调试过程反复验证了一条：**写信/读信 + 实测 vs 命令对照**，比读代码猜快得多。
尤其是"命令写下去了，轴到底走到哪"——没有位置反馈就只能靠眼睛，有反馈就能直接看数字。

---

## 七、可调参数（都在 `config.py`）

```python
# ---- 机械臂位置（0~10000，值越大越往下/往外）----
ARM1_X_TARGET = 10000    # 锁螺丝臂 X → 转盘B 上方
ARM1_Z_CONTACT = 8500    # 锁螺丝臂 Z 下接触（取料）
ARM1_Z_WORK    = 7000    # 锁螺丝臂 Z 放料高度
ARM2_X_TARGET = 5000     # 点胶臂 X → 点胶位
ARM2_Z_WORK    = 7000    # 点胶臂 Z 工作高度

# ---- 回零 ----
ARM_HOME_PRESTRETCH = 500      # 前伸/下探幅度（唤醒机构，避免"贴原点写0等于没写"）
ARM_HOME_PRESTRETCH_HOLD = 0.5 # 前伸后保持多久
ARM_HOME_SETTLE = 1.9          # 写 0 之后等多久（必须 >= 最坏回零行程）

# ---- 等轴停稳 ----
ARM_SETTLE_TIMEOUT = 3.0       # 等停稳最长时间
ARM_SETTLE_SAMPLES = 3         # 连续几次相同算停稳
ARM_SETTLE_POLL = 0.08         # 读间隔

# ---- 转盘 / 皮带时间 ----
TABLE_A_LOAD_WAIT = 3.5        # 料从发料器走到转盘A 中心
TABLE_A_REST = 1.0             # 料进中心后的停稳时间
BELT2_TRANSIT_WAIT = 4.5       # ★ 皮带2 走带时间（= 皮带什么时候停）
TABLE_B_PUSH_WAIT = 3.5        # 转盘B 滚轮把料推到皮带3
TABLE_B_SETTLE = 1.0           # 料推出后的稳定时间

# ---- 调试开关 ----
LLM_ENABLED = False            # ★ 调产线期间必须 False，否则 LLM 会一直改节拍
ARM_POS_TRACE = True           # 位置轨迹记录（定位完可关）
ARM_HOME_RESP_PROBE = False    # 回零时的响应探测（省节拍，排查时才开）
```

> ⚠️ **BELT2_TRANSIT_WAIT 的语义容易搞错**：它不是"料走完全程要多久"，
> 而是"皮带什么时候停"——让料在快到工位时停皮带，剩下的路靠惯性滑到机械臂能取的位置。
> 太大会让料顶在挡板上白等，太小会让料走不到位。标定只看现象：
> 料先到并顶住 → 减小；机械臂到了料还没到 → 加大。

---

## 八、节拍优化记录

初始节拍约 **62.5 s/件**，精修后约 **52 s/件**。改动都是"删冗余 + 用实测数据替代猜测"：

| # | 改动 | 省 |
|---|---|---|
| 1 | **删除两次冗余的"干活前回零"**（步骤2 的"取料前"、步骤3 的"点胶前"）<br>理由：步骤1 刚做完初始化回零，臂一次都没动过，再回一次是纯浪费<br>副作用：_arm_home 会把臂推到 500 再回 0，等于把已归零的臂又动一遍 | 9.6 s |
| 2 | **关掉回零时的"响应探测"**（ARM_HOME_RESP_PROBE=False）<br>那是排查"前伸 500 到底动没动"时加的调试代码，每次调用多等 0.7 s × 6 次 | 4.2 s |
| 3 | **删除假的漫反射传感器判据**<br>原来 _wait_input(..., timeout=5.0) 等满 5 秒再 +1.5 秒保底，而那个传感器现场确认是假的 | 5.0 s |
| 4 | **两个臂同时回零**（_arm_home_both）<br>两臂是独立执行机构，各有自己的寄存器和 Moving 信号，可以并行下发、并行等待 | 3.4 s |
| 5 | **修掉 BELT2_TRANSIT_WAIT**<br>先误设成 12 s（料到挡板白等 8 s），按实测倒推改成 4.5 s | 7.5 s |

**关键经验：**

- **冗余动作比慢动作更值钱。** 删掉两次不必要的回零，比把每次回零优化 10% 有效得多。
- **"等一个不存在的东西"是最贵的。** 那个假传感器每件白花 5 秒。
- **并行是免费的。** 两个独立机构串行等，改成并行直接减半，没有任何风险。

---

## 九、关于本仓库的来源

本仓库的程序代码**不是重新编写的**，而是从一次对话历史的 JSON（346 MB）里
**回放出来的最终态**，配合一个 Factory IO 场景文件复原而成。

复原方法、可信度评估和遗留缺陷清单见 [`04_复原报告.md`](04_复原报告.md)。

---

## 十、License

见 [LICENSE](LICENSE)。
