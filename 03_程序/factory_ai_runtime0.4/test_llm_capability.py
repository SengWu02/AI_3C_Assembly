# -*- coding: utf-8 -*-
"""LLM 能力实测 —— 确认 gemma3:4b 能不能稳定完成我们要的活

为什么必须先测：
    4B 模型能力有限。它可能：
      - 输出一堆解释文字，不按 JSON 格式回
      - JSON 键名写错 / 少键
      - 胡编数据（幻觉）
      - 遇到"调整节拍"这种要判断的事，给出离谱的值
    所以先把真实 prompt 拿去跑几遍，看它到底稳不稳。

测三个任务（对应它在串行生产里真正要干的三件事）：
    任务1  产量目标解析   "今天做50个" -> {"target": 50}
    任务2  产线状态评估   良率/效率/事件 -> JSON 决策
    任务3  异常判断       "料卡住了"这类事件能不能识别出来

用法：先确认 ollama 在跑，然后
      python test_llm_capability.py
约 2 分钟（每个任务跑 3 遍，看稳定性）。
"""

import json
import time

import requests

from config import LLM_MODEL, LLM_BASE_URL


def call_llm(prompt, use_json_format=True, timeout=60):
    """调用 ollama 一次，返回 (原始文本, 耗时秒, 错误)"""
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    if use_json_format:
        payload["format"] = "json"
    t0 = time.time()
    try:
        r = requests.post(LLM_BASE_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json().get("response", ""), time.time() - t0, None
    except Exception as e:
        return "", time.time() - t0, str(e)


def task1_target():
    """任务1：解析产量目标"""
    print("")
    print("=" * 72)
    print("任务1：产量目标解析")
    print("=" * 72)
    cases = ["做50个", "今天先来3件试试", "生产 20 个就够了"]
    ok = 0
    for c in cases:
        prompt = (
            "你是一个3C组装岛调度系统。\n"
            "你的任务是从人类的指令中，提取出需要生产的目标数量。\n"
            f"指令：\"{c}\"\n"
            "请输出一个 JSON 对象，包含键 \"target\" (整数)。\n"
            "不要输出任何其他解释文字。\n"
            "示例: {\"target\": 50}\n"
        )
        txt, dt, err = call_llm(prompt)
        if err:
            print(f"  ✗ \"{c}\"  -> 调用失败: {err}")
            continue
        try:
            v = json.loads(txt)
            t = int(v.get("target", -1))
            print(f"  ✓ \"{c}\"  -> target={t}   ({dt:.1f}s)")
            ok += 1
        except Exception as e:
            print(f"  ✗ \"{c}\"  -> JSON 解析失败: {e}")
            print(f"      原始输出: {txt[:150]}")
    print(f"  ── 任务1 成功 {ok}/{len(cases)}")
    return ok, len(cases)


def task2_assess():
    """任务2：产线状态评估（这是它主要要干的活）"""
    print("")
    print("=" * 72)
    print("任务2：产线状态评估 -> JSON 决策")
    print("=" * 72)

    scenario = {
        "production": "12/50",
        "alarm": False,
        "ai_score": 85,
        "stations": [
            "  工位1(视觉检测): 通过12/12 良率100.0%",
            "  工位2(锁螺丝):   通过12/12 良率100.0%",
            "  工位3(点胶):     通过12/12 良率100.0%",
            "  工位4(成品检测): 通过9/12 良率75.0%",
        ],
        "overall_yield": 93.8,
        "efficiency": 1.2,
        "cycle": 3.0,
        "events": [
            {"type": "LOW_EFFICIENCY", "message": "产能下降"},
        ],
    }

    prompt = (
        "你是3C组装岛的线长。当前生产状态：\n\n"
        f"产量: {scenario['production']}  报警: 否  AI评分: {scenario['ai_score']}\n\n"
        "各工位:\n" + "\n".join(scenario["stations"]) + "\n\n"
        f"总体良率: {scenario['overall_yield']}%  效率: {scenario['efficiency']} 件/分钟  "
        f"当前节拍: {scenario['cycle']}秒\n\n"
        "近期事件:\n" + json.dumps(scenario["events"], ensure_ascii=False, indent=2) + "\n\n"
        "请分析产线状态，输出一个 JSON 决策（不要输出其他文字）:\n"
        "{\n"
        '  "assessment": "正常/需要优化/异常",\n'
        '  "actions": [],\n'
        '  "adjustments": {}\n'
        "}\n"
        "actions 可选值: rotate / alarm_on / alarm_off / stop / continue\n"
        "adjustments 可选: cycle_time（生产节拍秒数，范围1.0~10.0）\n"
    )

    ok = 0
    for i in range(3):
        txt, dt, err = call_llm(prompt)
        if err:
            print(f"  第{i+1}遍 ✗ 调用失败: {err}")
            continue
        try:
            d = json.loads(txt)
            a = d.get("assessment")
            acts = d.get("actions")
            adj = d.get("adjustments")
            good = (a in ("正常", "需要优化", "异常") and isinstance(acts, list)
                    and isinstance(adj, dict))
            mark = "✓" if good else "△"
            print(f"  第{i+1}遍 {mark} assessment={a!r} actions={acts} adjustments={adj}  ({dt:.1f}s)")
            if good:
                ok += 1
        except Exception as e:
            print(f"  第{i+1}遍 ✗ JSON 解析失败: {e}")
            print(f"      原始输出: {txt[:200]}")
    print(f"  ── 任务2 格式正确 {ok}/3")
    return ok, 3


def task3_anomaly():
    """任务3：异常识别（良率骤降时能不能看出来）"""
    print("")
    print("=" * 72)
    print("任务3：异常识别（良率从 100% 掉到 33%）")
    print("=" * 72)
    _ev = json.dumps([
        {"type": "LOW_YIELD", "message": "良率低于阈值"},
        {"type": "LOW_EFFICIENCY", "message": "产能下降"},
    ], ensure_ascii=False, indent=2)

    _lines = [
        "你是3C组装岛的线长。当前生产状态：",
        "",
        "产量: 30/50  报警: 是  AI评分: 40",
        "",
        "各工位:",
        "  工位1(视觉检测): 通过30/30 良率100.0%",
        "  工位2(锁螺丝):   通过30/30 良率100.0%",
        "  工位3(点胶):     通过30/30 良率100.0%",
        "  工位4(成品检测): 通过10/30 良率33.3%",
        "",
        "总体良率: 83.3%  效率: 0.8 件/分钟  当前节拍: 3.0秒",
        "",
        "近期事件:",
        _ev,
        "",
        "请判断: 哪个工位是问题源头？应该采取什么动作？",
        "输出 JSON（不要输出其他文字）:",
        "{",
        '  "assessment": "正常/需要优化/异常",',
        '  "suspect_station": 工位编号(整数),',
        '  "reason": "简短原因",',
        '  "actions": []',
        "}",
    ]
    prompt = "\n".join(_lines)
    ok = 0
    for i in range(3):
        txt, dt, err = call_llm(prompt)
        if err:
            print(f"  第{i+1}遍 ✗ 调用失败: {err}")
            continue
        try:
            d = json.loads(txt)
            a = d.get("assessment")
            s = d.get("suspect_station")
            r = d.get("reason", "")
            right = (a == "异常" and str(s) == "4")
            mark = "✓" if right else "△"
            print(f"  第{i+1}遍 {mark} assessment={a!r} 怀疑工位={s} 原因={r[:40]!r}  ({dt:.1f}s)")
            if right:
                ok += 1
        except Exception as e:
            print(f"  第{i+1}遍 ✗ JSON 解析失败: {e}")
            print(f"      原始输出: {txt[:200]}")
    print(f"  ── 任务3 正确识别工位4 {ok}/3")
    return ok, 3


def main():
    print("=" * 72)
    print(f"LLM 能力实测   model={LLM_MODEL}")
    print(f"              url={LLM_BASE_URL}")
    print("=" * 72)

    # 先确认连得上
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=8)
        names = [m["name"] for m in r.json().get("models", [])]
        # ★ 大小写不敏感比较：config 里写的是 gemma3:4B，ollama 里实际是 gemma3:4b
        if LLM_MODEL.lower() not in [n.lower() for n in names]:
            print(f"  ★ 模型 {LLM_MODEL} 不在已安装列表里！")
            print(f"    已安装: {names}")
            print(f"    装法: ollama pull {LLM_MODEL}")
            return
        print(f"  ✓ 模型已安装")
    except Exception as e:
        print(f"  ★ 连不上 ollama: {e}")
        print("    先启动: ollama serve")
        return

    tot_ok = tot_all = 0
    for fn in (task1_target, task2_assess, task3_anomaly):
        o, a = fn()
        tot_ok += o
        tot_all += a

    print("")
    print("=" * 72)
    print(f"总计：{tot_ok}/{tot_all} 通过")
    print("=" * 72)
    print("判读：")
    print("  * 大部分 ✓  -> gemma3:4b 够用，可以激活它做线长")
    print("  * 大量 ✗    -> 它连 JSON 都出不来，需要换模型或简化 prompt")
    print("  * 格式对但内容胡编（△）-> 它能干活但不能做决策，只让它做【描述】")
    print("     （比如总结日志、生成日报），不要让它控制产线")


if __name__ == "__main__":
    main()
