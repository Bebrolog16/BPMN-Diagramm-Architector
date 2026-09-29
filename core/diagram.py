import uuid
from core.graph import BPMNGraph, BPMNNode

class DiagramSDK:
    def __init__(self):
        self.graph = BPMNGraph()
        # Системные ID из ТЗ
        self.ROOT_PROCESS_ID = "process_root"
        self.ROOT_START_TASK_ID = "start_event_root"
        self.ROOT_END_TASK_ID = "end_event_root"
        
        # Инициализируем базовые узлы
        self.graph.add_node(BPMNNode(self.ROOT_START_TASK_ID, "Start", "start", self.ROOT_PROCESS_ID))
        self.graph.add_node(BPMNNode(self.ROOT_END_TASK_ID, "End", "end", self.ROOT_PROCESS_ID))

    def add_pool(self, process_id, lane_names):
        pool_id = f"pool_{uuid.uuid4().hex[:8]}"
        # В ТЗ сказано: <pool_id>, <pool_line_id_list> = DIAGRAM.add_pool(...)
        lane_ids = []
        for name in lane_names:
            lane_id = f"lane_{uuid.uuid4().hex[:8]}"
            # Дорожка в нашем графе может быть представлена как виртуальный узел или группа
            # Для простоты храним её в реестре пулов графа
            lane_ids.append(lane_id)
        
        self.graph.add_pool(pool_id, lane_ids)
        return pool_id, lane_ids

    def _generate_id(self, prefix):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def add_task(self, name, parent_id):
        node_id = self._generate_id("task")
        self.graph.add_node(BPMNNode(node_id, name, "task", parent_id))
        return node_id

    def add_user_task(self, name, parent_id):
        node_id = self._generate_id("user_task")
        self.graph.add_node(BPMNNode(node_id, name, "userTask", parent_id))
        return node_id

    def add_script_task(self, name, parent_id):
        node_id = self._generate_id("script_task")
        self.graph.add_node(BPMNNode(node_id, name, "scriptTask", parent_id))
        return node_id

    def add_exclusive_gateway(self, name, parent_id):
        node_id = self._generate_id("ex_gateway")
        self.graph.add_node(BPMNNode(node_id, name, "exclusiveGateway", parent_id))
        return node_id

    def add_parallel_gateway(self, name, parent_id):
        node_id = self._generate_id("par_gateway")
        self.graph.add_node(BPMNNode(node_id, name, "parallelGateway", parent_id))
        return node_id

    def add_inclusive_gateway(self, name, parent_id):
        node_id = self._generate_id("inc_gateway")
        self.graph.add_node(BPMNNode(node_id, name, "inclusiveGateway", parent_id))
        return node_id

    def add_link(self, source_id, target_id):
        self.graph.add_edge(source_id, target_id)

    def add_subprocess(self, name, parent_id):
        # Для первого этапа реализуем как группу или отдельный процесс
        node_id = self._generate_id("subprocess")
        self.graph.add_node(BPMNNode(node_id, name, "subprocess", parent_id))
        return node_id

    def add_group(self, name, parent_id):
        node_id = self._generate_id("group")
        self.graph.add_node(BPMNNode(node_id, name, "group", parent_id))
        return node_id
