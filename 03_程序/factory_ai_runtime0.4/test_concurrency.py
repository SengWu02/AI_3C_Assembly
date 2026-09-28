# -*- coding: utf-8 -*-
"""集成测试：Modbus 线程锁 + 事件转发到 GUI（激活 LLM 后最关键的两处改动）

不连现场 —— 用一个假的 Modbus 后端，验证：
  1) 多线程并发访问 Modbus 时，读写不会互相插队（锁生效）
  2) event_manager 的事件能正确转发到 GUI 日志栏
  3) GUI 的 set_step / log / update_data 能被其他线程安全调用
"""
import threading
import time

import config
from event_manager import EventManager

config.PROTOCOL = "virtual"          # 用虚拟后端，不连现场
from modbus_client import FactoryModbusClient

print("=" * 68)
print("集成测试：线程锁 + 事件转发")
print("=" * 68)

pass_n = 0
fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
        print(f"  OK    {name} {detail}")
    else:
        fail_n += 1
        print(f"  ★失败 {name} {detail}")


# ==================== 1. 锁是否存在 ====================
print("")
print("[1] Modbus 线程锁")
mc = FactoryModbusClient("127.0.0.1", 502)
check("客户端有 _lock 属性", hasattr(mc, "_lock"))
check("_lock 是可重入锁", type(mc._lock).__name__ == "RLock", f"({type(mc._lock).__name__})")

# ==================== 2. 并发读写不交错 ====================
print("")
print("[2] 并发读写（40 个线程 x 50 次）")

# 用一个会"记下进入/离开"的假后端，检查有没有两个线程同时在里面
inner = {"in": 0, "max_in": 0, "overlap": False}
inner_lock = threading.Lock()


def fake_read_input(address):
    with inner_lock:
        inner["in"] += 1
        if inner["in"] > 1:
            inner["overlap"] = True     # ★ 说明有两个线程同时进来了 = 锁没生效
        inner["max_in"] = max(inner["max_in"], inner["in"])
    time.sleep(0.0005)                  # 故意留一点时间让竞争暴露
    with inner_lock:
        inner["in"] -= 1
    return False


def fake_write_register(address, value):
    with inner_lock:
        inner["in"] += 1
        if inner["in"] > 1:
            inner["overlap"] = True
        inner["max_in"] = max(inner["max_in"], inner["in"])
    time.sleep(0.0005)
    with inner_lock:
        inner["in"] -= 1


class FakeBackend:
    read_input = staticmethod(fake_read_input)
    write_register = staticmethod(fake_write_register)
    read_input_register = staticmethod(lambda a: 0)
    read_register = staticmethod(lambda a: 0)
    read_inputs = staticmethod(lambda s, c: [False] * c)
    write_coil = staticmethod(lambda a, v: None)
    get_coil = staticmethod(lambda a: False)
    get_register = staticmethod(lambda a: 0)
    connect = staticmethod(lambda: True)
    close = staticmethod(lambda: None)


mc._backend = FakeBackend()


def worker():
    for _ in range(50):
        mc.read_input(0)
        mc.write_register(0, 100)


ts = [threading.Thread(target=worker) for _ in range(40)]
t0 = time.time()
for t in ts:
    t.start()
for t in ts:
    t.join()
dt = time.time() - t0
check("没有两个线程同时进后端", not inner["overlap"],
      f"(后端内最大并发数={inner['max_in']}, 4000 次访问耗时 {dt:.1f}s)")

# ==================== 3. 事件转发到 GUI ====================
print("")
print("[3] 事件管理器的日志接收器")
em = EventManager()
got = []
em.sink = lambda m: got.append(m)
em.add_event("TEST_A", "事件一")
em.add_event("LOW_EFFICIENCY", "产能下降")
check("事件已转发", len(got) == 2, f"(收到 {len(got)} 条)")
check("转发内容含类型+消息", got and "TEST_A" in got[0] and "事件一" in got[0])
check("事件本身也存下来了", len(em.events) == 2)

# sink 抛异常时不能影响主流程
em.sink = lambda m: (_ for _ in ()).throw(RuntimeError("故意炸"))
try:
    em.add_event("TEST_B", "sink 会炸")
    check("sink 抛异常不影响 add_event", True)
except Exception as e:
    check("sink 抛异常不影响 add_event", False, str(e))

# ==================== 4. 事件数量上限 ====================
print("")
print("[4] 事件列表不会无限增长")
em2 = EventManager()
for i in range(700):
    em2.add_event("SPAM", f"第{i}条")
check("事件数被限制在 500", len(em2.events) <= 500, f"(实际 {len(em2.events)})")

# ==================== 5. GUI 被其他线程调用 ====================
print("")
print("[5] GUI 方法能被其他线程安全调用")
try:
    from dashboard import DashboardApp
    app = DashboardApp()
    errs = []

    def gui_worker():
        try:
            for i in range(30):
                app.set_step((i % 5) + 1)
                app.log(f"线程日志 {i}")
                app.update_data(
                    production_count=i, target=50,
                    station_stats={4: {"name": "成品检测", "ok": i, "total": i + 1,
                                       "yield_pct": 90.0}},
                    llm_status="工作中", ai_score=80, alarm=False, cycle=i,
                    cycle_time=50.0, params={"LLM": "已激活"})
        except Exception as e:
            errs.append(str(e))

    th = [threading.Thread(target=gui_worker) for _ in range(3)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    # ★ 模拟主线程：把队列里的更新消费掉（真实运行时 _tick 每 200ms 做这事）
    app._drain_queue()
    app.root.update()
    check("3 个线程同时调 GUI 没报错", not errs, str(errs[:2]))
    check("队列被消费完", app._q.qsize() == 0, f"(剩 {app._q.qsize()})")
    check("日志收到了内容", len(app._log_lines) > 0, f"({len(app._log_lines)} 行)")
    check("节拍历史有记录", len(app._cycle_history) > 0, f"({len(app._cycle_history)} 条)")
    check("步骤已切换", app._cur_step != 0 or app._last_step_time > 0,
          f"(当前步骤 {app._cur_step})")
    app.root.destroy()
except Exception as e:
    check("GUI 多线程调用", False, str(e))

print("")
print("=" * 68)
print(f"结果: 通过 {pass_n} / 失败 {fail_n}")
print("=" * 68)