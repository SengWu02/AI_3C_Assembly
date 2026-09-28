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

# 测试吸嘴
print("=== 测试 1: 开吸嘴 ===")
modbus_client.write_coil(ARM1_GRAB_COIL, True)
time.sleep(2.0)
print("关吸嘴")
modbus_client.write_coil(ARM1_GRAB_COIL, False)

print("\n=== 测试 2: 吸嘴+Z下 ===")
modbus_client.write_coil(ARM1_GRAB_COIL, True)   # 先开吸嘴
time.sleep(0.5)
modbus_client.write_register(ARM1_Z_REG, 8400)    # Z下
time.sleep(2.0)
modbus_client.write_register(ARM1_Z_REG, 0)       # Z上
time.sleep(1.0)
modbus_client.write_coil(ARM1_GRAB_COIL, False)   # 关吸嘴

print("\n=== 测试 3: 只吸嘴等2秒 ===")
modbus_client.write_coil(ARM1_GRAB_COIL, True)
time.sleep(2.0)
print("检查 Factory IO 里吸嘴有没有吸？")
input("按回车继续...")
modbus_client.write_coil(ARM1_GRAB_COIL, False)

modbus_client.close()
print("\n完成")
