import os
import sys

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.llm_client import OllamaBPMNClient
from core.executor import CodeExecutor
from core.layout import LayoutEngine

def test_real_pipeline():
    # 1. Реальный текст запроса
    user_text = "Процесс заказа пиццы: Клиент делает заказ, оператор проверяет оплату. Если оплачено, повар готовит пиццу, иначе клиент доплачивает. В конце курьер доставляет заказ."
    
    print(f"Testing with: {user_text}")
    
    # 2. Инициализация компонентов (как в main.py)
    llm = OllamaBPMNClient(model_name="llama3.2:3b")
    executor = CodeExecutor(output_filename="test_real.bpmn")
    
    # 3. Генерация кода
    raw_response = llm.generate_code(user_text)
    if not raw_response:
        print("Error: No response from LLM")
        return
    
    code = llm.clean_code(raw_response)
    print("\n--- Generated Code ---\n", code, "\n--- End Code ---\n")
    
    # 4. Выполнение кода в песочнице
    # Мы перехватываем результат выполнения, чтобы проверить граф
    result = executor.execute(code)
    
    if not result["success"]:
        print(f"Execution failed: {result['error']}")
        return

    # Чтобы проверить координаты, нам нужно получить доступ к объекту графа.
    print("\nAnalyzing coordinates from generated code...")
    # Создаем локальную среду выполнения
    local_env = {}
    try:
        # Импортируем ВСЕ необходимые классы в локальную среду
        from core.diagram import DiagramSDK
        from core.graph import BPMNGraph
        from core.layout import LayoutEngine
        from core.exporter import BPMNExporter
        
        # Передаем классы в exec, чтобы код LLM мог их использовать
        exec_globals = {
            "DiagramSDK": DiagramSDK, 
            "BPMNGraph": BPMNGraph, 
            "LayoutEngine": LayoutEngine, 
            "BPMNExporter": BPMNExporter, 
            "__builtins__": __builtins__
        }
        exec(code, exec_globals, local_env)
        
        # Объект диаграммы может быть либо в local_env, либо в exec_globals (если создан через sdk = DiagramSDK())
        # В коде LLM обычно используется sdk = DiagramSDK(), поэтому ищем sdk в local_env
        diagram_obj = local_env.get('sdk')
        
        if diagram_obj and hasattr(diagram_obj, 'graph'):
            graph = diagram_obj.graph
            engine = LayoutEngine(graph)
            engine.calculate_layout()
            
            print(f"\n{'Node ID':<25} | {'Level':<6} | {'X':<10} | {'Y':<10} | {'Lane':<15}")
            print("-" * 75)
            for node_id, node in graph.nodes.items():
                print(f"{node_id:<25} | {node.level:<6} | {node.coords[0]:<10.2f} | {node.coords[1]:<10.2f} | {node.parent_id:<15}")
        else:
            print("Could not find diagram object (sdk) in executed code.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Analysis failed: {e}")

if __name__ == "__main__":
    test_real_pipeline()
