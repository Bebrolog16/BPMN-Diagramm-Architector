"""
Golden examples for BPMN code generation.
Format: (user_request, expected_code)
"""

EXAMPLES = [
    (
        "Create a simple process: Client sends request, Manager approves it, and then the process ends.",
        """sdk = DiagramSDK()
pool_id, lanes = sdk.add_pool(sdk.ROOT_PROCESS_ID, ["Client", "Manager"])
t1 = sdk.add_user_task("Send Request", lanes[0])
t2 = sdk.add_user_task("Approve Request", lanes[1])
sdk.add_link(sdk.ROOT_START_TASK_ID, t1)
sdk.add_link(t1, t2)
sdk.add_link(t2, sdk.ROOT_END_TASK_ID)
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("result.bpmn")"""
    ),
    (
        "Process for loan application: Client submits app, Analyst reviews. If approved, end. If rejected, return to Client to fix.",
        """sdk = DiagramSDK()
pool_id, lanes = sdk.add_pool(sdk.ROOT_PROCESS_ID, ["Client", "Analyst"])
t1 = sdk.add_user_task("Submit Application", lanes[0])
t2 = sdk.add_user_task("Review Application", lanes[1])
gw1 = sdk.add_exclusive_gateway("Approved?", lanes[1])
sdk.add_link(sdk.ROOT_START_TASK_ID, t1)
sdk.add_link(t1, t2)
sdk.add_link(t2, gw1)
sdk.add_link(gw1, sdk.ROOT_END_TASK_ID, label="Yes", condition="approved")
sdk.add_link(gw1, t1, label="No", condition="rejected")
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("result.bpmn")"""
    ),
    (
        "Onboarding process: HR signs contract. Then simultaneously IT sets up laptop and Manager assigns mentor. Then end.",
        """sdk = DiagramSDK()
pool_id, lanes = sdk.add_pool(sdk.ROOT_PROCESS_ID, ["HR", "IT", "Manager"])
t1 = sdk.add_user_task("Sign Contract", lanes[0])
gw_start = sdk.add_parallel_gateway("Start Parallel", lanes[0])
t2 = sdk.add_user_task("Setup Laptop", lanes[1])
t3 = sdk.add_user_task("Assign Mentor", lanes[2])
gw_end = sdk.add_parallel_gateway("Merge Parallel", lanes[0])
sdk.add_link(sdk.ROOT_START_TASK_ID, t1)
sdk.add_link(t1, gw_start)
sdk.add_link(gw_start, t2)
sdk.add_link(gw_start, t3)
sdk.add_link(t2, gw_end)
sdk.add_link(t3, gw_end)
sdk.add_link(gw_end, sdk.ROOT_END_TASK_ID)
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("result.bpmn")"""
    ),
]
