import requests
import json
from core.prompts import SYSTEM_PROMPT

class OllamaBPMNClient:
    def __init__(self, model_name="llama3", base_url="http://localhost:11434/api/generate"):
        self.model_name = model_name
        self.base_url = base_url

    def generate_code(self, user_text, previous_error=None, previous_code=None):
        """
        Sends a request to Ollama to generate Python code for BPMN.
        If an error is provided, it asks the model to fix the code.
        """
        prompt = f"{SYSTEM_PROMPT}\n\nUser request: {user_text}"
        
        if previous_error and previous_code:
            prompt += f"\n\nYour previous code failed with error: {previous_error}\nPrevious code:\n{previous_code}\n\nPlease fix the code and provide ONLY the corrected Python code block."

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json" # We can try to force JSON or just clean the output
        }
        
        # Since we want raw code, we'll use the standard endpoint but 
        # we'll instruct the model to output only the code block.
        # Note: 'format': 'json' in Ollama requires the prompt to explicitly ask for JSON.
        # For raw code, we'll remove the JSON format and clean the output.
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False
        }

        try:
            print(f"Sending request to Ollama (model: {self.model_name})...")
            response = requests.post(self.base_url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result.get("response", "").strip()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error connecting to Ollama: {e}")
            if e.response.status_code == 404:
                print("Check if the Ollama server is running. The endpoint /api/generate might be wrong or the server is not responding correctly.")
            return None
        except Exception as e:
            print(f"Unexpected error connecting to Ollama: {e}")
            return None

    def clean_code(self, response):
        """
        Removes markdown code blocks (```python ... ```) from the LLM response.
        """
        code = response
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]
        return code.strip()
