import os
import sys

# --- Configuration ---
MODEL_NAME = "llama3.2:3b"
OUTPUT_FILE = "final_result.bpmn"
# ---------------------

# Add project root to sys.path for imports to work
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.llm_client import OllamaBPMNClient
from core.executor import CodeExecutor

def log(message, level="INFO"):
    """Prints formatted logs with colors."""
    colors = {
        "INFO": "\033[94m",    # Blue
        "SUCCESS": "\033[92m", # Green
        "ERROR": "\033[91m",   # Red
        "WARN": "\033[93m",    # Yellow
        "RESET": "\033[0m"
    }
    print(f"{colors.get(level, '')}[{level}] {message}{colors['RESET']}")

def run_bpmn_pipeline(user_text):
    """Main pipeline: User Text -> LLM -> Sandbox Execution -> BPMN File."""
    log(f"Processing request: {user_text}", "INFO")
    
    llm = OllamaBPMNClient(model_name=MODEL_NAME)
    executor = CodeExecutor(output_filename=OUTPUT_FILE)
    
    current_code = None
    last_error = None
    max_attempts = 3
    
    for attempt in range(1, max_attempts + 1):
        log(f"Attempt {attempt}/{max_attempts}...", "INFO")
        
        # 1. Generate code from LLM
        raw_response = llm.generate_code(user_text, previous_error=last_error, previous_code=current_code)
        if not raw_response:
            log("Failed to get response from Ollama.", "ERROR")
            return None
            
        current_code = llm.clean_code(raw_response)
        
        print("\n" + "="*30 + " GENERATED CODE " + "="*30)
        print(current_code)
        print("="*74 + "\n")
        
        # 2. Execute code in sandbox
        result = executor.execute(current_code)
        
        if result["success"]:
            log(f"BPMN file generated successfully: {result['output']}", "SUCCESS")
            try:
                with open(result["output"], "r", encoding="utf-8") as f:
                    content = f.read(200)
                    print(f"\nXML Preview (first 200 chars):\n{content}...")
            except Exception as e:
                log(f"Could not read output file: {e}", "WARN")
            return result["output"]
        else:
            last_error = result["error"]
            log(f"Execution failed: {last_error}", "ERROR")
            log("Requesting LLM to fix the code...", "INFO")
            
    log("Could not generate working code after max attempts.", "ERROR")
    return None

if __name__ == "__main__":
    print("\n" + "*"*50)
    print(" BPMN AI Assistant - Powered by Ollama & Qwen")
    print("*"*50)
    
    while True:
        try:
            user_input = input("\nDescribe your process (or 'exit' to quit): ").strip()
            if not user_input:
                continue
            if user_input.lower() in ['exit', 'quit']:
                break
            
            run_bpmn_pipeline(user_input)
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            break

    print("\nGoodbye!")
