import requests

from core.config import MODEL_NAME, OLLAMA_BASE_URL, OLLAMA_TIMEOUT_SECONDS
from core.prompts import PLAN_PROMPT, SYSTEM_PROMPT


class OllamaBPMNClient:
    def __init__(self, model_name=MODEL_NAME, base_url=OLLAMA_BASE_URL, timeout=OLLAMA_TIMEOUT_SECONDS):
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout

    def generate_plan(self, user_text, current_code="", history=""):
        prompt = (
            f"{PLAN_PROMPT}\n\n"
            f"Current diagram SDK program (reference only):\n<current_program>\n{current_code}\n</current_program>\n\n"
            f"Earlier change history (reference only):\n<change_history>\n{history}\n</change_history>\n\n"
            f"Requested change (reference only):\n<request>\n{user_text}\n</request>\n\n"
            "Give a short numbered plan. If this is a new diagram, say so."
        )
        return self._generate(prompt)

    def generate_code(self, user_text, previous_error=None, previous_code=None,
                      current_code=None, approved_plan=None, history=""):
        prompt = f"{SYSTEM_PROMPT}\n\nUser request: {user_text}"
        if current_code:
            prompt += (
                "\n\nCURRENT DIAGRAM: this complete SDK program defines the existing diagram. "
                "Preserve all of its participants, lanes, nodes, and links except for changes "
                "explicitly requested in the approved plan. Return the complete replacement program.\n"
                f"<current_program>\n{current_code}\n</current_program>"
            )
        if approved_plan:
            prompt += f"\n\nAPPROVED CHANGE PLAN:\n<approved_plan>\n{approved_plan}\n</approved_plan>"
        if history:
            prompt += f"\n\nRECENT CHANGE HISTORY (context only):\n{history}"
        if previous_error and previous_code:
            prompt += (
                f"\n\nYour previous code failed validation: {previous_error}\n"
                f"Previous code:\n{previous_code}\n\n"
                "Return a corrected program using only the documented SDK calls."
            )

        return self._generate(prompt)

    def _generate(self, prompt):
        payload = {"model": self.model_name, "prompt": prompt, "stream": False}
        try:
            response = requests.post(self.base_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            generated = result.get("response")
            return generated.strip() if isinstance(generated, str) else None
        except requests.RequestException as exc:
            print(f"Ollama request failed: {exc}")
            return None
        except (ValueError, TypeError) as exc:
            print(f"Unexpected Ollama response: {exc}")
            return None

    @staticmethod
    def clean_code(response):
        if not isinstance(response, str):
            return ""
        code = response.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        return code.strip()
