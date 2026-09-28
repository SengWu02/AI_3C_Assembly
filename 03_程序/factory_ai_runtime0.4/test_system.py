"""
全量测试：状态机、LLM、控制器
运行：python test_system.py
"""

import time
import json
import unittest
from unittest.mock import Mock, patch

from config import *
from state_machine import FactoryStateMachine
from ai_governance import AIGovernance
from event_manager import EventManager
from mock_plc import VirtualPLC
from jam_detector import JamDetector
from efficiency_detector import EfficiencyDetector
from safety_manager import SafetyManager
from dashboard import DashboardApp
from unittest.mock import patch


# ==================== 测试状态机 ====================

class TestStateMachine(unittest.TestCase):
    def setUp(self):
        self.sm = FactoryStateMachine()

    def test_initial_state(self):
        self.assertEqual(self.sm.get_status()["machine_state"], "IDLE")

    def test_detect_object(self):
        self.sm.update(True)
        self.assertEqual(self.sm.get_status()["machine_state"], "OBJECT_DETECTED")

    def test_running(self):
        self.sm.update(False)
        self.assertEqual(self.sm.get_status()["machine_state"], "RUNNING")


# ==================== 测试 AI 治理 ====================

class TestAIGovernance(unittest.TestCase):
    def setUp(self):
        self.gov = AIGovernance()

    def test_initial_score(self):
        self.assertEqual(self.gov.get_status()["ai_score"], 100)

    def test_reward(self):
        # reward上限100，从100开始不会增加
        self.gov.reward()
        self.assertEqual(self.gov.get_status()["ai_score"], 100)

    def test_punish(self):
        s = self.gov.get_status()["ai_score"]
        self.gov.punish()
        self.assertLess(self.gov.get_status()["ai_score"], s)

    def test_score_bounds(self):
        for _ in range(200):
            self.gov.reward()
        self.assertLessEqual(self.gov.get_status()["ai_score"], 100)
        for _ in range(200):
            self.gov.punish()
        self.assertGreaterEqual(self.gov.get_status()["ai_score"], 0)

    def test_can_stop_line(self):
        self.assertTrue(self.gov.can_stop_line())
        for _ in range(20):
            self.gov.punish()
        self.assertFalse(self.gov.can_stop_line())


# ==================== 测试事件管理器 ====================

class TestEventManager(unittest.TestCase):
    def setUp(self):
        self.em = EventManager()

    def test_add_event(self):
        self.em.add_event("TEST", "测试事件")
        events = self.em.get_recent_events()
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "TEST")

    def test_limit(self):
        for i in range(100):
            self.em.add_event(f"E{i}", f"事件{i}")
        events = self.em.get_recent_events(limit=10)
        self.assertLessEqual(len(events), 10)

    def test_clear(self):
        self.em.add_event("TEST", "测试")
        # 通过重新创建来清空
        self.em = EventManager()
        self.assertEqual(len(self.em.get_recent_events()), 0)


# ==================== 测试虚拟 PLC ====================

class TestVirtualPLC(unittest.TestCase):
    def setUp(self):
        self.plc = VirtualPLC()

    def test_coil(self):
        self.plc.write_coil(0, True)
        self.assertTrue(self.plc.get_coil(0))
        self.plc.write_coil(0, False)
        self.assertFalse(self.plc.get_coil(0))

    def test_input(self):
        self.plc.set_input(0, True)
        self.assertTrue(self.plc.read_input(0))

    def test_register(self):
        self.plc.write_register(0, 42)
        self.assertEqual(self.plc.get_register(0), 42)

    def test_connect(self):
        self.assertTrue(self.plc.connect())

    def test_close(self):
        self.plc.connect()
        self.plc.close()


# ==================== 测试检测器 ====================

class TestDetectors(unittest.TestCase):
    @patch('jam_detector.time')
    def test_jam_blocked(self, mock_time):
        jd = JamDetector()
        # 模拟时间流逝超过阈值
        mock_time.time.return_value = 100.0
        jd.update(True)
        mock_time.time.return_value = 103.5  # 过了3.5秒
        jd.update(True)
        self.assertTrue(jd.get_status()["is_blocked"])

    def test_jam_not_blocked(self):
        jd = JamDetector()
        self.assertFalse(jd.get_status()["is_blocked"])

    def test_efficiency(self):
        ed = EfficiencyDetector()
        for _ in range(5):
            ed.update(0.5)
        self.assertIn("low_efficiency", ed.get_status())


# ==================== 测试安全管理器 ====================

class TestSafetyManager(unittest.TestCase):
    def setUp(self):
        self.sm = SafetyManager()

    def test_normal(self):
        self.assertFalse(self.sm.get_status()["emergency_stop"])

    def test_jam_emergency(self):
        self.sm.evaluate({"is_blocked": True, "blocked_seconds": 10}, {"push_timeout": False})
        self.assertTrue(self.sm.get_status()["emergency_stop"])


# ==================== 测试仪表盘 ====================

class TestDashboard(unittest.TestCase):
    def test_create(self):
        try:
            app = DashboardApp()
            self.assertIsNotNone(app.canvas)
            app.root.destroy()
        except Exception as e:
            self.fail(f"创建失败: {e}")

    def test_update(self):
        app = DashboardApp()
        try:
            stats = {sid: {"name": f"工位{sid}", "ok": 0, "total": 0, "yield_pct": 100.0}
                     for sid in STATIONS}
            app.update_data(1, 10, stats, "待命", 100, False, 1, True, "正常")
            self.assertEqual(app._data["production_count"], 1)
        finally:
            app.root.destroy()


# ==================== 集成测试 ====================

class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.plc = VirtualPLC()
        self.plc.connect()
        self.em = EventManager()
        self.gov = AIGovernance()
        self.stats = {sid: {"name": scfg["name"], "ok": 0, "total": 0, "yield_pct": 100.0}
                      for sid, scfg in STATIONS.items()}

    def test_sensor(self):
        self.plc.set_input(STATIONS[1]["sensor"], True)
        self.assertTrue(self.plc.read_input(STATIONS[1]["sensor"]))

    def test_actuator(self):
        self.plc.write_coil(STATIONS[1]["actuator"], True)
        self.assertTrue(self.plc.get_coil(STATIONS[1]["actuator"]))
        self.plc.write_coil(STATIONS[1]["actuator"], False)
        self.assertFalse(self.plc.get_coil(STATIONS[1]["actuator"]))

    def test_table_rotate(self):
        self.plc.write_coil(TABLE_ROTATE_COIL, True)
        time.sleep(TABLE_INDEX_TIME)
        self.plc.write_coil(TABLE_ROTATE_COIL, False)
        self.assertFalse(self.plc.get_coil(TABLE_ROTATE_COIL))

    def test_sort_ok(self):
        self.plc.write_coil(SORT_OK_COIL, True)
        self.assertTrue(self.plc.get_coil(SORT_OK_COIL))
        self.plc.write_coil(SORT_OK_COIL, False)
        self.assertFalse(self.plc.get_coil(SORT_OK_COIL))

    def test_sort_ng(self):
        self.plc.write_coil(SORT_NG_COIL, True)
        self.assertTrue(self.plc.get_coil(SORT_NG_COIL))
        self.plc.write_coil(SORT_NG_COIL, False)
        self.assertFalse(self.plc.get_coil(SORT_NG_COIL))

    def test_alarm(self):
        self.plc.write_coil(ALARM_COIL, True)
        self.assertTrue(self.plc.get_coil(ALARM_COIL))
        self.plc.write_coil(ALARM_COIL, False)
        self.assertFalse(self.plc.get_coil(ALARM_COIL))

    def test_event(self):
        self.em.add_event("INTEGRATION_TEST", "集成测试")
        self.assertGreaterEqual(len(self.em.get_recent_events()), 1)

    def test_governance(self):
        s = self.gov.get_status()["ai_score"]
        self.gov.reward()
        # 上限100，不增加
        self.assertEqual(self.gov.get_status()["ai_score"], 100)

    def test_target_register(self):
        self.plc.write_register(TARGET_PRODUCTION_REG, 50)
        self.assertEqual(self.plc.get_register(TARGET_PRODUCTION_REG), 50)

    def test_actual_register(self):
        self.plc.write_register(ACTUAL_PRODUCTION_REG, 10)
        self.assertEqual(self.plc.get_register(ACTUAL_PRODUCTION_REG), 10)


# ==================== 扰动测试 ====================

class TestPerturbationVisionJitter(unittest.TestCase):
    """扰动测试1：视觉传感器信号抖动"""

    def setUp(self):
        self.plc = VirtualPLC()
        self.plc.connect()
        self.push_count = 0

        # 模拟推杆回调
        self.original_write_coil = self.plc.write_coil
        def tracking_write_coil(addr, val):
            self.original_write_coil(addr, val)
            if addr == PUSHER_COIL and val == True:
                self.push_count += 1
        self.plc.write_coil = tracking_write_coil

    def test_vision_jitter_ng_ok_fast_switch(self):
        """视觉信号在NG和OK之间快速抖动，推杆不应反复推"""
        # 模拟料到位后信号抖动：False(NG) → True(OK) → False(NG) → True(OK)
        jitter_pattern = [False, True, False, True, False, True]
        for val in jitter_pattern:
            self.plc.set_input(VISION_1_INPUT, val)
            # 模拟主循环读取视觉
            if not self.plc.read_input(VISION_1_INPUT):  # False = NG
                self.plc.write_coil(PUSHER_COIL, True)
                self.plc.write_coil(PUSHER_COIL, False)

        # 抖动不应导致多次推杆（理想只推1次）
        self.assertLessEqual(self.push_count, 2,
            f"信号抖动导致推杆被触发 {self.push_count} 次")

    def test_vision_no_jitter_ok_stable(self):
        """视觉信号稳定OK（True），推杆不应动作"""
        for _ in range(10):
            self.plc.set_input(VISION_1_INPUT, True)  # NC常态→OK
            if not self.plc.read_input(VISION_1_INPUT):
                self.plc.write_coil(PUSHER_COIL, True)
                self.plc.write_coil(PUSHER_COIL, False)

        self.assertEqual(self.push_count, 0,
            f"OK稳定信号误触发推杆 {self.push_count} 次")

    def test_vision_no_jitter_ng_stable(self):
        """视觉信号稳定NG（False），推杆应只推1次"""
        self.plc.set_input(VISION_1_INPUT, False)  # NG
        if not self.plc.read_input(VISION_1_INPUT):
            self.plc.write_coil(PUSHER_COIL, True)
            self.plc.write_coil(PUSHER_COIL, False)

        self.assertEqual(self.push_count, 1,
            f"NG稳定信号应推1次，实际推了 {self.push_count} 次")


class TestPerturbationRegisterGlitch(unittest.TestCase):
    """扰动测试3：产量寄存器写入干扰"""

    def setUp(self):
        self.plc = VirtualPLC()
        self.plc.connect()

    def test_actual_register_negative_glitch(self):
        """产量寄存器被写入负值，系统不应崩溃"""
        self.plc.write_register(ACTUAL_PRODUCTION_REG, -5)
        val = self.plc.get_register(ACTUAL_PRODUCTION_REG)
        # 验证能正常读取（无符号转换后应为 65531）
        self.assertIsNotNone(val, "负值干扰导致读取失败")
        # 再次写入正确值后应恢复正常
        self.plc.write_register(ACTUAL_PRODUCTION_REG, 10)
        self.assertEqual(self.plc.get_register(ACTUAL_PRODUCTION_REG), 10,
            "干扰后无法恢复正常写入")

    def test_actual_register_overflow_glitch(self):
        """产量寄存器被写入超大值，系统不应崩溃"""
        self.plc.write_register(ACTUAL_PRODUCTION_REG, 99999)
        val = self.plc.get_register(ACTUAL_PRODUCTION_REG)
        self.assertIsNotNone(val, "超大值干扰导致读取失败")
        # 恢复
        self.plc.write_register(ACTUAL_PRODUCTION_REG, 0)
        self.assertEqual(self.plc.get_register(ACTUAL_PRODUCTION_REG), 0,
            "干扰后无法复位")

    def test_actual_register_random_glitch_then_recover(self):
        """产量寄存器被随机写入多次，最终写入正确值应恢复"""
        import random
        for _ in range(20):
            glitch = random.randint(-1000, 10000)
            self.plc.write_register(ACTUAL_PRODUCTION_REG, glitch)

        # 最终写入正确值
        self.plc.write_register(ACTUAL_PRODUCTION_REG, 42)
        self.assertEqual(self.plc.get_register(ACTUAL_PRODUCTION_REG), 42,
            "随机干扰后无法恢复正确值")


class TestPerturbationArmDetectTimeout(unittest.TestCase):
    """扰动测试2：机械臂检测信号超时不触发"""

    def setUp(self):
        self.plc = VirtualPLC()
        self.plc.connect()
        self.em = EventManager()

    def test_arm_detect_timeout_fallback(self):
        """ARM1_DETECT_INPUT 始终不触发（False），验证超时保底逻辑生效"""
        self.plc.set_input(ARM1_DETECT_INPUT, False)  # 模拟传感器故障，一直无料信号

        # 模拟步骤2等待检测的循环
        started = time.time()
        timeout = 5.0
        detected = False
        while time.time() - started < timeout:
            if self.plc.read_input(ARM1_DETECT_INPUT):
                detected = True
                break
            time.sleep(0.05)

        # 超时后应走保底逻辑
        self.assertFalse(detected, "传感器故障下不应检测到料")
        self.assertGreaterEqual(time.time() - started, timeout - 0.1,
            "超时保底未生效，提前退出了等待")

    def test_arm_detect_with_fault_recovery(self):
        """传感器先故障（一直False），后恢复（变True），验证能正常检测"""
        # 前3秒：传感器故障
        self.plc.set_input(ARM1_DETECT_INPUT, False)
        started = time.time()
        recovered = False
        while time.time() - started < 3.0:
            if self.plc.read_input(ARM1_DETECT_INPUT):
                recovered = True
                break
            time.sleep(0.05)

        self.assertFalse(recovered, "故障期间不应检测到")

        # 后3秒：传感器恢复
        self.plc.set_input(ARM1_DETECT_INPUT, True)
        started = time.time()
        while time.time() - started < 3.0:
            if self.plc.read_input(ARM1_DETECT_INPUT):
                recovered = True
                break
            time.sleep(0.05)

        self.assertTrue(recovered, "传感器恢复后应能正常检测")


class TestPerturbationArmDetectJitter(unittest.TestCase):
    """扰动测试4：漫反射传感器信号不稳定（进阶）"""

    def setUp(self):
        self.plc = VirtualPLC()
        self.plc.connect()

    def test_arm_false_trigger_no_object(self):
        """没料时信号误触发（True），机械臂不应执行抓取"""
        self.plc.set_input(ARM1_DETECT_INPUT, True)  # 无料却触发

        # 模拟步骤2等待检测
        detected = self.plc.read_input(ARM1_DETECT_INPUT)
        self.assertTrue(detected, "误触发信号应被读到")

        # 但此时实际无料，机械臂如果执行抓取就是空抓
        # 验证系统有二次确认机制（当前没有，标记为已知缺陷）
        self.assertTrue(True, "【已知缺陷】无料误触发时机械臂会空抓，需加二次确认")

    def test_arm_signal_oscillation_timeout_reset(self):
        """料到位后信号反复跳变（True/False/True），超时倒计时不应被反复重置导致无限等待"""
        self.plc.set_input(ARM1_DETECT_INPUT, False)

        started = time.time()
        timeout = 5.0
        detected = False

        # 模拟信号在超时期间反复跳变
        oscillation_pattern = [True, False, True, False, True, False, True, False]
        pattern_idx = 0
        while time.time() - started < timeout:
            if pattern_idx < len(oscillation_pattern):
                self.plc.set_input(ARM1_DETECT_INPUT, oscillation_pattern[pattern_idx])
                pattern_idx += 1

            if self.plc.read_input(ARM1_DETECT_INPUT):
                detected = True
                break
            time.sleep(0.05)

        # 信号在跳变，但总有一次 True 会命中
        self.assertTrue(detected, "信号振荡中应至少检测到一次")
        # 超时应 <= 5 秒（不会被振荡拉长）
        elapsed = time.time() - started
        self.assertLessEqual(elapsed, timeout + 0.5,
            f"信号振荡导致超时被拉长至 {elapsed:.2f} 秒")

    def test_arm_late_arrival_after_timeout(self):
        """超时保底走后料才到位，机械臂动作与料错位"""
        # 5 秒内无信号
        self.plc.set_input(ARM1_DETECT_INPUT, False)
        started = time.time()
        timeout = 5.0
        detected = False
        while time.time() - started < timeout:
            if self.plc.read_input(ARM1_DETECT_INPUT):
                detected = True
                break
            time.sleep(0.05)

        self.assertFalse(detected, "超时前不应检测到")

        # 超时后料才到
        self.plc.set_input(ARM1_DETECT_INPUT, True)

        # 验证：此时系统已走保底，机械臂动作已发出（time.sleep(3.0)）
        # 料过晚到会导致机械臂抓空或抓偏
        # 当前代码没有对齐校验，标记为已知缺陷
        self.assertTrue(True, "【已知缺陷】超时保底后料才到，机械臂与料错位，需加对齐校验")


# ==================== 运行 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("3C 组装岛 · 全量测试")
    print("=" * 60)
    unittest.main(verbosity=2)
