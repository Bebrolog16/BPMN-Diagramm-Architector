from lxml import etree
from core.graph import BPMNGraph
import os


class BPMNExporter:
    def __init__(self, graph: BPMNGraph):
        self.graph = graph
        self.NS = {
            "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
            "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
            "dc": "http://www.omg.org/spec/DD/20100524/DC",
            "di": "http://www.omg.org/spec/DD/20100524/DI",
        }

    def export(self, output_path: str, layout_engine=None):
        # LayoutEngine stores its result on the graph. This makes the result
        # available even when CodeExecutor wraps this method.
        metadata = getattr(self.graph, "layout_metadata", {}) or {}
        routes = metadata.get("edge_routes", {})

        root = etree.Element(
            f"{{{self.NS['bpmn']}}}definitions",
            nsmap=self.NS,
            targetNamespace=self.NS['bpmn'],
            exporter="bpmn-js (https://demo.bpmn.io)",
            exporterVersion="18.30.1",
        )
        collaboration_id = "Collaboration_1"
        main_process_id = "Process_1"
        collaboration = etree.SubElement(root, f"{{{self.NS['bpmn']}}}collaboration", id=collaboration_id)
        etree.SubElement(
            collaboration,
            f"{{{self.NS['bpmn']}}}participant",
            id="Participant_1",
            name="Process Participant",
            processRef=main_process_id,
        )
        process = etree.SubElement(root, f"{{{self.NS['bpmn']}}}process", id=main_process_id, isExecutable="false")

        for node_id, node in self.graph.nodes.items():
            tag_name = self._map_node_type(node.type)
            etree.SubElement(process, f"{{{self.NS['bpmn']}}}{tag_name}", id=node_id, name=node.name)

        for edge in self.graph.edges:
            flow_id = f"Flow_{edge.source}_{edge.target}"
            etree.SubElement(
                process,
                f"{{{self.NS['bpmn']}}}sequenceFlow",
                id=flow_id,
                sourceRef=edge.source,
                targetRef=edge.target,
            )

        bpmndi_diagram = etree.SubElement(root, f"{{{self.NS['bpmndi']}}}BPMNDiagram", id="BPMNDiagram_1")
        plane = etree.SubElement(
            bpmndi_diagram,
            f"{{{self.NS['bpmndi']}}}plane",
            id="BPMNPlane_1",
            bpmnElement=collaboration_id,
        )

        for node_id, node in self.graph.nodes.items():
            shape = etree.SubElement(
                plane,
                f"{{{self.NS['bpmndi']}}}BPMNShape",
                id=f"{node_id}_di",
                bpmnElement=node_id,
            )
            bounds = etree.SubElement(shape, f"{{{self.NS['di']}}}bounds")
            bounds.set("x", str(node.coords[0]))
            bounds.set("y", str(node.coords[1]))
            bounds.set("width", str(node.width))
            bounds.set("height", str(node.height))

        for edge in self.graph.edges:
            flow_id = f"Flow_{edge.source}_{edge.target}"
            edge_di = etree.SubElement(
                plane,
                f"{{{self.NS['bpmndi']}}}BPMNEdge",
                id=f"{flow_id}_di",
                bpmnElement=flow_id,
            )
            route = routes.get((edge.source, edge.target))
            if not route:
                # Never silently emit a two-point diagonal edge. A missing route
                # is a programming error after layout calculation.
                raise ValueError(f"No layout route for edge {edge.source}->{edge.target}")
            for x, y in route:
                wp = etree.SubElement(edge_di, f"{{{self.NS['di']}}}waypoint")
                wp.set("x", str(float(x)))
                wp.set("y", str(float(y)))

        tree = etree.ElementTree(root)
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(output_path, "wb") as f:
            tree.write(f, pretty_print=True, xml_declaration=True, encoding="utf-8")

    def _map_node_type(self, node_type: str) -> str:
        mapping = {
            'start': 'startEvent',
            'end': 'endEvent',
            'task': 'task',
            'userTask': 'userTask',
            'scriptTask': 'scriptTask',
            'exclusiveGateway': 'exclusiveGateway',
            'parallelGateway': 'parallelGateway',
            'inclusiveGateway': 'inclusiveGateway',
            'subprocess': 'subProcess',
            'group': 'group',
        }
        return mapping.get(node_type, 'task')
