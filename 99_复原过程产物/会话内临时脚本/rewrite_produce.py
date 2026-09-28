with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_func_start = '''def produce_one(modbus_client, station_stats):
    """执行一次完整生产循环（按照用户流程）：

    流程：
      - 左来料视觉检查（VISION_0_INPUT）
      - 左皮带(BELT_0) + 发料(EMITTER) → 转盘A（带滚轮）转90° → 送料到中下皮带2(BELT_2)
      - 皮带2送料停止，机械臂1(ARM1)取料(X/Z/GRAB)，送至转盘B
      - 转盘B（带滚轮）转90° → 送料到右皮带3(BELT_3)
      - 右皮带3由视觉(VISION_1)判断OK/NG，NG由推杆(PUSHER_COIL)推出至NG仓，OK流向OK仓

    返回: bool 表示本件是否为 OK
    """
    global production_count

    # 默认结果为 NG，除非右侧视觉判断为 OK
    is_ok = False

    try:


        # 2) 来料入料：启动皮带0和发料器，把料送到转盘A
        print(">>> 左皮带+发料: 启动 BELT_0 & EMITTER")


        # 3) 使用转盘A滚轮配合转动，把料送至皮带2（转90°）
        print(">>> 转盘A: 滚轮 + 旋转90°，送料到皮带2")

        # 先给转盘一个旋转脉冲（模拟90°），等待限位或超时
        modbus_client.write_coil(TABLE_A_TURN_COIL, True)


        time.sleep(3)  # 确保转盘接收到旋转指令
        modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)
        modbus_client.write_coil(BELT_0_COIL, True)
        modbus_client.write_coil(EMITTER_COIL, True)
        time.sleep(4.0)  # 让料完全进入转盘
        modbus_client.write_coil(BELT_0_COIL, False)
        modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)
        time.sleep(0.5)  # 确保转盘停止后再启动滚轮
        modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)  # 转盘滚轮继续转动，确保送料到皮带2
        


        # 停止滚轮，开始皮带2以接收
        modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)

        # 启动皮带2，让料移动到机械臂取料位
        modbus_client.write_coil(BELT_2_COIL, True)
        time.sleep(1.2)
        modbus_client.write_coil(BELT_2_COIL, False)

        # 更新左侧工位统计（感应到来料视为一次产出尝试）
        s1 = station_stats.get(1)
        if s1 is None:
            station_stats[1] = {"name": "视觉检测", "ok": 0, "total": 0, "yield_pct": 100.0}
            s1 = station_stats[1]
        s1["total"] += 1

        time.sleep(0.3)

        # 4) 机械臂1 从皮带2 取料并送到转盘B
        print(">>> 机械臂1 取料并送到转盘B")
        # 停止皮带2以保证取料位置稳定（上面已停止）
        modbus_client.write_coil(ARM1_Z_COIL, True)    # Z 下
        time.sleep(1.2)
        modbus_client.write_coil(ARM1_GRAB_COIL, True) # 抓取
        time.sleep(0.4)
        modbus_client.write_coil(ARM1_Z_COIL, False)   # Z 上
        time.sleep(0.6)
        modbus_client.write_coil(ARM1_X_COIL, True)    # X 伸出到转盘B
        time.sleep(0.9)
        modbus_client.write_coil(ARM1_X_COIL, False)

        # 把料放到转盘B 并旋转90°送料到右皮带3
        modbus_client.write_coil(TABLE_B_TURN_COIL, True)
        if not _wait_input(modbus_client, TABLE_B_LIMIT_90_INPUT, True, timeout=5.0):
            time.sleep(TABLE_INDEX_TIME)
        modbus_client.write_coil(TABLE_B_TURN_COIL, False)

        # 放料动作
        modbus_client.write_coil(ARM1_Z_COIL, True)
        time.sleep(0.8)
        modbus_client.write_coil(ARM1_GRAB_COIL, False) # 放开
        time.sleep(0.3)
        modbus_client.write_coil(ARM1_Z_COIL, False)
        time.sleep(0.5)
        modbus_client.write_coil(ARM1_X_COIL, True)
        time.sleep(0.8)
        modbus_client.write_coil(ARM1_X_COIL, False)

        # 启动转盘B滚轮并送料到右皮带3
        modbus_client.write_coil(TABLE_B_ROLL_P_COIL, True)
        modbus_client.write_coil(BELT_3_COIL, True)
        time.sleep(1.2)
        modbus_client.write_coil(BELT_3_COIL, False)
        modbus_client.write_coil(TABLE_B_ROLL_P_COIL, False)

        # 5) 右侧视觉检测：判断 OK/NG
        print(">>> 右侧视觉检测 (VISION_1)")
        # 等待视觉传感器稳定
        if _wait_input(modbus_client, VISION_1_INPUT, True, timeout=2.0):
            # True 表示 OK
            print("右侧视觉判断: OK")
            is_ok = True
        else:
            print("右侧视觉判断: NG")
            is_ok = False

        # 6) 分拣：OK 保持，NG 推至 NG 仓（使用 PUSHER_COIL）
        sort_product(modbus_client, is_ok)

        # 更新最终检测站统计
        s4 = station_stats.get(4)
        if s4 is None:
            station_stats[4] = {"name": "成品检测", "ok": 0, "total": 0, "yield_pct": 100.0}
            s4 = station_stats[4]
        s4["total"] += 1
        if is_ok:
            s4["ok"] += 1
        s4["yield_pct"] = round(s4["ok"] / s4["total"] * 100, 1)

        production_count += 1
        return is_ok

    except Exception as e:
        print("produce_one 出错:", e)
        # 异常时尽量把设备置为安全状态
        try:
            modbus_client.write_coil(BELT_0_COIL, False)
            modbus_client.write_coil(BELT_2_COIL, False)
            modbus_client.write_coil(BELT_3_COIL, False)
            modbus_client.write_coil(TABLE_A_TURN_COIL, False)
            modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)
            modbus_client.write_coil(TABLE_B_TURN_COIL, False)
            modbus_client.write_coil(TABLE_B_ROLL_P_COIL, False)
            modbus_client.write_coil(ARM1_GRAB_COIL, False)
            modbus_client.write_coil(ARM1_X_COIL, False)
            modbus_client.write_coil(ARM1_Z_COIL, False)
            modbus_client.write_coil(EMITTER_COIL, False)
            modbus_client.write_coil(PUSHER_COIL, False)
        except Exception:
            pass
        return False'''

new_func = '''def produce_one(modbus_client, station_stats):
    """执行一次完整生产循环"""
    global production_count

    is_ok = False

    # ====== 步骤1: 转盘A接料 + 回0° + 送到皮带2 ======
    print(">>> 步骤1: 转盘A转90°接料 → 回0° → 送料到皮带2")

    # 转盘A转90°到接料位
    modbus_client.write_coil(TABLE_A_TURN_COIL, True)
    if not _wait_input(modbus_client, TABLE_A_LIMIT_90_INPUT, True, timeout=8.0):
        time.sleep(5.0)
    modbus_client.write_coil(TABLE_A_TURN_COIL, False)

    # 开滚轮+皮带1+发料，送料进转盘中心
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)
    modbus_client.write_coil(BELT_0_COIL, True)
    modbus_client.write_coil(EMITTER_COIL, True)
    time.sleep(4.0)

    # 停滚轮+皮带1+发料
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, False)
    modbus_client.write_coil(BELT_0_COIL, False)
    modbus_client.write_coil(EMITTER_COIL, False)
    time.sleep(0.5)

    # 转盘A回0°
    modbus_client.write_coil(TABLE_A_TURN_COIL, True)
    if not _wait_input(modbus_client, TABLE_A_LIMIT_0_INPUT, True, timeout=8.0):
        time.sleep(5.0)
    modbus_client.write_coil(TABLE_A_TURN_COIL, False)

    # 开滚轮送料到皮带2
    modbus_client.write_coil(TABLE_A_ROLL_P_COIL, True)
    time.sleep(2.0)

    # 更新工位1统计
    s1 = station_stats.get(1)
    if s1 is None:
        station_stats[1] = {"name": "视觉检测", "ok": 0, "total": 0, "yield_pct": 100.0}
        s1 = station_stats[1]
    s1["total"] += 1

    # ====== 步骤2: 皮带2送料到机械臂取料位 ======
    print(">>> 步骤2: 皮带2送料(2.3s)")
    modbus_client.write_coil(BELT_2_COIL, True)
    time.sleep(2.3)
    modbus_client.write_coil(BELT_2_COIL, False)
    time.sleep(0.3)

    # ====== 步骤3: 机械臂1搬运到转盘B ======
    print(">>> 步骤3: 机械臂1搬运到转盘B")
    modbus_client.write_coil(ARM1_Z_COIL, True)        # Z下
    time.sleep(1.2)
    modbus_client.write_coil(ARM1_GRAB_COIL, True)     # 抓
    time.sleep(0.5)
    modbus_client.write_coil(ARM1_Z_COIL, False)       # Z上
    time.sleep(1.0)
    modbus_client.write_coil(ARM1_X_COIL, True)        # X伸
    time.sleep(1.0)

    # 转盘B转90°等待放料
    modbus_client.write_coil(TABLE_B_TURN_COIL, True)
    if not _wait_input(modbus_client, TABLE_B_LIMIT_90_INPUT, True, timeout=8.0):
        time.sleep(5.0)
    modbus_client.write_coil(TABLE_B_TURN_COIL, False)

    modbus_client.write_coil(ARM1_X_COIL, False)
    modbus_client.write_coil(ARM1_Z_COIL, True)        # Z下放料
    time.sleep(1.0)
    modbus_client.write_coil(ARM1_GRAB_COIL, False)    # 放
    time.sleep(0.5)
    modbus_client.write_coil(ARM1_Z_COIL, False)       # Z上
    time.sleep(0.5)
    modbus_client.write_coil(ARM1_X_COIL, True)        # X回
    time.sleep(1.0)
    modbus_client.write_coil(ARM1_X_COIL, False)

    # ====== 步骤4: 转盘B送料到皮带3（右视觉位） ======
    print(">>> 步骤4: 转盘B送料到皮带3")
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, True)
    modbus_client.write_coil(BELT_3_COIL, True)
    time.sleep(3.0)
    modbus_client.write_coil(TABLE_B_ROLL_P_COIL, False)
    modbus_client.write_coil(BELT_3_COIL, False)
    time.sleep(0.5)

    # ====== 步骤5: 右侧视觉检测 ======
    print(">>> 步骤5: 视觉检测 (VISION_1)")
    if _wait_input(modbus_client, VISION_1_INPUT, True, timeout=3.0):
        print("→ OK")
        is_ok = True
    else:
        print("→ NG")
        is_ok = False

    # ====== 步骤6: 分拣 ======
    sort_product(modbus_client, is_ok)

    # 更新工位4统计
    s4 = station_stats.get(4)
    if s4 is None:
        station_stats[4] = {"name": "成品检测", "ok": 0, "total": 0, "yield_pct": 100.0}
        s4 = station_stats[4]
    s4["total"] += 1
    if is_ok:
        s4["ok"] += 1
    s4["yield_pct"] = round(s4["ok"] / s4["total"] * 100, 1)

    production_count += 1
    return is_ok'''

if old_func_start in content:
    content = content.replace(old_func_start, new_func, 1)
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('替换成功')
else:
    print('未找到旧的函数体')
