import time
from config import *
from modbus_client import FactoryModbusClient

print("连接 PLC...")
modbus_client = FactoryModbusClient(MODBUS_HOST, MODBUS_PORT)
connected = modbus_client.connect()
if not connected:
    print("连接失败")
    exit()

print("连接成功\n")

# 测试流程：开皮带3送料 → 等视觉触发 → 推杆推出
print("=== 视觉+推杆联动测试 ===")
print("开皮带3送料...")
modbus_client.write_coil(BELT_3_COIL, True)

# 等待视觉触发（NC逻辑：False = NG）
print("等待视觉触发（超时10秒）...")
start = time.time()
detected = False
while time.time() - start < 10:
    val = modbus_client.read_input(VISION_1_INPUT)
    if val == False:
        print(f"视觉触发！读到 False（NG）")
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
else:
    print("超时未触发，当前视觉值:", modbus_client.read_input(VISION_1_INPUT))
    modbus_client.write_coil(BELT_3_COIL, False)

modbus_client.close()
print("\n完成")
