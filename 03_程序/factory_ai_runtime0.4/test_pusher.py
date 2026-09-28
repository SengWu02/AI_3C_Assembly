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

# 测试推杆
print("=== 推杆测试 ===")
print("推出...")
modbus_client.write_coil(PUSHER_COIL, True)
time.sleep(1)
print("收回...")
modbus_client.write_coil(PUSHER_COIL, False)
time.sleep(1)

print("再推出...")
modbus_client.write_coil(PUSHER_COIL, True)
time.sleep(1)
print("再收回...")
modbus_client.write_coil(PUSHER_COIL, False)

modbus_client.close()
print("\n完成")
