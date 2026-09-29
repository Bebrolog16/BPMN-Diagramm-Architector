from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import os
import sys

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.llm_client import OllamaBPMNClient
from core.executor import CodeExecutor
from core.prompts import SYSTEM_PROMPT

app = FastAPI()

# Config
MODEL_NAME = "qwen2.5-coder:7b-instruct"
OUTPUT_FILE = "final_result.bpmn"

class ProcessRequest(BaseModel):
    text: str

@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Dynamically calculate the path to index.html relative to this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(current_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/generate")
async def generate_bpmn(request: ProcessRequest):
    llm = OllamaBPMNClient(model_name=MODEL_NAME)
    executor = CodeExecutor(output_filename=OUTPUT_FILE)
    
    current_code = None
    last_error = None
    max_attempts = 3
    
    for attempt in range(1, max_attempts + 1):
        # Generate
        raw_response = llm.generate_code(request.text, previous_error=last_error, previous_code=current_code)
        if not raw_response:
            raise HTTPException(status_code=500, detail="Ollama failed to respond")
            
        current_code = llm.clean_code(raw_response)
        
        # Execute
        result = executor.execute(current_code)
        
        if result["success"]:
            try:
                with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                    xml_content = f.read()
                return {
                    "success": True, 
                    "xml": xml_content, 
                    "code": current_code, 
                    "file": OUTPUT_FILE
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error reading XML: {str(e)}")
        else:
            last_error = result["error"]
    
    raise HTTPException(status_code=500, detail=f"Max attempts reached. Last error: {last_error}")

@app.get("/download")
async def download_file():
    if os.path.exists(OUTPUT_FILE):
        return FileResponse(OUTPUT_FILE, filename="diagram.bpmn")
    raise HTTPException(status_code=404, detail="File not found")
