import requests
import json

from config import LLM_MODEL, LLM_BASE_URL


class LLMManager:

    def __init__(self):

        self.url = LLM_BASE_URL
        self.model = LLM_MODEL

    def analyze_factory(self, recent_events):

        prompt = f"""
你是一名工业AI生产管理者。

请分析以下工厂事件日志：

{json.dumps(recent_events, ensure_ascii=False, indent=2)}

规则：
1. 只分析工厂运行状态
2. 不要幻想
3. 回复简短
4. 如果出现 PUSH_TIMEOUT 或 BLOCK_DETECTED 属于严重异常
5. LOW_EFFICIENCY 属于产能下降

请输出：
- 当前状态
- 是否异常
- 管理建议
"""

        payload = {

            "model": self.model,

            "prompt": prompt,

            "stream": False
        }

        try:

            response = requests.post(
                self.url,
                json=payload,
                timeout=15
            )

            result = response.json()

            return result["response"]

        except Exception as e:

            return f"LLM调用失败: {e}"

