import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.diagram import DiagramSDK
from core.layout import LayoutEngine
from core.exporter import BPMNExporter


def _is_orthogonal(route):
    return all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
               for a, b in zip(route, route[1:]))


def _segment_hits_rect(a, b, node):
    x, y = node.coords
    x2, y2 = x + node.width, y + node.height
    ax, ay = a
    bx, by = b
    if abs(ax - bx) < 1e-6:
        if not (x <= ax <= x2):
            return False
        lo, hi = sorted((ay, by))
        return hi > y and lo < y2
    if abs(ay - by) < 1e-6:
        if not (y <= ay <= y2):
            return False
        lo, hi = sorted((ax, bx))
        return hi > x and lo < x2
    return True


def test_cycle_and_gateway_routing():
    sdk = DiagramSDK()
    pool, lanes = sdk.add_pool(sdk.ROOT_PROCESS_ID, ["Main"])

    send = sdk.add_task("Send Request", lanes[0])
    approve = sdk.add_task("Approve", lanes[0])
    decision = sdk.add_exclusive_gateway("Decision", lanes[0])
    end_process = sdk.add_task("End Process", lanes[0])
    reject = sdk.add_task("Reject", lanes[0])

    sdk.add_link(sdk.ROOT_START_TASK_ID, send)
    sdk.add_link(send, approve)
    sdk.add_link(approve, decision)
    sdk.add_link(decision, end_process)
    sdk.add_link(decision, reject)
    sdk.add_link(reject, end_process)
    sdk.add_link(end_process, sdk.ROOT_END_TASK_ID)

    layout = LayoutEngine(sdk.graph)
    layout.calculate_layout()
    routes = sdk.graph.layout_metadata["edge_routes"]

    # Forward structure must progress left-to-right.
    for source, target in [
        (sdk.ROOT_START_TASK_ID, send),
        (send, approve),
        (approve, decision),
        (decision, end_process),
        (decision, reject),
        (end_process, sdk.ROOT_END_TASK_ID),
    ]:
        assert sdk.graph.nodes[target].coords[0] > sdk.graph.nodes[source].coords[0]

    # The two decision branches are on different Y positions.
    assert sdk.graph.nodes[end_process].coords[1] != sdk.graph.nodes[reject].coords[1]

    # Every route is orthogonal and avoids every unrelated node.
    for edge in sdk.graph.edges:
        route = routes[(edge.source, edge.target)]
        assert _is_orthogonal(route), (edge.source, edge.target, route)
        for a, b in zip(route, route[1:]):
            for nid, node in sdk.graph.nodes.items():
                if nid in {edge.source, edge.target}:
                    continue
                assert not _segment_hits_rect(a, b, node), (edge.source, edge.target, nid, route)

    # The Reject -> End Process edge must be routed as an explicit back/long route,
    # not as a single diagonal segment.
    reject_route = routes[(reject, end_process)]
    assert len(reject_route) >= 4
    assert any(a[1] != b[1] for a, b in zip(reject_route, reject_route[1:]))

    output = os.path.join(os.path.dirname(__file__), "routing_result.bpmn")
    BPMNExporter(sdk.graph).export(output)
    assert os.path.exists(output)


if __name__ == "__main__":
    test_cycle_and_gateway_routing()
    print("routing test: OK")
