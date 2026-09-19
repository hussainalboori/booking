import os
from flask import Flask, request, jsonify
import db
import request_handlers

app = Flask(__name__, static_folder="static", static_url_path="")

@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

@app.route("/api/request", methods=["POST"])
def process_request():
    """Endpoint for processing incoming customer messages."""
    data = request.get_json() or {}
    message_text = data.get("message")
    
    if not message_text:
        return jsonify({"error": "Message content is required"}), 400
        
    try:
        outcome = request_handlers.handle_request(message_text)
        return jsonify({
            "success": True,
            "category": outcome["category"],
            "status": outcome["status"],
            "priority": outcome["priority"],
            "assigned_staff": outcome["assigned_staff"],
            "action_taken": outcome["action_taken"],
            "response_generated": outcome["response"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/status", methods=["GET"])
def get_status():
    """Endpoint to inspect current state of slots, bookings, staff, and logged requests."""
    return jsonify({
        "remaining_slots": db.slots,
        "active_bookings": [b for b in db.bookings if b["status"] == "active"],
        "all_bookings": db.bookings,
        "staff": db.staff,
        "refund_limit": db.REFUND_LIMIT,
        "requests_log": db.requests_log
    })

@app.route("/api/approve-refund/<int:request_id>", methods=["POST"])
def approve_refund(request_id):
    """Staff endpoint to manually approve an escalated duplicate charge refund."""
    # Find request in log
    target_req = None
    for r in db.requests_log:
        if r["id"] == request_id:
            target_req = r
            break
            
    if not target_req:
        return jsonify({"error": "Request ID not found"}), 404
        
    if target_req["category"] != "DUPLICATE_CHARGE":
        return jsonify({"error": "This request is not a duplicate charge complaint"}), 400
        
    if target_req["status"] != "pending_staff_approval":
        return jsonify({"error": f"Refund is not in pending state. Current status: {target_req['status']}"}), 400
        
    # Approve refund
    target_req["status"] = "refund_approved_by_staff"
    target_req["action_taken"] += " | Manually approved by staff."
    target_req["response"] = f"Hello. Your refund of ${target_req.get('refund_amount', 0.0):.2f} has been manually approved by our staff and processed. Thank you for your patience."
    
    return jsonify({
        "success": True,
        "message": f"Refund of ${target_req.get('refund_amount', 0.0):.2f} approved successfully.",
        "request": {
            "id": target_req["id"],
            "status": target_req["status"],
            "action_taken": target_req["action_taken"]
        }
    })

@app.route("/api/approve-cancellation/<int:request_id>", methods=["POST"])
def approve_cancellation(request_id):
    """Staff endpoint to review/waive fee for a non-VIP cancellation."""
    target_req = None
    for r in db.requests_log:
        if r["id"] == request_id:
            target_req = r
            break
            
    if not target_req:
        return jsonify({"error": "Request ID not found"}), 404
        
    if target_req["status"] not in ["cancelled_with_fee_review", "pending_staff_approval"]:
        return jsonify({"error": f"Cancellation is not pending review. Current status: {target_req['status']}"}), 400
        
    target_req["status"] = "fee_waived_by_staff"
    target_req["action_taken"] += " | Cancellation fee waived by staff."
    target_req["response"] = "Hello. Our staff has reviewed your cancellation and agreed to waive the standard cancellation fee. Have a great day!"
    
    return jsonify({
        "success": True,
        "message": "Cancellation fee waiver approved successfully.",
        "request": {
            "id": target_req["id"],
            "status": target_req["status"],
            "action_taken": target_req["action_taken"]
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Booking Automation Server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
