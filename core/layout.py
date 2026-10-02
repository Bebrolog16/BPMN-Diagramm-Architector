from typing import Dict, List, Tuple, Set, Optional
from collections import deque
from core.graph import BPMNGraph, BPMNNode

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


class LayoutEngine:
    """Deterministic layered BPMN layout with separate edge routing."""

    def __init__(self, graph: BPMNGraph):
        self.graph = graph
        self.X_GAP = 80.0
        self.LANE_HEIGHT = 140.0
        self.POOL_GAP = 40.0
        self.START_X = 82.0
        self.START_Y = 40.0
        self.ROUTE_GAP = 24.0
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
            'group': (200.0, 200.0),
        }

    def calculate_layout(self):
        self._identify_back_edges()
        self._assign_levels()
        self._assign_coordinates()
        self._route_edges()
        # Store the complete result on the graph so the exporter cannot lose it.
        self.graph.layout_metadata = {
            'back_edges': set(self.back_edges),
            'edge_routes': dict(self.edge_routes),
        }

    def _identify_back_edges(self):
        self.back_edges: Set[Tuple[str, str]] = set()
        start = 'start_event_root'
        if start not in self.graph.nodes:
            return

        visited: Set[str] = set()
        active: Set[str] = set()

        outgoing: Dict[str, List[str]] = {}
        for edge in self.graph.edges:
            outgoing.setdefault(edge.source, []).append(edge.target)

        def dfs(u: str):
            visited.add(u)
            active.add(u)
            for v in outgoing.get(u, []):
                if v in active:
                    self.back_edges.add((u, v))
                elif v not in visited:
                    dfs(v)
            active.remove(u)

        dfs(start)

    def _forward_edges(self):
        backs = getattr(self, 'back_edges', set())
        return [e for e in self.graph.edges if (e.source, e.target) not in backs]

    def _assign_levels(self):
        """Longest-path ranks on the forward DAG, not BFS shortest-path ranks."""
        forward = self._forward_edges()
        outgoing: Dict[str, List[str]] = {nid: [] for nid in self.graph.nodes}
        indegree: Dict[str, int] = {nid: 0 for nid in self.graph.nodes}
        for e in forward:
            outgoing.setdefault(e.source, []).append(e.target)
            indegree[e.target] = indegree.get(e.target, 0) + 1

        # Kahn topological order. Unreachable nodes are appended deterministically.
        q = deque(sorted([n for n, d in indegree.items() if d == 0]))
        topo: List[str] = []
        while q:
            u = q.popleft()
            topo.append(u)
            for v in outgoing.get(u, []):
                indegree[v] -= 1
                if indegree[v] == 0:
                    q.append(v)

        # A malformed graph can still contain a non-back cycle. Keep it stable.
        for nid in self.graph.nodes:
            if nid not in topo:
                topo.append(nid)

        levels = {nid: 0 for nid in self.graph.nodes}
        for u in topo:
            for v in outgoing.get(u, []):
                levels[v] = max(levels.get(v, 0), levels[u] + 1)

        # Do not leave the mandatory End before reachable process nodes.
        max_level = max(levels.values(), default=0)
        # The mandatory End belongs at the end even in small unit tests where
        # it is not explicitly connected yet. This also prevents Start/End
        # from occupying the same coordinates.
        end_id = 'end_event_root'
        if end_id in self.graph.nodes:
            has_forward_incoming = any(
                e.target == end_id and (e.source, e.target) not in self.back_edges
                for e in forward
            )
            if not has_forward_incoming:
                levels[end_id] = max_level + 1

        for nid, node in self.graph.nodes.items():
            node.level = levels.get(nid, 0)

    def _lane_centers(self) -> Dict[str, float]:
        centers: Dict[str, float] = {}
        current = self.START_Y
        for pool_id, lanes in self.graph.pools.items():
            for i, lane_id in enumerate(lanes):
                centers[lane_id] = current + i * self.LANE_HEIGHT + self.LANE_HEIGHT / 2
            current += len(lanes) * self.LANE_HEIGHT + self.POOL_GAP
        return centers

    def _infer_lane(self, node_id: str, lane_centers: Dict[str, float]) -> Optional[str]:
        node = self.graph.nodes[node_id]
        if node.parent_id in lane_centers:
            return node.parent_id

        # Start/end are process-level nodes. Attach them visually to the nearest
        # lane used by their forward neighbourhood so a simple process is one line.
        if node_id == 'start_event_root':
            for e in self.graph.edges:
                if e.source == node_id and (e.source, e.target) not in self.back_edges:
                    lane = self._infer_lane(e.target, lane_centers)
                    if lane:
                        return lane
        if node_id == 'end_event_root':
            for e in reversed(self.graph.edges):
                if e.target == node_id and (e.source, e.target) not in self.back_edges:
                    lane = self._infer_lane(e.source, lane_centers)
                    if lane:
                        return lane
        return None

    def _assign_coordinates(self):
        lane_centers = self._lane_centers()
        node_lane: Dict[str, Optional[str]] = {
            nid: self._infer_lane(nid, lane_centers) for nid in self.graph.nodes
        }
        self.node_lane = node_lane

        # Set sizes first.
        for node in self.graph.nodes.values():
            node.width, node.height = self.SIZES.get(node.type, (100.0, 80.0))

        levels = sorted({n.level for n in self.graph.nodes.values()})
        level_width = {
            level: max((n.width for n in self.graph.nodes.values() if n.level == level), default=100.0)
            for level in levels
        }

        x_centers: Dict[int, float] = {}
        cursor = self.START_X
        for level in levels:
            width = level_width[level]
            x_centers[level] = cursor + width / 2
            cursor += width + self.X_GAP
        self.x_centers = x_centers

        # Stack nodes within the same level/lane around the lane center.
        buckets: Dict[Tuple[int, Optional[str]], List[str]] = {}
        for nid, node in self.graph.nodes.items():
            buckets.setdefault((node.level, node_lane[nid]), []).append(nid)

        for (level, lane), node_ids in buckets.items():
            center_x = x_centers[level]
            if lane is not None:
                center_y = lane_centers[lane]
            else:
                center_y = self.START_Y + self.LANE_HEIGHT / 2

            node_ids.sort(key=lambda nid: nid)
            heights = [self.graph.nodes[nid].height for nid in node_ids]
            total = sum(heights) + max(0, len(node_ids) - 1) * 30.0
            top = center_y - total / 2
            y = top
            for nid in node_ids:
                node = self.graph.nodes[nid]
                node.coords = (center_x - node.width / 2, y)
                y += node.height + 30.0

        # Separate gateway branches inside the same lane. A merge target keeps
        # the lane center; sibling branch nodes are shifted around it. This is
        # topology-driven and does not depend on node names.
        forward = self._forward_edges()
        incoming = {nid: 0 for nid in self.graph.nodes}
        for e in forward:
            incoming[e.target] = incoming.get(e.target, 0) + 1
        outgoing: Dict[str, List[str]] = {nid: [] for nid in self.graph.nodes}
        for e in forward:
            outgoing.setdefault(e.source, []).append(e.target)

        BRANCH_OFFSET = 45.0
        for gid, gateway in self.graph.nodes.items():
            if gateway.type not in {"exclusiveGateway", "parallelGateway", "inclusiveGateway"}:
                continue
            targets = [t for t in outgoing.get(gid, []) if t in self.graph.nodes]
            if len(targets) < 2:
                continue
            same_lane = [t for t in targets if node_lane.get(t) == node_lane.get(gid)]
            if len(same_lane) < 2:
                continue
            center = lane_centers.get(node_lane.get(gid), gateway.coords[1] + gateway.height / 2)
            merge_targets = [t for t in same_lane if incoming.get(t, 0) > 1]
            branch_targets = [t for t in same_lane if t not in merge_targets]
            if merge_targets:
                # Keep merge/continuation at the main line.
                for tid in merge_targets:
                    n = self.graph.nodes[tid]
                    n.coords = (n.coords[0], center - n.height / 2)
                offsets = [BRANCH_OFFSET * (i + 1) for i in range(len(branch_targets))]
                # Alternate below/above to keep the main line readable.
                signed = []
                for i, off in enumerate(offsets):
                    signed.append(off if i % 2 == 0 else -off)
            else:
                mid = (len(same_lane) - 1) / 2
                signed = [(i - mid) * BRANCH_OFFSET * 2 for i in range(len(same_lane))]
            for tid, off in zip(branch_targets, signed):
                n = self.graph.nodes[tid]
                n.coords = (n.coords[0], center + off - n.height / 2)

    # ---------- geometry helpers ----------
    def _rect(self, node: BPMNNode):
        x, y = node.coords
        return (x, y, x + node.width, y + node.height)

    @staticmethod
    def _point_inside_rect(p: Point, r, margin=0.0) -> bool:
        x, y = p
        x1, y1, x2, y2 = r
        return x1 - margin < x < x2 + margin and y1 - margin < y < y2 + margin

    @staticmethod
    def _segment_intersects_rect(a: Point, b: Point, r, margin=0.0) -> bool:
        x1, y1, x2, y2 = r
        x1 -= margin; y1 -= margin; x2 += margin; y2 += margin
        ax, ay = a; bx, by = b
        if abs(ax - bx) < 1e-6:  # vertical
            if not (x1 <= ax <= x2):
                return False
            lo, hi = sorted((ay, by))
            return hi >= y1 and lo <= y2
        if abs(ay - by) < 1e-6:  # horizontal
            if not (y1 <= ay <= y2):
                return False
            lo, hi = sorted((ax, bx))
            return hi >= x1 and lo <= x2
        # Diagonal segments are forbidden by the router.
        return True

    @staticmethod
    def _segments(route: List[Point]) -> List[Segment]:
        return list(zip(route, route[1:]))

    @staticmethod
    def _segments_cross(a: Segment, b: Segment) -> bool:
        (ax1, ay1), (ax2, ay2) = a
        (bx1, by1), (bx2, by2) = b
        if abs(ax1 - ax2) < 1e-6 and abs(bx1 - bx2) < 1e-6:
            if abs(ax1 - bx1) > 1e-6:
                return False
            return max(min(ay1, ay2), min(by1, by2)) < min(max(ay1, ay2), max(by1, by2))
        if abs(ay1 - ay2) < 1e-6 and abs(by1 - by2) < 1e-6:
            if abs(ay1 - by1) > 1e-6:
                return False
            return max(min(ax1, ax2), min(bx1, bx2)) < min(max(ax1, ax2), max(bx1, bx2))
        # perpendicular
        if abs(ax1 - ax2) < 1e-6:
            vx, vy1, vy2 = ax1, min(ay1, ay2), max(ay1, ay2)
            hy, hx1, hx2 = by1, min(bx1, bx2), max(bx1, bx2)
            return hx1 < vx < hx2 and vy1 < hy < vy2
        vx, vy1, vy2 = bx1, min(by1, by2), max(by1, by2)
        hy, hx1, hx2 = ay1, min(ax1, ax2), max(ax1, ax2)
        return hx1 < vx < hx2 and vy1 < hy < vy2

    def _route_hits_nodes(self, route: List[Point], source: str, target: str) -> bool:
        ignored = {source, target}
        for a, b in self._segments(route):
            for nid, node in self.graph.nodes.items():
                if nid in ignored:
                    continue
                if self._segment_intersects_rect(a, b, self._rect(node), margin=4.0):
                    return True
        return False

    def _edge_crossing_penalty(self, route: List[Point], existing: List[List[Point]]) -> int:
        penalty = 0
        for old in existing:
            for s1 in self._segments(route):
                for s2 in self._segments(old):
                    if self._segments_cross(s1, s2):
                        penalty += 1
        return penalty

    def _port(self, node: BPMNNode, side: str) -> Point:
        x, y = node.coords
        if side == 'left':
            return (x, y + node.height / 2)
        if side == 'right':
            return (x + node.width, y + node.height / 2)
        if side == 'top':
            return (x + node.width / 2, y)
        return (x + node.width / 2, y + node.height)

    def _candidate_forward_routes(self, src: BPMNNode, dst: BPMNNode, existing):
        """Generate orthogonal routes, including detours around intervening nodes."""
        sx1, sy1, sx2, sy2 = self._rect(src)
        tx1, ty1, tx2, ty2 = self._rect(dst)
        sy = sy1 + src.height / 2
        ty = ty1 + dst.height / 2
        start = (sx2, sy)
        end = (tx1, ty)

        if tx1 < sx2:
            return []

        x_candidates = [
            sx2 + self.ROUTE_GAP,
            (sx2 + tx1) / 2,
            tx1 - self.ROUTE_GAP,
            sx2 + self.ROUTE_GAP * 2,
            tx1 - self.ROUTE_GAP * 2,
        ]

        # First try a straight horizontal connection.
        routes = []
        direct = [start, end]
        if abs(sy - ty) < 1e-6 and not self._route_hits_nodes(direct, src.id, dst.id):
            routes.append(direct)

        # If direct is blocked or Y differs, use orthogonal X/Y channels.
        y_candidates = [
            sy,
            ty,
            sy - 50.0,
            sy + 50.0,
            ty - 50.0,
            ty + 50.0,
            min(sy, ty) - 80.0,
            max(sy, ty) + 80.0,
        ]

        for x in x_candidates:
            for y in y_candidates:
                route = [start, (x, sy), (x, y), (tx1 - self.ROUTE_GAP, y), (tx1 - self.ROUTE_GAP, ty), end]
                # Remove zero-length segments while preserving orthogonality.
                compact = [route[0]]
                for point in route[1:]:
                    if point != compact[-1]:
                        compact.append(point)
                if len(compact) < 2:
                    continue
                if self._route_hits_nodes(compact, src.id, dst.id):
                    continue
                routes.append(compact)

        # Prefer fewer bends, then shorter routes, then fewer edge crossings.
        return routes

    def _back_route(self, src: BPMNNode, dst: BPMNNode) -> List[Point]:
        # Put all cycle traffic above the entire drawing. Each back-edge gets
        # its own channel so it cannot cut through the main flow.
        min_y = min((n.coords[1] for n in self.graph.nodes.values()), default=self.START_Y)
        channel = min_y - 70.0 - 30.0 * len([1 for e in self.edge_routes if e in self.back_edges])
        s = self._port(src, 'top')
        t = self._port(dst, 'top')
        x1 = s[0]
        x2 = t[0]
        return [s, (x1, channel), (x2, channel), t]

    def _route_edges(self):
        self.edge_routes: Dict[Tuple[str, str], List[Point]] = {}
        existing: List[List[Point]] = []
        # Forward edges first, longest/most important edges first.
        edges = sorted(self.graph.edges, key=lambda e: (e.source in {x for x, _ in self.back_edges}, self.graph.nodes[e.source].level, self.graph.nodes[e.target].level))
        for edge in edges:
            src = self.graph.nodes[edge.source]
            dst = self.graph.nodes[edge.target]
            key = (edge.source, edge.target)
            if key in self.back_edges:
                route = self._back_route(src, dst)
            else:
                candidates = self._candidate_forward_routes(src, dst, existing)
                if candidates:
                    route = min(candidates, key=lambda r: (self._edge_crossing_penalty(r, existing), len(r)))
                else:
                    # Safe fallback: route on a dedicated channel to the right
                    # of the source, then to the target. This remains orthogonal.
                    sy = src.coords[1] + src.height / 2
                    ty = dst.coords[1] + dst.height / 2
                    x = max(src.coords[0] + src.width, dst.coords[0] - self.ROUTE_GAP) + self.ROUTE_GAP
                    route = [(src.coords[0] + src.width, sy), (x, sy), (x, ty), (dst.coords[0], ty)]
            self.edge_routes[key] = route
            existing.append(route)

        # Validate hard invariant. Raise during development/tests rather than silently export bad DI.
        for edge in self.graph.edges:
            route = self.edge_routes[(edge.source, edge.target)]
            if self._route_hits_nodes(route, edge.source, edge.target):
                raise ValueError(f"Edge {edge.source}->{edge.target} intersects a node")
            for a, b in self._segments(route):
                if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                    raise ValueError(f"Edge {edge.source}->{edge.target} contains a diagonal segment")
