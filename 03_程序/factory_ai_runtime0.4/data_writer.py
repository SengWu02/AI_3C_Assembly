"""
shared_data.json 写入工具

供 main.py 调用，每周期写入当前状态。
只写数据，不做逻辑判断。
"""

import json
import os

DATA_FILE = os.path.join(os.path.dirname(__file__), "shared_data.json")


def write_dashboard_data(
    production_count: int,
    target: int,
    station_stats: dict,
    llm_status: str,
    ai_score: int,
    alarm: bool,
    cycle: int,
):
    """将当前状态写入 shared_data.json"""

    # 把 station_stats 的 key 转成 str 以便 JSON 序列化
    stations = {}
    for sid, s in station_stats.items():
        stations[str(sid)] = {
            "ok": s.get("ok", 0),
            "total": s.get("total", 0),
            "yield_pct": round(s.get("yield_pct", 0.0), 1),
            "name": s.get("name", ""),
        }

    data = {
        "production_count": production_count,
        "target": target,
        "stations": stations,
        "llm_status": llm_status,
        "ai_score": ai_score,
        "alarm": alarm,
        "cycle": cycle,
    }

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass  # 写失败不阻塞主循环
