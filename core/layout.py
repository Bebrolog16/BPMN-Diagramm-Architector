from collections import defaultdict, deque
from typing import DefaultDict, Dict, List, Tuple

from core.graph import BPMNGraph


class LayoutEngine:
    """Deterministic layered layout for process and lane diagrams."""

    X_STEP = 230.0
    ROW_GAP = 110.0
    LANE_MIN_HEIGHT = 150.0
    POOL_GAP = 75.0
    START_X = 100.0
    START_Y = 60.0
    POOL_PADDING_X = 48.0
    POOL_PADDING_Y = 36.0

    SIZES = {
        "start": (36.0, 36.0),
        "end": (36.0, 36.0),
        "exclusiveGateway": (50.0, 50.0),
        "parallelGateway": (50.0, 50.0),
        "inclusiveGateway": (50.0, 50.0),
        "task": (120.0, 80.0),
        "userTask": (120.0, 80.0),
        "scriptTask": (120.0, 80.0),
        "subprocess": (150.0, 100.0),
        "group": (200.0, 120.0),
    }

    def __init__(self, graph: BPMNGraph):
        self.graph = graph

    def calculate_layout(self):
        self._assign_levels()
        self._assign_coordinates()
        return self.graph

    def _assign_levels(self):
        if not self.graph.nodes:
            return

        root_start = self.graph.root_process_id
        start_id = next(
            (node.id for node in self.graph.nodes.values() if node.type == "start" and node.process_id == root_start),
            None,
        )
        levels: Dict[str, int] = {}
        queue = deque()
        start_ids = [
            node.id
            for node in self.graph.nodes.values()
            if node.type == "start"
        ]
        if start_id and start_id not in start_ids:
            start_ids.insert(0, start_id)
        for event_id in start_ids:
            levels[event_id] = 0
            queue.append(event_id)

        outgoing: DefaultDict[str, List[str]] = defaultdict(list)
        for edge in self.graph.edges:
            outgoing[edge.source].append(edge.target)

        while queue:
            current = queue.popleft()
            for target in outgoing[current]:
                if target not in levels:
                    levels[target] = levels[current] + 1
                    queue.append(target)

        next_level = max(levels.values(), default=-1) + 1
        for node in self.graph.nodes.values():
            if node.id not in levels:
                levels[node.id] = next_level
                next_level += 1
            node.level = levels[node.id]

    def _assign_coordinates(self):
        self.graph.process_bounds.clear()
        self.graph.pool_bounds.clear()
        self.graph.lane_bounds.clear()
        for node in self.graph.nodes.values():
            node.width, node.height = self.SIZES.get(node.type, (120.0, 80.0))

        process_bands = []
        y_cursor = self.START_Y
        for process_id in self.graph.processes:
            pool_id = self.graph.process_pool.get(process_id)
            lane_ids = self.graph.pools[pool_id].lane_ids if pool_id else []
            process_nodes = [node for node in self.graph.nodes.values() if node.process_id == process_id]

            if lane_ids:
                bands = []
                for lane_id in lane_ids:
                    lane_nodes = [node for node in process_nodes if node.parent_id == lane_id]
                    height = self._lane_height(lane_nodes)
                    bands.append((lane_id, lane_nodes, height))
                unassigned = [node for node in process_nodes if node.parent_id not in lane_ids]
                if unassigned:
                    bands.insert(0, (None, unassigned, self._lane_height(unassigned)))
            else:
                bands = [(None, process_nodes, self._lane_height(process_nodes))]

            process_top = y_cursor
            lane_top = y_cursor
            for lane_id, lane_nodes, height in bands:
                self._place_lane_nodes(lane_nodes, lane_top, height)
                if lane_id:
                    self.graph.lane_bounds[lane_id] = (
                        self.START_X - self.POOL_PADDING_X,
                        lane_top,
                        self._process_width(process_nodes),
                        height,
                    )
                lane_top += height

            process_height = max(lane_top - process_top, self.LANE_MIN_HEIGHT)
            pool_x = self.START_X - self.POOL_PADDING_X
            bounds = (pool_x, process_top, self._process_width(process_nodes), process_height)
            self.graph.process_bounds[process_id] = bounds
            if pool_id:
                self.graph.pool_bounds[pool_id] = bounds
            process_bands.append((process_id, process_top, process_height))
            y_cursor += process_height + self.POOL_GAP

    def _lane_height(self, nodes):
        if not nodes:
            return self.LANE_MIN_HEIGHT
        counts: DefaultDict[int, int] = defaultdict(int)
        for node in nodes:
            counts[node.level] += 1
        rows = max(counts.values(), default=1)
        return max(self.LANE_MIN_HEIGHT, 80.0 + self.ROW_GAP * (rows - 1) + 50.0)

    def _process_width(self, nodes):
        max_level = max((node.level for node in nodes), default=0)
        max_right = max(
            (self.START_X + node.level * self.X_STEP + node.width / 2 for node in nodes),
            default=self.START_X + 600,
        )
        return max(600.0, max_right - (self.START_X - self.POOL_PADDING_X) + self.POOL_PADDING_X)

    def _place_lane_nodes(self, nodes, lane_top, lane_height):
        groups: DefaultDict[int, List] = defaultdict(list)
        for node in nodes:
            groups[node.level].append(node)
        lane_center = lane_top + lane_height / 2
        for level, level_nodes in groups.items():
            count = len(level_nodes)
            for index, node in enumerate(level_nodes):
                center_x = self.START_X + level * self.X_STEP
                center_y = lane_center + (index - (count - 1) / 2) * self.ROW_GAP
                node.coords = (center_x - node.width / 2, center_y - node.height / 2)
