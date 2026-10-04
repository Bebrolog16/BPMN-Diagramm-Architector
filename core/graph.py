from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class BPMNNode:
    id: str
    name: str
    type: str
    parent_id: Optional[str] = None
    level: int = 0
    coords: Tuple[float, float] = (0.0, 0.0)
    width: float = 100.0
    height: float = 80.0
    process_id: Optional[str] = None


@dataclass
class BPMNEdge:
    source: str
    target: str
    label: Optional[str] = None
    condition: Optional[str] = None
    flow_type: str = "sequence"


@dataclass
class BPMNLane:
    id: str
    name: str
    pool_id: str
    order: int


@dataclass
class BPMNPool:
    id: str
    name: str
    process_id: str
    parent_id: Optional[str]
    lane_ids: List[str]


class BPMNGraph:
    def __init__(self, root_process_id: str = "process_root"):
        self.nodes: Dict[str, BPMNNode] = {}
        self.edges: List[BPMNEdge] = []
        self.processes: Dict[str, str] = {root_process_id: "Main Process"}
        self.pools: Dict[str, BPMNPool] = {}
        self.lanes: Dict[str, BPMNLane] = {}
        self.lane_map: Dict[str, str] = {}
        self.process_pool: Dict[str, str] = {}
        self.root_process_id = root_process_id
        self.root_participant_id = "Participant_root"
        self.process_bounds: Dict[str, Tuple[float, float, float, float]] = {}
        self.pool_bounds: Dict[str, Tuple[float, float, float, float]] = {}
        self.lane_bounds: Dict[str, Tuple[float, float, float, float]] = {}

    def add_process(self, process_id: str, name: str, pool_id: Optional[str] = None) -> None:
        self.processes[process_id] = name
        if pool_id:
            self.process_pool[process_id] = pool_id

    def add_pool(
        self,
        pool_id: str,
        lane_ids: List[str],
        lane_names: Optional[List[str]] = None,
        process_id: Optional[str] = None,
        name: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> None:
        lane_names = lane_names or lane_ids
        if len(lane_names) != len(lane_ids):
            raise ValueError("lane_ids and lane_names must have the same length")
        process_id = process_id or f"process_{pool_id.removeprefix('pool_')}"
        pool_name = name or (", ".join(lane_names) if lane_names else "Participant")
        pool = BPMNPool(pool_id, pool_name, process_id, parent_id, lane_ids)
        self.pools[pool_id] = pool
        self.add_process(process_id, pool_name, pool_id)
        for order, (lane_id, lane_name) in enumerate(zip(lane_ids, lane_names)):
            lane = BPMNLane(lane_id, lane_name, pool_id, order)
            self.lanes[lane_id] = lane
            self.lane_map[lane_id] = pool_id

    def process_for_parent(self, parent_id: Optional[str]) -> str:
        if parent_id in self.lanes:
            return self.pools[self.lanes[parent_id].pool_id].process_id
        if parent_id in self.pools:
            return self.pools[parent_id].process_id
        if parent_id in self.processes:
            return parent_id
        if parent_id in self.nodes:
            return self.nodes[parent_id].process_id or self.root_process_id
        return self.root_process_id

    def add_node(self, node: BPMNNode) -> None:
        if node.process_id is None:
            node.process_id = self.process_for_parent(node.parent_id)
        self.nodes[node.id] = node

    def add_edge(
        self,
        source: str,
        target: str,
        label: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"Unknown edge endpoint: {source!r} -> {target!r}")
        flow_node_types = {
            "start", "end", "task", "userTask", "scriptTask",
            "exclusiveGateway", "parallelGateway", "inclusiveGateway", "subprocess",
        }
        if self.nodes[source].type not in flow_node_types or self.nodes[target].type not in flow_node_types:
            raise ValueError("Sequence and message flows must connect BPMN flow nodes")
        source_process = self.nodes[source].process_id
        target_process = self.nodes[target].process_id
        flow_type = "sequence" if source_process == target_process else "message"
        if flow_type == "message" and condition:
            raise ValueError("Message flows cannot have sequence-flow conditions")
        self.edges.append(BPMNEdge(source, target, label, condition, flow_type))
