import subprocess
import sys
import os
from core.diagram import DiagramSDK
from core.layout import LayoutEngine
from core.exporter import BPMNExporter

class CodeExecutor:
    """
    Safe executor for LLM-generated BPMN code.
    It executes the code in a restricted environment to prevent RCE.
    """
    def __init__(self, output_filename="result.bpmn"):
        self.output_filename = output_filename

    def execute(self, code: str):
        """
        Executes the provided python code with a restricted set of globals.
        """
        # Restricted globals to prevent access to dangerous modules
        safe_globals = {
            "DiagramSDK": DiagramSDK,
            "LayoutEngine": LayoutEngine,
            "BPMNExporter": BPMNExporter,
            "__builtins__": {
                "print": print,
                "range": range,
                "len": len,
                "list": list,
                "dict": dict,
                "str": str,
                "int": int,
                "float": float,
                "tuple": tuple,
                "set": set,
                "bool": bool,
            }
        }
        
        # Create a closure to capture the output_filename
        def create_exporter_class(out_path):
            class WrapperExporter(BPMNExporter):
                def export(self, path):
                    # Override the path with the one we want
                    super().export(out_path)
            return WrapperExporter

        safe_globals["BPMNExporter"] = create_exporter_class(self.output_filename)

        local_vars = {}
        try:
            # Execute the code
            exec(code, safe_globals, local_vars)
            return {"success": True, "output": self.output_filename, "error": None}
        except Exception as e:
            return {"success": False, "output": None, "error": str(e)}
