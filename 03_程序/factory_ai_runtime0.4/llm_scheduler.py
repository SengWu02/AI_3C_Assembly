import requests
import json


class LLMScheduler:

    def __init__(self):

        self.url = "http://localhost:11434/api/generate"
        self.model = "phi3.5:latest "

    def analyze_and_suggest(self, status_data):

        """
        输入当前产线状态，LLM 返回调度建议。

        status_data 示例:
        {
            "line1": {"setpoint_ppm": 10.0, "current_ppm": 8.5, "speed_output": 7},
            "line2": {"setpoint_ppm": 5.0, "current_ppm": 5.2, "speed_output": 6},
            "events": [...]
        }
        """

        prompt = f"""你是一个工业生产线智能调度专家。

当前产线状态：
{json.dumps(status_data, ensure_ascii=False, indent=2)}

请根据以下规则分析并给出调度建议：

1. 如果实际产能持续低于目标产能的 80%，建议加速或检查异常
2. 如果产能超过 120%，建议减速（避免卡料）
3. 如果出现 BLOCK_DETECTED 或 PUSH_TIMEOUT，建议先处理异常再调速
4. 如果有异常，建议优先级：停线 > 减速 > 维持 > 加速

请严格按照以下 JSON 格式输出：

{{"line1_action": "accelerate/decelerate/maintain/stop", "line2_action": "accelerate/decelerate/maintain/stop", "reason": "简要说明"}}

其中 action 含义：
- accelerate: 建议加速（提高目标产能或允许PID上限）
- decelerate: 建议减速
- maintain: 维持当前速度
- stop: 建议停线检查
"""

        try:

            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }

            response = requests.post(
                self.url,
                json=payload,
                timeout=15
            )

            response.raise_for_status()

            result = response.json()

            decision = json.loads(result["response"])

            return decision

        except Exception as e:

            print("LLM调度分析失败:", e)

            return {
                "line1_action": "maintain",
                "line2_action": "maintain",
                "reason": "LLM分析失败，维持当前速度"
            }
