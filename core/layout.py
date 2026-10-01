from typing import Dict, List, Tuple, Set
from core.graph import BPMNGraph, BPMNNode

class LayoutEngine:
    def __init__(self, graph: BPMNGraph):
        self.graph = graph
        self.X_STEP = 140.0        # Balanced step
        self.LANE_HEIGHT = 100.0   # Compact lanes
        self.POOL_GAP = 20.0
        self.START_X = 40.0
        self.START_Y = 40.0

        # Node sizes (Width, Height)
        self.SIZES = {
            'start': (36.0, 36.0),
            'end': (36.0, 36.0),
            'exclusiveGateway': (50.0, 50.0),
            'parallelGateway': (50.0, 50.0),
            'inclusiveGateway': (50.0, 50.0),
            'task': (100.0, 80.0),
            'userTask': (100.0, 80.0),
            'scriptTask': (100.0, 80.0),
            'subprocess': (150.0, 100.0),
            'group': (200.0, 200.0)
        }

    def calculate_layout(self):
        """Main entry point for coordinate calculation"""
        # 1. Identify edges that are 'back-edges' (cycles) to exclude them from level calculation
        self._identify_back_edges()
        # 2. Assign levels based ONLY on forward edges
        self._assign_levels()
        # 3. Assign coordinates based on levels and lanes
        self._assign_coordinates()

    def _identify_back_edges(self):
        """Identifies edges that point to a node already visited in the main flow."""
        self.back_edges: Set[Tuple[str, str]] = set()
        start_node_id = "start_event_root"
        if start_node_id not in self.graph.nodes:
            return

        visited = set()
        stack = set()
        
        def dfs(u):
            visited.add(u)
            stack.add(u)
            for edge in self.graph.edges:
                if edge.source == u:
                    v = edge.target
                    if v in stack:
                        # Found a back-edge (cycle)
                        self.back_edges.add((u, v))
                    elif v not in visited:
                        dfs(v)
            stack.remove(u)

        dfs(start_node_id)

    def _assign_levels(self):
        """Determine X-levels using BFS on forward edges only."""
        levels: Dict[str, int] = {}
        start_node_id = "start_event_root"
        if start_node_id not in self.graph.nodes:
            return

        raw_levels: Dict[str, int] = {node_id: 0 for node_id in self.graph.nodes}
        queue = [(start_node_id, 0)]
        visited = {start_node_id}

        while queue:
            node_id, level = queue.pop(0)
            raw_levels[node_id] = level

            for edge in self.graph.edges:
                # CRITICAL: Ignore back-edges during level assignment to keep main flow linear
                if edge.source == node_id and edge.target not in visited:
                    if (edge.source, edge.target) not in getattr(self, 'back_edges', set()):
                        visited.add(edge.target)
                        queue.append((edge.target, level + 1))

        # Compact levels to remove empty columns
        sorted_raw_levels = sorted(list(set(raw_levels.values())))
        level_map = {raw: i for i, raw in enumerate(sorted_raw_levels)}

        for node_id, node in self.graph.nodes.items():
            node.level = level_map.get(raw_levels[node_id], 0)

    def _assign_coordinates(self):
        """Calculates X and Y using a layered approach with lane constraints."""
        pool_y_offsets: Dict[str, float] = {}
        current_y_offset = self.START_Y
        for pool_id, lanes in self.graph.pools.items():
            pool_y_offsets[pool_id] = current_y_offset
            pool_height = len(lanes) * self.LANE_HEIGHT
            current_y_offset += pool_height + self.POOL_GAP

        lane_y_centers: Dict[str, float] = {}
        for pool_id, lanes in self.graph.pools.items():
            base_y = pool_y_offsets[pool_id]
            for i, lane_id in enumerate(lanes):
                lane_y_centers[lane_id] = base_y + (i * self.LANE_HEIGHT) + (self.LANE_HEIGHT / 2)

        buckets: Dict[Tuple[int, str], List[str]] = {}
        for node_id, node in self.graph.nodes.items():
            key = (node.level, node.parent_id if node.parent_id else "root")
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(node_id)

        level_max_widths: Dict[int, float] = {}
        for (level, lane_id), node_ids in buckets.items():
            for nid in node_ids:
                node = self.graph.nodes[nid]
                w, h = self.SIZES.get(node.type, (100.0, 80.0))
                node.width, node.height = w, h
                level_max_widths[level] = max(level_max_widths.get(level, 0.0), w)

        abs_x_positions: Dict[int, float] = {}
        current_abs_x = self.START_X
        sorted_levels = sorted(level_max_widths.keys())
        
        if sorted_levels:
            first_lvl = sorted_levels[0]
            first_w = level_max_widths[first_lvl]
            abs_x_positions[first_lvl] = current_abs_x + (first_w / 2)
            current_abs_x += first_w
            
            for i in range(1, len(sorted_levels)):
                lvl = sorted_levels[i]
                curr_w = level_max_widths[lvl]
                gap = 40.0 
                abs_x_positions[lvl] = current_abs_x + (gap / 2) + (curr_w / 2)
                current_abs_x += gap + curr_w

        for (level, lane_id), node_ids in buckets.items():
            max_h = 0.0
            for nid in node_ids:
                node = self.graph.nodes[nid]
                max_h = max(max_h, node.height)

            center_x = abs_x_positions.get(level, self.START_X + (level * self.X_STEP))
            center_y = lane_y_centers.get(lane_id, self.START_Y + (self.LANE_HEIGHT / 2))

            count = len(node_ids)
            spacing = 20.0
            total_stack_height = (count - 1) * (max_h + spacing)
            start_y = center_y - (total_stack_height / 2)

            for i, node_id in enumerate(node_ids):
                node = self.graph.nodes[node_id]
                node_x = center_x - (node.width / 2)
                slot_center_y = start_y + i * (max_h + spacing) + (max_h / 2)
                node_y = slot_center_y - (node.height / 2)
                node.coords = (node_x, node_y)
