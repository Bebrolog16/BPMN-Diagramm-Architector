import uuid

from core.graph import BPMNGraph, BPMNNode


class DiagramSDK:
    def __init__(self):
        self.graph = BPMNGraph()
        self.ROOT_PROCESS_ID = self.graph.root_process_id
        self.ROOT_START_TASK_ID = "start_event_root"
        self.ROOT_END_TASK_ID = "end_event_root"
        self.graph.add_node(BPMNNode(self.ROOT_START_TASK_ID, "Start", "start", self.ROOT_PROCESS_ID))
        self.graph.add_node(BPMNNode(self.ROOT_END_TASK_ID, "End", "end", self.ROOT_PROCESS_ID))

    def _generate_id(self, prefix):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def add_pool(self, process_id, lane_names, name=None):
        if not isinstance(lane_names, (list, tuple)) or not lane_names:
            raise ValueError("A pool must have at least one named lane")
        pool_id = self._generate_id("pool")
        process_ref = self._generate_id("process")
        lane_ids = [self._generate_id("lane") for _ in lane_names]
        self.graph.add_pool(
            pool_id,
            lane_ids,
            lane_names=[str(lane_name) for lane_name in lane_names],
            process_id=process_ref,
            name=name,
            parent_id=process_id,
        )
        return pool_id, lane_ids

    def add_task(self, name, parent_id):
        node_id = self._generate_id("task")
        self.graph.add_node(BPMNNode(node_id, str(name), "task", parent_id))
        return node_id

    def add_user_task(self, name, parent_id):
        node_id = self._generate_id("user_task")
        self.graph.add_node(BPMNNode(node_id, str(name), "userTask", parent_id))
        return node_id

    def add_script_task(self, name, parent_id):
        node_id = self._generate_id("script_task")
        self.graph.add_node(BPMNNode(node_id, str(name), "scriptTask", parent_id))
        return node_id

    def add_start_event(self, name, parent_id):
        node_id = self._generate_id("start_event")
        self.graph.add_node(BPMNNode(node_id, str(name), "start", parent_id))
        return node_id

    def add_end_event(self, name, parent_id):
        node_id = self._generate_id("end_event")
        self.graph.add_node(BPMNNode(node_id, str(name), "end", parent_id))
        return node_id

    def add_exclusive_gateway(self, name, parent_id):
        node_id = self._generate_id("ex_gateway")
        self.graph.add_node(BPMNNode(node_id, str(name), "exclusiveGateway", parent_id))
        return node_id

    def add_parallel_gateway(self, name, parent_id):
        node_id = self._generate_id("par_gateway")
        self.graph.add_node(BPMNNode(node_id, str(name), "parallelGateway", parent_id))
        return node_id

    def add_inclusive_gateway(self, name, parent_id):
        node_id = self._generate_id("inc_gateway")
        self.graph.add_node(BPMNNode(node_id, str(name), "inclusiveGateway", parent_id))
        return node_id

    def add_link(self, source_id, target_id, label=None, condition=None):
        self.graph.add_edge(source_id, target_id, label=label, condition=condition)

    def add_subprocess(self, name, parent_id):
        node_id = self._generate_id("subprocess")
        self.graph.add_node(BPMNNode(node_id, str(name), "subprocess", parent_id))
        return node_id

    def add_group(self, name, parent_id):
        node_id = self._generate_id("group")
        self.graph.add_node(BPMNNode(node_id, str(name), "group", parent_id))
        return node_id
