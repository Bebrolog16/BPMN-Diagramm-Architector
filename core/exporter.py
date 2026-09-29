from lxml import etree
from core.graph import BPMNEdge, BPMNGraph, BPMNNode
import os

class BPMNExporter:
    def __init__(self, graph: BPMNGraph):
        self.graph = graph
        # Namespaces - Exactly as in the sample file
        self.NS = {
            "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
            "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
            "dc": "http://www.omg.org/spec/DD/20100524/DC",
            "di": "http://www.omg.org/spec/DD/20100524/DI"
        }

    def export(self, output_path: str):
        """Main method to generate .bpmn file compatible with bpmn.io (STABLE VERSION)"""
        # 1. Root element
        root = etree.Element(f"{{{self.NS['bpmn']}}}definitions",
                             nsmap=self.NS,
                             targetNamespace=self.NS['bpmn'],
                             exporter="bpmn-js (https://demo.bpmn.io)",
                             exporterVersion="18.30.1")

        # IDs for top-level elements
        collaboration_id = "Collaboration_1"
        main_process_id = "Process_1"

        # 2. Collaboration
        collaboration = etree.SubElement(root, f"{{{self.NS['bpmn']}}}collaboration", id=collaboration_id)
        
        # To avoid 'unrecognized element bpmn:lane' or 'bpmn:laneSet', 
        # we create a single participant without lanes for the prototype.
        # LayoutEngine still handles the Y coordinates for visual separation.
        participant = etree.SubElement(collaboration, f"{{{self.NS['bpmn']}}}participant", 
                                         id="Participant_1", 
                                         name="Process Participant", 
                                         processRef=main_process_id)

        # 3. Process Logic
        process = etree.SubElement(root, f"{{{self.NS['bpmn']}}}process", id=main_process_id, isExecutable="false")
        
        # Nodes
        for node_id, node in self.graph.nodes.items():
            tag_name = self._map_node_type(node.type)
            etree.SubElement(process, f"{{{self.NS['bpmn']}}}{tag_name}", id=node_id, name=node.name)

        # Edges (Sequence Flows)
        for edge in self.graph.edges:
            flow_id = f"Flow_{edge.source}_{edge.target}"
            etree.SubElement(process, f"{{{self.NS['bpmn']}}}sequenceFlow", 
                             id=flow_id, 
                             sourceRef=edge.source, 
                             targetRef=edge.target)

        # 4. BPMN Diagram (DI)
        bpmndi_diagram = etree.SubElement(root, f"{{{self.NS['bpmndi']}}}BPMNDiagram", id="BPMNDiagram_1")
        
        # Plane references the Collaboration
        plane = etree.SubElement(bpmndi_diagram, f"{{{self.NS['bpmndi']}}}plane", 
                                id="BPMNPlane_1", 
                                bpmnElement=collaboration_id)

        # Shapes
        for node_id, node in self.graph.nodes.items():
            shape = etree.SubElement(plane, f"{{{self.NS['bpmndi']}}}BPMNShape", 
                                   id=f"{node_id}_di", 
                                   bpmnElement=node_id)
            
            # Bounds: plain attributes for bpmn.io
            bounds = etree.SubElement(shape, f"{{{self.NS['di']}}}bounds")
            bounds.set("x", str(node.coords[0]))
            bounds.set("y", str(node.coords[1]))
            bounds.set("width", str(node.width))
            bounds.set("height", str(node.height))

        # Edges
        for edge in self.graph.edges:
            flow_id = f"Flow_{edge.source}_{edge.target}"
            edge_di = etree.SubElement(plane, f"{{{self.NS['bpmndi']}}}BPMNEdge", 
                                     id=f"{flow_id}_di", 
                                     bpmnElement=flow_id)
            
            src = self.graph.nodes[edge.source]
            dst = self.graph.nodes[edge.target]
            
            # Waypoints: plain attributes
            wp1 = etree.SubElement(edge_di, f"{{{self.NS['di']}}}waypoint")
            wp1.set("x", str(src.coords[0] + src.width))
            wp1.set("y", str(src.coords[1] + src.height / 2))
            
            wp2 = etree.SubElement(edge_di, f"{{{self.NS['di']}}}waypoint")
            wp2.set("x", str(dst.coords[0]))
            wp2.set("y", str(dst.coords[1] + dst.height / 2))

        # Final Write
        tree = etree.ElementTree(root)
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
            'group': 'group'
        }
        return mapping.get(node_type, 'task')
