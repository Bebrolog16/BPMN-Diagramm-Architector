import os

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b-instruct")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api/generate")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
MAX_GENERATION_ATTEMPTS = int(os.getenv("MAX_GENERATION_ATTEMPTS", "3"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "final_result.bpmn")
DATA_DIR = os.path.abspath(os.getenv("BPMN_DATA_DIR", os.path.join(PROJECT_ROOT, "data")))
DATABASE_FILE = os.path.join(DATA_DIR, "bpmn_architect.sqlite3")
GENERATED_DIR = os.path.join(DATA_DIR, "generated")
