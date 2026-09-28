"""
Webots ↔ VirtualPLC 桥接控制器

每个时间步：
  1. 读取 Webots 中各工位的传感器状态
  2. 写入 VirtualPLC 的数字量输入
  3. 读取 VirtualPLC 的数字量输出
  4. 控制 Webots 中的执行器

世界坐标（X=左右，Y=前后，Z=上下）：
  底座        (0, 0, 0.3)
  转盘台面    (0, 0, 0.7)
  工位1 视觉  (~0, -0.94, 0.97)   Y负方向
  工位2 锁螺丝 (0.94, -0.12, 1.0) X正方向
  工位3 点胶   (-0.11, 0.69, 0.97) Y正方向
  工位4 检测   (-0.93, -0.04, 0.89) X负方向
  进料口      (1.5, 0, 0.76)
  出料OK      (-1.37, 0.48, 0.66)
  出料NG      (-1.4, -0.38, 0.66)

Modbus 地址映射（与 config.py 同步）：
  Digital Inputs:
    0  - 工位1 视觉检测结果 (True=OK, False=NG)
    1  - 工位2 螺丝扭矩达标
    2  - 工位3 点胶量达标
    3  - 工位4 成品检测结果
    4  - 转盘定位完成
    5  - 来料到位传感器
    6  - 安全门状态 (True=关闭)
    7  - 急停按钮 (True=按下)

  Digital Outputs:
    0  - 转盘旋转指令
    1  - 工位1 视觉拍照
    2  - 工位2 锁螺丝启动
    3  - 工位3 点胶启动
    4  - 工位4 检测启动
    5  - OK 分拣
    6  - NG 分拣
    7  - 蜂鸣器报警

  Analog Params:
    0  - 转盘位置 (0-3, 对应4个工位)
    10 - 目标产量
    11 - 实际产量
"""

import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mock_plc import VirtualPLC


class WebotsBridge:
    """Webots 世界 ↔ VirtualPLC 的桥梁"""

    def __init__(self):

        self.plc = VirtualPLC()

        # 模拟状态
        self.cycle_count = 0
        self.table_position = 0       # 0-3 对应工位1-4
        self.table_moving = False
        self.production_count = 0
        self.ng_count = 0

        # 场景参数（可由 LLM 线长通过寄存器调整）
        self.vision_pass_rate = 0.95   # 视觉通过率
        self.screw_torque_rate = 0.93  # 锁螺丝良率
        self.glue_volume_rate = 0.92   # 点胶良率
        self.inspect_pass_rate = 0.96  # 成品检测良率

    def step(self):
        """Webots 每帧调用一次"""

        self.cycle_count += 1

        # ---- 读取模拟传感器 ----
        vision_ok = self._simulate_vision()
        torque_ok = self._simulate_screw()
        glue_ok = self._simulate_glue()
        inspect_ok = self._simulate_inspection()

        part_ready = self._simulate_infeed()
        safety_closed = True
        emergency = False

        # ---- 写入 VirtualPLC 输入 ----
        self.plc.set_input(
            0, vision_ok
        )
        self.plc.set_input(
            1, torque_ok
        )
        self.plc.set_input(
            2, glue_ok
        )
        self.plc.set_input(
            3, inspect_ok
        )
        self.plc.set_input(
            4, self.table_position == (self.cycle_count % 4)
        )
        self.plc.set_input(
            5, part_ready
        )
        self.plc.set_input(
            6, safety_closed
        )
        self.plc.set_input(
            7, emergency
        )

        # ---- 从输出线圈读取 LLM 指令 ----
        rotate = self.plc.get_coil(0)
        vision_trigger = self.plc.get_coil(1)
        screw_start = self.plc.get_coil(2)
        glue_start = self.plc.get_coil(3)
        inspect_start = self.plc.get_coil(4)
        sort_ok = self.plc.get_coil(5)
        sort_ng = self.plc.get_coil(6)
        alarm = self.plc.get_coil(7)

        # ---- 执行转盘动作 ----
        if rotate and not self.table_moving:
            self._rotate_table()

        # ---- 执行各工位动作 ----
        if vision_trigger:
            self._do_vision()

        if screw_start:
            self._do_screw()

        if glue_start:
            self._do_glue()

        if inspect_start:
            self._do_inspection()

        if sort_ok:
            self._sort_ok()

        if sort_ng:
            self._sort_ng()

        if alarm:
            self._sound_alarm()

        # ---- 更新模拟量参数给 LLM ----
        self.plc.write_register(0, self.table_position)
        self.plc.write_register(11, self.production_count)

    def _rotate_table(self):
        """分度旋转：前进一个工位"""
        self.table_moving = True
        self.table_position = (self.table_position + 1) % 4
        self.table_moving = False

    def _simulate_vision(self):
        """模拟视觉检测结果"""
        import random
        return random.random() < self.vision_pass_rate

    def _simulate_screw(self):
        """模拟锁螺丝结果"""
        import random
        return random.random() < self.screw_torque_rate

    def _simulate_glue(self):
        """模拟点胶结果"""
        import random
        return random.random() < self.glue_volume_rate

    def _simulate_inspection(self):
        """模拟成品检测结果"""
        import random
        return random.random() < self.inspect_pass_rate

    def _simulate_infeed(self):
        """模拟来料到位"""
        return True

    def _do_vision(self):
        pass  # 视觉拍照（模拟，不改变物理世界）

    def _do_screw(self):
        pass  # 螺丝刀动作

    def _do_glue(self):
        pass  # 点胶动作

    def _do_inspection(self):
        pass  # 检测探头动作

    def _sort_ok(self):
        self.production_count += 1

    def _sort_ng(self):
        self.ng_count += 1

    def _sound_alarm(self):
        pass


# ==================== Webots 入口 ====================
if __name__ == "__main__":
    bridge = WebotsBridge()
    print("Webots Bridge 启动（模拟模式）")
    for _ in range(100):
        bridge.step()
    plc = bridge.plc
    print(f"\n100 个周期运行完成:")
    print(f"  产量: {bridge.production_count}")
    print(f"  不良品: {bridge.ng_count}")
    print(f"  操作日志: {len(plc.history)} 条")
    plc.print_history(last_n=10)
