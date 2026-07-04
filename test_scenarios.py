import time
import json
import threading
import urllib.request
import urllib.error
from app import app

# Constants for test URL
BASE_URL = "http://127.0.0.1:5000"

def run_server():
    """Run Flask server in background thread."""
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

def send_post(endpoint, data):
    """Utility to send POST requests using urllib."""
    url = f"{BASE_URL}{endpoint}"
    req_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, 
        data=req_data, 
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode("utf-8")}

def send_get(endpoint):
    """Utility to send GET requests using urllib."""
    url = f"{BASE_URL}{endpoint}"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode("utf-8")}

def print_section(title):
    print("\n" + "="*80)
    print(f" SCENARIO: {title}")
    print("="*80)

def main():
    print("Starting background Flask server...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to boot
    time.sleep(1.5)
    print("Server ready. Starting test scenarios...\n")
    
    # Scenario 0: Initial Status check
    status = send_get("/api/status")
    print(f"Initial available slots: {status['remaining_slots']}")
    print(f"Initial active bookings count: {len(status['active_bookings'])}")
    for b in status['active_bookings']:
        print(f"  - Booking #{b['id']}: {b['customer_name']} at {b['slot']}")
    
    # -------------------------------------------------------------
    # Scenario 1: VIP booking cancellation
    # -------------------------------------------------------------
    print_section("1. VIP Booking Cancellation (John Doe)")
    vip_cancel_msg = {
        "message": "Hello, I am VIP customer John Doe. I need to cancel my booking for 02:00 PM today. Please process this."
    }
    print(f"Input Message: \"{vip_cancel_msg['message']}\"")
    result = send_post("/api/request", vip_cancel_msg)
    print(json.dumps(result, indent=2))
    
    # -------------------------------------------------------------
    # Scenario 2: New customer booking earliest available slot today
    # -------------------------------------------------------------
    print_section("2. New Customer Booking Earliest Slot")
    # Slot 02:00 PM should have been freed up by the VIP cancellation. Let's book it.
    booking_msg = {
        "message": "Can I book the earliest available slot today? My name is Mark Smith, email mark.smith@example.com"
    }
    print(f"Input Message: \"{booking_msg['message']}\"")
    result = send_post("/api/request", booking_msg)
    print(json.dumps(result, indent=2))

    # -------------------------------------------------------------
    # Scenario 3: Customer charged twice (duplicate charge)
    # -------------------------------------------------------------
    # Case A: Below limit ($35) -> Should auto-approve
    print_section("3A. Duplicate Charge (Below Limit - $35.00)")
    refund_low_msg = {
        "message": "Hi, I was charged twice. There was an extra charge on my bill for $35.00. Can I get a refund?"
    }
    print(f"Input Message: \"{refund_low_msg['message']}\"")
    result = send_post("/api/request", refund_low_msg)
    print(json.dumps(result, indent=2))
    
    # Case B: Above limit ($120) -> Should flag for staff review
    print_section("3B. Duplicate Charge (Above Limit - $120.00)")
    refund_high_msg = {
        "message": "Hello, I have a duplicate charge on my credit card for $120.00. I need a refund immediately."
    }
    print(f"Input Message: \"{refund_high_msg['message']}\"")
    result = send_post("/api/request", refund_high_msg)
    print(json.dumps(result, indent=2))
    
    # We will need the ID for approval later
    status = send_get("/api/status")
    pending_refunds = [r for r in status['requests_log'] if r['status'] == 'pending_staff_approval' and r['category'] == 'DUPLICATE_CHARGE']
    pending_id = pending_refunds[0]['id'] if pending_refunds else None

    # -------------------------------------------------------------
    # Scenario 4: Customer simple price question
    # -------------------------------------------------------------
    print_section("4. Simple Pricing Question")
    price_msg = {
        "message": "What are your standard prices? How much is the VIP package?"
    }
    print(f"Input Message: \"{price_msg['message']}\"")
    result = send_post("/api/request", price_msg)
    print(json.dumps(result, indent=2))

    # -------------------------------------------------------------
    # Scenario 5: Angry customer at risk of leaving bad review
    # -------------------------------------------------------------
    print_section("5. Angry Customer Escalation")
    angry_msg = {
        "message": "This is the worst customer service ever! If you don't call me back immediately, I am writing a negative Google review about your business!"
    }
    print(f"Input Message: \"{angry_msg['message']}\"")
    result = send_post("/api/request", angry_msg)
    print(json.dumps(result, indent=2))

    # -------------------------------------------------------------
    # Scenario 6: Staff Approval of Pending Refund
    # -------------------------------------------------------------
    if pending_id:
        print_section(f"6. Staff Approval of Refund Request ID #{pending_id}")
        print(f"Approving escalated refund of $120.00 for request ID #{pending_id}...")
        approval_result = send_post(f"/api/approve-refund/{pending_id}", {})
        print(json.dumps(approval_result, indent=2))
    else:
        print("\nCould not find a pending refund request to approve.")

    # -------------------------------------------------------------
    # Final Database State Summary
    # -------------------------------------------------------------
    print_section("FINAL SYSTEM STATE")
    final_status = send_get("/api/status")
    print(f"Remaining available slots: {final_status['remaining_slots']}")
    print("\nActive Bookings:")
    for b in final_status['active_bookings']:
        print(f"  - Booking #{b['id']}: {b['customer_name']} at {b['slot']} ({b['customer_email']})")
    
    print("\nRequest Logs Overview:")
    for r in final_status['requests_log']:
        print(f"  - Request #{r['id']} | Category: {r['category']} | Status: {r['status']} | Assigned Staff: {r['assigned_staff']} | Action: {r['action_taken']}")
        
    print("\nTest Scenarios execution completed successfully.")

if __name__ == "__main__":
    main()
