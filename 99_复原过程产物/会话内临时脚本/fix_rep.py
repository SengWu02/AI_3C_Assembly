import re
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 定位到"# ========== 生产一个产品 =========="第一次出现
idx1 = content.find('# ========== 生产一个产品 ==========')
# 定位到第二次出现
idx2 = content.find('# ========== 生产一个产品 ==========', idx1 + 50)

if idx2 > 0:
    # 从idx1到idx2之间的内容是重复的，删掉第二个函数定义
    new_content = content[:idx2] + content[idx2:].replace(
        "# ========== 生产一个产品 ==========\ndef produce_one(modbus_client, station_stats):\n    \"\"\"执行一次完整生产循环\"\"\"\n    global production_count\n\n    is_ok = random.random() < 0.85\n\n",
        "",
        1
    )
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('OK')
else:
    print('未找到重复')
