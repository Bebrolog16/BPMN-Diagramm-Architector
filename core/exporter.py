from lxml import etree


class BPMNExporter:
    NS = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    def __init__(self, graph):
        self.graph = graph

    def export(self, output_path: str):
        root = etree.Element(
            self._q("bpmn", "definitions"),
            nsmap=self.NS,
            id="Definitions_1",
            targetNamespace="https://example.org/bpmn",
            exporter="BPMN AI Architect",
            exporterVersion="1.0.0",
        )
        ids = {}
        collaboration_id = "Collaboration_1"
        collaboration = etree.SubElement(root, self._q("bpmn", "collaboration"), id=collaboration_id)
        participant_ids = {self.graph.root_process_id: self.graph.root_participant_id}
        for pool in self.graph.pools.values():
            participant_ids[pool.process_id] = pool.id

        for process_id, process_name in self.graph.processes.items():
            participant_id = participant_ids[process_id]
            etree.SubElement(
                collaboration,
                self._q("bpmn", "participant"),
                id=participant_id,
                name=process_name,
                processRef=process_id,
            )
            ids[participant_id] = "participant"

        process_elements = {}
        for process_id, process_name in self.graph.processes.items():
            process = etree.SubElement(
                root,
                self._q("bpmn", "process"),
                id=process_id,
                name=process_name,
                isExecutable="false",
            )
            process_elements[process_id] = process
            ids[process_id] = "process"
            pool = self.graph.pools.get(self.graph.process_pool.get(process_id))
            if pool and pool.lane_ids:
                lane_set = etree.SubElement(process, self._q("bpmn", "laneSet"), id=f"{pool.id}_laneSet")
                for lane_id in pool.lane_ids:
                    lane = self.graph.lanes[lane_id]
                    lane_element = etree.SubElement(
                        lane_set,
                        self._q("bpmn", "lane"),
                        id=lane.id,
                        name=lane.name,
                    )
                    ids[lane.id] = "lane"
                    for node in self.graph.nodes.values():
                        if node.parent_id == lane_id and node.type != "group":
                            etree.SubElement(lane_element, self._q("bpmn", "flowNodeRef")).text = node.id

        for node in self.graph.nodes.values():
            if node.process_id not in process_elements:
                raise ValueError(f"Node {node.id} references unknown process {node.process_id}")
            tag = self._map_node_type(node.type)
            etree.SubElement(
                process_elements[node.process_id],
                self._q("bpmn", tag),
                id=node.id,
                name=node.name,
            )
            ids[node.id] = "node"

        for edge_index, edge in enumerate(self.graph.edges):
            flow_id = self._flow_id(edge, edge_index)
            if edge.flow_type == "message":
                etree.SubElement(
                    collaboration,
                    self._q("bpmn", "messageFlow"),
                    id=flow_id,
                    sourceRef=edge.source,
                    targetRef=edge.target,
                    **({"name": edge.label} if edge.label else {}),
                )
                ids[flow_id] = "messageFlow"
                continue

            attrs = {"id": flow_id, "sourceRef": edge.source, "targetRef": edge.target}
            if edge.label:
                attrs["name"] = edge.label
            sequence = etree.SubElement(process_elements[self.graph.nodes[edge.source].process_id], self._q("bpmn", "sequenceFlow"), **attrs)
            ids[flow_id] = "sequenceFlow"
            if edge.condition:
                condition = etree.SubElement(sequence, self._q("bpmn", "conditionExpression"))
                condition.set(self._q("xsi", "type"), "bpmn:tFormalExpression")
                condition.text = edge.condition

        diagram = etree.SubElement(root, self._q("bpmndi", "BPMNDiagram"), id="BPMNDiagram_1")
        plane = etree.SubElement(
            diagram,
            self._q("bpmndi", "BPMNPlane"),
            id="BPMNPlane_1",
            bpmnElement=collaboration_id,
        )

        for process_id, participant_id in participant_ids.items():
            bounds = self.graph.process_bounds.get(process_id)
            if bounds:
                self._add_shape(plane, participant_id, f"{participant_id}_di", bounds, is_horizontal=True)
            pool_id = self.graph.process_pool.get(process_id)
            pool = self.graph.pools.get(pool_id)
            if pool:
                for lane_id in pool.lane_ids:
                    lane_bounds = self.graph.lane_bounds.get(lane_id)
                    if lane_bounds:
                        self._add_shape(plane, lane_id, f"{lane_id}_di", lane_bounds, is_horizontal=True)

        for node in self.graph.nodes.values():
            self._add_shape(
                plane,
                node.id,
                f"{node.id}_di",
                (node.coords[0], node.coords[1], node.width, node.height),
                is_horizontal=False,
            )

        for edge_index, edge in enumerate(self.graph.edges):
            waypoints = self._route_edge(edge, edge_index)
            edge_flow_id = self._flow_id(edge, edge_index)
            edge_element = etree.SubElement(
                plane,
                self._q("bpmndi", "BPMNEdge"),
                id=f"{edge_flow_id}_di",
                bpmnElement=edge_flow_id,
            )
            for x, y in waypoints:
                etree.SubElement(edge_element, self._q("di", "waypoint"), x=self._number(x), y=self._number(y))

        self._validate_tree(root, ids)
        etree.ElementTree(root).write(
            output_path,
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8",
        )
        return output_path

    def _validate_tree(self, root, ids):
        if set(self.graph.processes) - set(self.graph.process_bounds):
            raise ValueError("Run LayoutEngine.calculate_layout() before BPMN export")
        seen = set()
        for element in root.iter():
            element_id = element.get("id")
            if element_id:
                if element_id in seen:
                    raise ValueError(f"Duplicate BPMN id: {element_id}")
                seen.add(element_id)
        bpmn_ids = {
            element.get("id")
            for element in root.iter()
            if isinstance(element.tag, str) and element.tag.startswith(f"{{{self.NS['bpmn']}}}") and element.get("id")
        }
        for element in root.iter():
            referenced = element.get("bpmnElement")
            if referenced and referenced not in bpmn_ids:
                raise ValueError(f"Diagram interchange references missing BPMN element: {referenced}")
            process_ref = element.get("processRef")
            if process_ref and process_ref not in self.graph.processes:
                raise ValueError(f"Participant references missing process: {process_ref}")
        for edge in self.graph.edges:
            if edge.source not in self.graph.nodes or edge.target not in self.graph.nodes:
                raise ValueError(f"Unknown flow endpoint: {edge.source} -> {edge.target}")
            if edge.flow_type == "sequence" and self.graph.nodes[edge.source].process_id != self.graph.nodes[edge.target].process_id:
                raise ValueError("Sequence flows cannot cross process boundaries; use message flows")

    def _add_shape(self, plane, element_id, shape_id, bounds, is_horizontal=False):
        attrs = {"id": shape_id, "bpmnElement": element_id}
        if is_horizontal:
            attrs["isHorizontal"] = "true"
        shape = etree.SubElement(plane, self._q("bpmndi", "BPMNShape"), **attrs)
        x, y, width, height = bounds
        etree.SubElement(
            shape,
            self._q("dc", "Bounds"),
            x=self._number(x),
            y=self._number(y),
            width=self._number(width),
            height=self._number(height),
        )

    def _route_edge(self, edge, edge_index):
        source = self.graph.nodes[edge.source]
        target = self.graph.nodes[edge.target]
        sx = source.coords[0] + source.width
        sy = source.coords[1] + source.height / 2
        tx = target.coords[0]
        ty = target.coords[1] + target.height / 2

        if tx > sx + 20:
            mid_x = (sx + tx) / 2 + self._fan_offset(edge, edge_index)
            if abs(sy - ty) < 1:
                return [(sx, sy), (tx, ty)]
            return [(sx, sy), (mid_x, sy), (mid_x, ty), (tx, ty)]

        track_rank = sum(
            1
            for candidate in self.graph.edges[:edge_index]
            if self.graph.nodes[candidate.target].coords[0]
            <= self.graph.nodes[candidate.source].coords[0]
            + self.graph.nodes[candidate.source].width
            + 20
        )
        track = min(source.coords[1], target.coords[1]) - 35 - track_rank * 16
        return [
            (sx, sy),
            (sx + 24, sy),
            (sx + 24, track),
            (tx - 24, track),
            (tx - 24, ty),
            (tx, ty),
        ]

    def _fan_offset(self, edge, edge_index):
        offset = 0.0
        source_edges = [(index, candidate) for index, candidate in enumerate(self.graph.edges) if candidate.source == edge.source]
        if len(source_edges) > 1:
            rank = next(rank for rank, (index, _) in enumerate(source_edges) if index == edge_index)
            spacing = min(14.0, 50.0 / len(source_edges))
            offset += (rank - (len(source_edges) - 1) / 2) * spacing

        target_edges = [(index, candidate) for index, candidate in enumerate(self.graph.edges) if candidate.target == edge.target]
        if len(target_edges) > 1:
            rank = next(rank for rank, (index, _) in enumerate(target_edges) if index == edge_index)
            spacing = min(14.0, 50.0 / len(target_edges))
            offset += (rank - (len(target_edges) - 1) / 2) * spacing
        return offset

    @staticmethod
    def _flow_id(edge, index):
        return f"Flow_{index}_{edge.source}_{edge.target}"

    @staticmethod
    def _number(value):
        return str(float(value))

    @staticmethod
    def _q(prefix, local_name):
        return f"{{{BPMNExporter.NS[prefix]}}}{local_name}"

    @staticmethod
    def _map_node_type(node_type):
        return {
            "start": "startEvent",
            "end": "endEvent",
            "task": "task",
            "userTask": "userTask",
            "scriptTask": "scriptTask",
            "exclusiveGateway": "exclusiveGateway",
            "parallelGateway": "parallelGateway",
            "inclusiveGateway": "inclusiveGateway",
            "subprocess": "subProcess",
            "group": "group",
        }.get(node_type, "task")
