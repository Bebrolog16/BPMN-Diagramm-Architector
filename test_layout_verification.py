from core.graph import BPMNGraph, BPMNNode
from core.layout import LayoutEngine

def test_layout():
    graph = BPMNGraph()
    
    # Создаем пул с двумя дорожками
    pool_id = "pool_1"
    lane1 = "lane_1"
    lane2 = "lane_2"
    graph.add_pool(pool_id, [lane1, lane2])
    
    # Создаем узлы
    # Уровень 0
    start = BPMNNode("start_event_root", "Start", "start", lane1)
    graph.add_node(start)
    
    # Уровень 1: два узла в одной дорожке (проверка симметрии по Y)
    task1 = BPMNNode("task_1", "Task 1", "task", lane1)
    task2 = BPMNNode("task_2", "Task 2", "task", lane1)
    graph.add_node(task1)
    graph.add_node(task2)
    
    # Уровень 2: узел в другой дорожке
    task3 = BPMNNode("task_3", "Task 3", "task", lane2)
    graph.add_node(task3)
    
    # Уровень 3: финальный узел
    end = BPMNNode("end_event_root", "End", "end", lane1)
    graph.add_node(end)
    
    # Связи
    graph.add_edge("start_event_root", "task_1")
    graph.add_edge("start_event_root", "task_2")
    graph.add_edge("task_1", "task_3")
    graph.add_edge("task_2", "task_3")
    graph.add_edge("task_3", "end_event_root")
    
    # Запуск лейаута
    engine = LayoutEngine(graph)
    engine.calculate_layout()
    
    print(f"{'Node ID':<20} | {'Level':<6} | {'X':<10} | {'Y':<10} | {'Lane':<10}")
    print("-" * 60)
    for node_id, node in graph.nodes.items():
        print(f"{node_id:<20} | {node.level:<6} | {node.coords[0]:<10.2f} | {node.coords[1]:<10.2f} | {node.parent_id:<10}")

if __name__ == "__main__":
    test_layout()
