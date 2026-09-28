# 3C组装岛 — 场景与 IO 对照表

**本表不是从对话里抄的，是从 `3C assembly.factoryio` 场景文件的 `<ModbusTCPServer>` 节直接解出来的。**
解析方式：场景里每个 IO 点带一个 `Key`（GUID），`<ModbusTCPServer>` 里用 `<BitInputN PointIOKey="GUID">` 指定
第 N 号点挂在哪个元件上，把两边对起来就得到 Modbus 地址 ↔ 现场元件的**权威映射**。
（解析结果同时存成 [99_复原过程产物/场景IO解析_scene_map.json](../99_复原过程产物/场景IO解析_scene_map.json)）

场景信息：
- 驱动：`ModbusTCPServer`（CurrentDriver=32），16 位输入 / 16 位输出 / 8 路 Numeric，`ScaleFactor="1000"`
- 场景描述字段：`3C组装岛、工位-左视觉检测，上锁螺丝，右点胶，下成品检测`
- 元件总数 57：转盘 ×2、2m 皮带 ×3、两轴机械手 ×2、视觉 ×2、推杆 ×1、漫反射 ×1、发料器 ×1、卸料器 ×2、低斜滑道 ×2、安全门 ×17、自由滚轮 ×15、立柱 ×8

> ⚠️ **两套地址不要混**
> 场景 XML 里每个 IO 还有一个 `Address` 属性（例如 "Turntable 0 Roll (+)" 是 34）。
> 那是 Factory IO **内部画布地址**，**不是 Modbus 地址**。真正对 Python 生效的是下面的 0 起编号。

---

## 1. Coils — 0x 区（Python 写 → 现场动作）

对应代码：`modbus_client.write_coil(地址, True/False)`

| Coil | 常量名（config.py） | 现场元件 | 位置 [X,Y,Z] |
|---:|---|---|---|
| 0 | `EMITTER_COIL` | Emitter 0 (Emit) 发料器 | [256, 9, 113] |
| 1 | `BELT_0_COIL` | Belt Conveyor (2m) 0 皮带机0（来料） | [256, 3, 117] |
| 2 | `BELT_2_COIL` | Belt Conveyor (2m) 2 皮带机2（转盘A→锁螺丝） | [272, 3, 132] |
| 3 | `BELT_3_COIL` | Belt Conveyor (2m) 1 皮带机3（出料） | [271, 4, 159] |
| 4 | `TABLE_A_ROLL_P_COIL` | Turntable 0 Roll (+) 转盘A滚轮正转 | [256, 5, 132] |
| 5 | `TABLE_A_ROLL_N_COIL` | Turntable 0 Roll (−) 转盘A滚轮反转 | [256, 5, 132] |
| 6 | `TABLE_A_TURN_COIL` | Turntable 0 Turn 转盘A旋转 | [256, 5, 132] |
| 7 | `TABLE_B_ROLL_P_COIL` | Turntable 1 Roll (+) 转盘B滚轮正转 | [270, 6, 143] |
| 8 | `TABLE_B_ROLL_N_COIL` | Turntable 1 Roll (−) 转盘B滚轮反转 | [270, 6, 143] |
| 9 | `TABLE_B_TURN_COIL` | Turntable 1 Turn 转盘B旋转 | [270, 6, 143] |
| 12 | `ARM1_GRAB_COIL` | Two-Axis Pick & Place **2** (Grab) 锁螺丝位夹爪/吸嘴 | [269, 10, 126] |
| 15 | `PUSHER_COIL` | Pusher 0 推杆（推 NG 料） | [264, 7, 160] |

### ⚠️ Coil 10 / 11 / 13 / 14 在场景里是空的

`config.py` 里还有这几个常量，但它们**在当前场景里没有对应的输出点**：

| 常量名 | 值 | 实际情况 |
|---|---:|---|
| `ARM1_Z_COIL` | 10 | 场景里机械手**没有** Z 轴线圈输出，Z 走模拟量（NumericOutput 1） |
| `ARM1_X_COIL` | 11 | 同上，X 走模拟量（NumericOutput 0） |
| `ARM2_Z_COIL` | 13 | 点胶位机械手同样只走模拟量 |
| `ARM2_X_COIL` | 14 | 同上 |

这是**机械臂从"开关量控制"改成"模拟量控制"留下的历史残留**（会话里 1727 那一轮改的）。
所以别奇怪为什么 `config.py` 里 X/Z 有线圈又有寄存器——线圈那套已经废了，
`main.py` 里机械臂动作全部走 `write_register()`。

---

## 2. Discrete Inputs — 1x 区（现场 → Python 读）

对应代码：`modbus_client.read_input(地址)`

| Input | 常量名（config.py） | 现场元件 | 位置 |
|---:|---|---|---|
| 0 | `VISION_0_INPUT` | Vision Sensor **0** 来料检测（皮带0 上） | [255, 16, 120] |
| 1 | `VISION_1_INPUT` | Vision Sensor **1** 成品检测（皮带3 上） | [271, 16, 160] |
| 2 | `TABLE_A_LIMIT_0_INPUT` | Turntable 0 (Limit 0) 转盘A 0°限位 | [256, 5, 132] |
| 3 | `TABLE_A_LIMIT_90_INPUT` | Turntable 0 (Limit 90) 转盘A 90°限位 | [256, 5, 132] |
| 4 | `TABLE_B_LIMIT_0_INPUT` | Turntable 1 (Limit 0) 转盘B 0°限位 | [270, 6, 143] |
| 5 | `TABLE_B_LIMIT_90_INPUT` | Turntable 1 (Limit 90) 转盘B 90°限位 | [270, 6, 143] |
| 6 | `ARM1_DETECT_INPUT` | **Diffuse Sensor 0** 漫反射（皮带2 末端，替代机械臂检测） | [270, 8, 129] |
| 7 | `PUSHER_FRONT_INPUT` | Pusher 0 (Front Limit) 推杆前限位 | [264, 7, 160] |
| 8 | `PUSHER_BACK_INPUT` | Pusher 0 (Back Limit) 推杆后限位 | [264, 7, 160] |
| 9 | `ARM0_MOVING_X_INPUT` | Two-Axis Pick & Place **0** (Moving X) 点胶位X运动中 | [259, 10, 143] |
| 10 | `ARM0_MOVING_Z_INPUT` | Two-Axis Pick & Place **0** (Moving Z) 点胶位Z运动中 | [259, 10, 143] |
| 11 | `ARM2_MOVING_X_INPUT` | Two-Axis Pick & Place **2** (Moving X) 锁螺丝位X运动中 | [269, 10, 126] |
| 12 | `ARM2_MOVING_Z_INPUT` | Two-Axis Pick & Place **2** (Moving Z) 锁螺丝位Z运动中 | [269, 10, 126] |

### 关于 Input 6 / Input 7 撞号

`config.py` 里：

```python
ARM1_DETECT_INPUT  = 6   # 机械臂1 检测到物体
ARM2_DETECT_INPUT  = 7   # 机械臂2 检测到物体（未接线，Python模拟）
PUSHER_FRONT_INPUT = 7   # 推杆前限位
PUSHER_BACK_INPUT  = 8   # 推杆后限位
```

按场景文件核对：
- **Input 6 = 漫反射传感器**（Diffuse Sensor 0），会话里 1682 那一轮用户把它接到 input 6，用来替代机械臂自带的 Item Detected。
- **Input 7 = 推杆前限位**，`ARM2_DETECT_INPUT = 7` 是**废弃值**（用户原话："这两个我没填，机械臂的 Detected 是空的"）。
- 两个机械手的 `Item Detected`（场景内部地址 16 / 6）**没有映射到 Modbus**，所以读不到。

改地址的时候按**元件名**对，别按常量名的字面意思对。

---

## 3. Holding Registers — 4x 区（Python 写 → 机械臂模拟量）

对应代码：`modbus_client.write_register(地址, 值)`
场景 `ScaleFactor="1000"`，所以 **0–10000 对应 0–10V**，即 1 V = 1000。

| 寄存器 | 常量名 | 现场元件 Set Point | 位置 | 代码里的用法 |
|---:|---|---|---|---|
| 0 | `ARM1_X_REG` | Two-Axis Pick & Place **2** X Set Point | [269, 10, 126] | 锁螺丝位 X 伸出/回零（0 = 原点，10000 = 极限） |
| 1 | `ARM1_Z_REG` | Two-Axis Pick & Place **2** Z Set Point | [269, 10, 126] | 锁螺丝位 Z 升降（**0 V = 顶部原点，10 V = 最下**） |
| 2 | `ARM2_X_REG` | Two-Axis Pick & Place **0** X Set Point | [259, 10, 143] | 点胶位 X |
| 3 | `ARM2_Z_REG` | Two-Axis Pick & Place **0** Z Set Point | [259, 10, 143] | 点胶位 Z |
| 4 | `PUSHER_SET_REG` | Pusher 0 Set Point | [264, 7, 160] | 推杆模拟量（已弃用，见下） |

**代码里实际用到的模拟量取值**（来自 `main.py` 恢复后的内容）

| 值 | 含义 |
|---:|---|
| 0 | 原点（顶部） |
| 500 | 硬复位用的"先往反方向走一点" |
| 5000 | X 轴伸出到转盘B / 点胶位上方 |
| 8400–8500 | Z 轴下降到取料/放料/点胶高度 |

> **推杆为什么不用模拟量了**
> 会话里用户试过把推杆改成"数字&amp;模拟"类型（Holding Reg 4 给设定、Input Reg 0 读位置，比率 1000），
> 折腾一轮后**宣布失败**，最后退回 `Monostable` 类型：
> **推杆 = Coil 15 开关量，前限位 Input 7，后限位 Input 8**。
> `PUSHER_SET_REG` / `PUSHER_POS_REG` 保留只是兼容旧代码，别再用。

---

## 4. Input Registers — 3x 区

| 寄存器 | 常量名 | 说明 |
|---:|---|---|
| 0 | `PUSHER_POS_REG` | 推杆位置（模拟量方案已废弃，当前无效） |

## 5. Numeric Outputs（场景 → Modbus 的模拟量输出通道）

下面 4 路就是上面 §3 的物理来源，一一对应：

| NumericOutput | 现场元件 Set Point | config.py 里的寄存器 |
|---:|---|---:|
| 0 | Two-Axis Pick & Place 2 X Set Point (V) | 0 (`ARM1_X_REG`) |
| 1 | Two-Axis Pick & Place 2 Z Set Point (V) | 1 (`ARM1_Z_REG`) |
| 2 | Two-Axis Pick & Place 0 X Set Point (V) | 2 (`ARM2_X_REG`) |
| 3 | Two-Axis Pick & Place 0 Z Set Point (V) | 3 (`ARM2_Z_REG`) |

---

## 6. 通信参数

| 项 | 值 | 来源 |
|---|---|---|
| 协议 | Modbus TCP（Factory IO 做 Server，Python 做 Client） | 场景 `CurrentDriver="32"` |
| IP | `192.168.102.1` | `config.py`（会话里配错成 `192.168.101.1` 过一次） |
| 端口 | `502` | `config.py` |
| 从站/单元 ID | `1` | 会话记录 |
| 读输入 | `read_discrete_inputs`（1x 区） | `modbus_client.py` |
| 写输出 | `write_coil`（0x 区） | `modbus_client.py` |
| 写模拟量 | `write_register`（4x 区），负数自动转无符号 | `modbus_client.py` |
| `ALARM_COIL` | 20 | ⚠️ 场景 NumericOutput 只到 7、BitOutput 只到 15，**20 号线圈很可能不存在**，报警输出实际是空写（不影响主流程） |

> 场景里两个机械手的 `Rotate CW/CCW`、`Gripper CW/CCW`、`Stop Blade 0`、
> 两个 `Remover`、17 个 `SafetyDoor` **都没有映射到 Modbus**，程序里也没有用到。
> 安全门如果要接入安全逻辑，得先去 Factory IO 里把它们挂到空闲的 BitInput 上（13/14/15 是空的）。
