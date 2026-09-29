from typing import Dict, List, Tuple, Set
from core.graph import BPMNGraph, BPMNNode

class LayoutEngine:
    def __init__(self, graph: BPMNGraph):
        self.graph = graph
        self.X_STEP = 250.0
        self.LANE_HEIGHT = 150.0
        self.POOL_GAP = 50.0
        self.START_X = 100.0
        self.START_Y = 50.0
        
        # Node sizes based on type (Width, Height)
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
        self._assign_levels()
        self._assign_coordinates()

    def _assign_levels(self):
        """BFS to determine the X-level of each node"""
        levels: Dict[str, int] = {}
        start_node_id = "start_event_root" 
        if start_node_id not in self.graph.nodes:
            return

        queue = [(start_node_id, 0)]
        visited = {start_node_id}
        
        while queue:
            node_id, level = queue.pop(0)
            levels[node_id] = level
            
            for edge in self.graph.edges:
                if edge.source == node_id and edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, level + 1))
        
        for node_id, node in self.graph.nodes.items():
            node.level = levels.get(node_id, 0)

    def _assign_coordinates(self):
        """Calculates X and Y based on levels and pools/lanes"""
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

        occupancy: Dict[Tuple[int, str], int] = {}

        for node_id, node in self.graph.nodes.items():
            # Get size for this specific node type
            width, height = self.SIZES.get(node.type, (100.0, 80.0))
            node.width = width
            node.height = height
            
            # X coordinate (Centered on a vertical line)
            # Center_X = START_X + (level * X_STEP)
            # Node_X = Center_X - (width / 2)
            center_x = self.START_X + (node.level * self.X_STEP)
            node_x = center_x - (width / 2)
            
            # Y coordinate
            lane_id = node.parent_id
            if lane_id in lane_y_centers:
                center_y = lane_y_centers[lane_id]
            else:
                center_y = self.START_Y + (self.LANE_HEIGHT / 2)
            
            # Handle overlap (Stacking)
            key = (node.level, lane_id if lane_id else "root")
            count = occupancy.get(key, 0)
            occupancy[key] = count + 1
            
            # Shift Y if multiple nodes are at the same spot
            # Shift is relative to the center_y
            y_offset = (count - 0) * 110.0 
            
            # Node_Y = center_y + y_offset - (height / 2)
            node_y = center_y + y_offset - (height / 2)
            
            node.coords = (node_x, node_y)
