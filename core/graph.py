from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any

@dataclass
class BPMNNode:
    id: str
    name: str
    type: str  # 'start', 'end', 'task', 'userTask', 'scriptTask', 'exclusiveGateway', 'parallelGateway', 'inclusiveGateway'
    parent_id: Optional[str] = None  # ID пула или дорожки
    level: int = 0
    coords: Tuple[float, float] = (0.0, 0.0)
    width: float = 100.0
    height: float = 80.0

@dataclass
class BPMNEdge:
    source: str
    target: str
    label: Optional[str] = None

class BPMNGraph:
    def __init__(self):
        self.nodes: Dict[str, BPMNNode] = {}
        self.edges: List[BPMNEdge] = []
        self.pools: Dict[str, List[str]] = {}  # {pool_id: [lane_id1, lane_id2]}
        self.lane_map: Dict[str, str] = {}     # {lane_id: pool_id}

    def add_node(self, node: BPMNNode):
        self.nodes[node.id] = node

    def add_edge(self, source: str, target: str, label: Optional[str] = None):
        self.edges.append(BPMNEdge(source, target, label))

    def add_pool(self, pool_id: str, lanes: List[str]):
        self.pools[pool_id] = lanes
        for lane in lanes:
            self.lane_map[lane] = pool_id
