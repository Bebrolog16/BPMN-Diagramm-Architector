import os
import sys

# MAGIC FIX: Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.diagram import DiagramSDK
from core.layout import LayoutEngine
from core.exporter import BPMNExporter

def run_complex_test():
    print("Starting Complex Scenario Test...")
    
    sdk = DiagramSDK()
    
    # 1. Define Pools and Lanes
    # Pool 1: Customer
    customer_pool, customer_lanes = sdk.add_pool("Pool_Customer", ["Customer_Lane"])
    
    # Pool 2: Store (with multiple lanes)
    store_pool, store_lanes = sdk.add_pool("Pool_Store", ["Manager_Lane", "Warehouse_Lane", "Delivery_Lane"])
    
    # 2. Build the Graph
    # --- Start ---
    start_id = sdk.ROOT_START_TASK_ID
    
    # Customer places order
    t1 = sdk.add_task("Place Order", customer_lanes[0])
    sdk.add_link(start_id, t1)
    
    # Order goes to Manager for verification
    t2 = sdk.add_task("Verify Order", store_lanes[0])
    sdk.add_link(t1, t2)
    
    # Manager decides if order is valid (Exclusive Gateway)
    g1 = sdk.add_exclusive_gateway("Order Valid?", store_lanes[0])
    sdk.add_link(t2, g1)
    
    # Case A: Not Valid -> Back to Customer
    t_fix = sdk.add_task("Fix Order Details", customer_lanes[0])
    sdk.add_link(g1, t_fix)
    sdk.add_link(t_fix, t2) # LOOP: Back to verification
    
    # Case B: Valid -> Proceed to parallel processing
    g_parallel_start = sdk.add_parallel_gateway("Start Parallel", store_lanes[0])
    sdk.add_link(g1, g_parallel_start)
    
    # Branch 1: Warehouse picks items
    t_pick = sdk.add_task("Pick Items", store_lanes[1])
    sdk.add_link(g_parallel_start, t_pick)
    
    # Branch 2: Manager prepares documents
    t_docs = sdk.add_task("Prepare Invoice", store_lanes[0])
    sdk.add_link(g_parallel_start, t_docs)
    
    # Join parallel branches
    g_parallel_end = sdk.add_parallel_gateway("Join Parallel", store_lanes[0])
    sdk.add_link(t_pick, g_parallel_end)
    sdk.add_link(t_docs, g_parallel_end)
    
    # Finally, Delivery
    t_deliver = sdk.add_task("Ship Order", store_lanes[2])
    sdk.add_link(g_parallel_end, t_deliver)
    
    # End process
    sdk.add_link(t_deliver, sdk.ROOT_END_TASK_ID)
    
    print("Graph construction completed. Running Layout Engine...")
    
    # 3. Layout
    layout = LayoutEngine(sdk.graph)
    layout.calculate_layout()
    
    # 4. Export
    output_path = "outputs/complex_result.bpmn"
    os.makedirs("outputs", exist_ok=True)
    exporter = BPMNExporter(sdk.graph)
    exporter.export(output_path)
    
    print(f"Success! Complex diagram exported to: {output_path}")
    print("Now open it in bpmn.io and check for overlaps or missing links, блядь!")

if __name__ == "__main__":
    run_complex_test()
