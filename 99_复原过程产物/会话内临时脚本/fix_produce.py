import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 produce_one 函数体，替换步骤1
old = '''# ========== 生产一个产品 ==========
def produce_one(modbus_client, station_stats):
    """执行一次完整生产循环"""
    global production_count

    is_ok = random.random() < 0.85

        # ---- 步骤1: 转盘A转90°(等5s到位) → 发料+皮带进料 ----
    print(">>> 步骤1: 转盘A转90°(5s) → 发料+皮带进料(3s)")
    modbus_client.write_coil(TABLE_A_TURN_COIL, True)
    time.sleep(5.0)
    modbus_client.write_coil(TABLE_A_TURN_COIL, False)
    modbus_client.write_coil(EMITTER_COs)")
    modbus_clientIL, True)
    modbus_client.write_coil(BELT_0_COIL, True)
    time.sleep(3.0)
    modbus_client.write_coil(EMIT.write_coil(TABLE_A_TURN_COIL, True)
    modbus_client.write_coil(EMITTER_COIL, True)
    modbus_client.write_coil(BELT_0_COIL, True)
    time.sleep(5.0)
    modbus_client.write_coil(TABLE_A_TURN_COIL, False)
    modbus_client.write_coil(EMITTER_COIL, False)
    modbus_client.write_coil(BELT_0_COIL, False)
    print("<<< 步骤1 完成\n")