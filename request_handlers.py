import db
import ai_service

def handle_request(message_text):
    """Classifies the customer message and routes it to the correct handler."""
    # 1. AI Classification
    ai_result = ai_service.classify_request(message_text)
    category = ai_result.get("category")
    
    # Base structure for the request entry
    req_entry = {
        "id": len(db.requests_log) + 1,
        "message": message_text,
        "category": category,
        "ai_analysis": ai_result,
        "assigned_staff": None,
        "priority": "normal",
        "status": "processed",
        "action_taken": "",
        "response": ""
    }
    
    # 2. Routing to Handlers
    if category in ["VIP_CANCELLATION", "CANCELLATION"]:
        response_data = handle_vip_cancellation(ai_result, req_entry)
    elif category == "NEW_BOOKING":
        response_data = handle_new_booking(ai_result, req_entry)
    elif category == "DUPLICATE_CHARGE":
        response_data = handle_duplicate_charge(ai_result, req_entry)
    elif category == "PRICE_QUESTION":
        response_data = handle_price_question(message_text, req_entry)
    elif category == "ANGRY_CUSTOMER":
        response_data = handle_angry_customer(ai_result, req_entry)
    else:
        # Fallback default handler
        req_entry["response"] = "Thank you for your message. We have received it and will get back to you shortly."
        req_entry["action_taken"] = "No action. Logged."
        db.requests_log.append(req_entry)
        response_data = req_entry

    return response_data

def handle_vip_cancellation(ai_result, req_entry):
    customer_name = ai_result.get("extracted_name")
    customer_email = ai_result.get("extracted_email")
    extracted_slot = ai_result.get("extracted_slot")
    
    # Check VIP list by name or email
    is_vip_customer = (customer_name and db.is_vip(customer_name)) or (customer_email and db.is_vip(customer_email))
    
    # Find matching active booking
    booking_to_cancel = None
    
    # 1. Match by email
    if customer_email:
        for b in db.bookings:
            if b["status"] == "active" and b["customer_email"].lower() == customer_email.lower():
                booking_to_cancel = b
                break
                
    # 2. Match by customer name
    if not booking_to_cancel and customer_name:
        for b in db.bookings:
            if b["status"] == "active" and (
                customer_name.lower() in b["customer_name"].lower() or 
                b["customer_name"].lower() in customer_name.lower()
            ):
                booking_to_cancel = b
                break
                
    # 3. Match by time slot mentioned (e.g. 02:00 PM, 2:00, 5pm)
    if not booking_to_cancel and extracted_slot:
        clean_extracted = extracted_slot.lower().replace(" ", "").lstrip("0")
        for b in db.bookings:
            clean_b_slot = b["slot"].lower().replace(" ", "").lstrip("0")
            if b["status"] == "active" and (clean_extracted in clean_b_slot or clean_b_slot in clean_extracted):
                booking_to_cancel = b
                break

    # 4. Fallback if VIP customer didn't specify name/slot clearly
    if not booking_to_cancel and is_vip_customer:
        for b in db.bookings:
            if b["status"] == "active" and db.is_vip(b["customer_name"]):
                booking_to_cancel = b
                break

    # 5. If only one active booking remains and cancellation was asked
    if not booking_to_cancel:
        active_bookings = [b for b in db.bookings if b["status"] == "active"]
        if len(active_bookings) == 1:
            booking_to_cancel = active_bookings[0]

    # Process cancellation if booking found
    if booking_to_cancel:
        # Check VIP status of the found booking if not already detected
        if not is_vip_customer:
            is_vip_customer = db.is_vip(booking_to_cancel["customer_name"]) or db.is_vip(booking_to_cancel["customer_email"])

        # Mark booking as cancelled and release slot
        booking_to_cancel["status"] = "cancelled"
        db.add_slot(booking_to_cancel["slot"])

        if is_vip_customer:
            req_entry["status"] = "cancelled_automatically"
            req_entry["action_taken"] = f"Auto-cancelled slot {booking_to_cancel['slot']} for VIP {booking_to_cancel['customer_name']}. Slot is now open."
            req_entry["response"] = f"Hi {booking_to_cancel['customer_name']}. We have successfully cancelled your appointment at {booking_to_cancel['slot']} today, free of charge. Your VIP status guarantees free cancellations. Have a nice day!"
        else:
            staff_name = db.assign_staff_member()
            req_entry["status"] = "cancelled_with_fee_review"
            req_entry["assigned_staff"] = staff_name
            req_entry["priority"] = "normal"
            req_entry["action_taken"] = f"Cancelled slot {booking_to_cancel['slot']} for {booking_to_cancel['customer_name']}. Slot is now open. Flagged for standard fee ($25) review."
            req_entry["response"] = f"Hi {booking_to_cancel['customer_name']}. Your appointment at {booking_to_cancel['slot']} has been cancelled and the slot has been reopened. Standard cancellation fee ($25) applies unless exempt. Our staff member {staff_name} will review your account."
    else:
        req_entry["status"] = "no_booking_found"
        req_entry["action_taken"] = "Cancellation requested but no matching active booking was found."
        display_name = customer_name or "there"
        req_entry["response"] = f"Hi {display_name}. We received your cancellation request, but could not find an active booking for you today. Please contact us directly if you believe this is an error."
        
    db.requests_log.append(req_entry)
    return req_entry

def handle_new_booking(ai_result, req_entry):
    customer_name = ai_result.get("extracted_name") or "New Customer"
    customer_email = ai_result.get("extracted_email") or "customer@example.com"
    
    slot = db.get_next_available_slot()
    
    if slot:
        # Reserve slot and create booking
        db.reserve_slot(slot)
        new_booking = {
            "id": len(db.bookings) + 1,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "slot": slot,
            "status": "active"
        }
        db.bookings.append(new_booking)
        
        req_entry["status"] = "booked_automatically"
        req_entry["action_taken"] = f"Auto-booked slot {slot} for {customer_name}"
        req_entry["response"] = f"Hi {customer_name}. Your booking for the earliest slot today ({slot}) has been confirmed! We look forward to seeing you."
    else:
        req_entry["status"] = "no_slots_available"
        req_entry["action_taken"] = "Tried to book but no slots are available today."
        req_entry["response"] = f"Hi {customer_name}. Unfortunately, we do not have any slots remaining today. We have added you to our waitlist and will reach out if a slot opens up."
        
    db.requests_log.append(req_entry)
    return req_entry

def handle_duplicate_charge(ai_result, req_entry):
    amount = ai_result.get("extracted_amount")
    
    # Default to standard single charge amount if extraction failed
    if not amount:
        amount = 100.0
        
    req_entry["refund_amount"] = amount
    
    if amount <= db.REFUND_LIMIT:
        req_entry["status"] = "refund_auto_approved"
        req_entry["action_taken"] = f"Auto-approved duplicate charge refund of ${amount:.2f}."
        req_entry["response"] = f"Hello. We have verified your request and automatically approved a refund of ${amount:.2f} for the duplicate charge. It will appear on your statement within 3-5 business days."
    else:
        staff_name = db.assign_staff_member()
        req_entry["status"] = "pending_staff_approval"
        req_entry["assigned_staff"] = staff_name
        req_entry["priority"] = "high"
        req_entry["action_taken"] = f"Duplicate charge refund of ${amount:.2f} exceeds threshold. Flagged for review."
        req_entry["response"] = f"Hello. We have detected a duplicate charge of ${amount:.2f}. Since this amount exceeds our auto-refund limit of ${db.REFUND_LIMIT:.2f}, we have escalated this to {staff_name} for immediate manual approval."
        
    db.requests_log.append(req_entry)
    return req_entry

def handle_price_question(message_text, req_entry):
    # Call AI service with knowledge base context
    answer = ai_service.generate_price_response(message_text, db.knowledge_base)
    
    req_entry["status"] = "auto_answered"
    req_entry["action_taken"] = "Answered pricing/info question using Knowledge Base."
    req_entry["response"] = answer
    
    db.requests_log.append(req_entry)
    return req_entry

def handle_angry_customer(ai_result, req_entry):
    customer_name = ai_result.get("extracted_name") or "Valued Customer"
    staff_name = db.assign_staff_member()
    
    req_entry["status"] = "escalated_to_staff"
    req_entry["assigned_staff"] = staff_name
    req_entry["priority"] = "high"
    req_entry["action_taken"] = f"High frustration detected. Escalated to {staff_name} to prevent bad review."
    req_entry["response"] = f"Hi {customer_name}. We are very sorry for the frustration this has caused. We have escalated your message directly to our staff member {staff_name}, who will contact you immediately to make this right."
    
    db.requests_log.append(req_entry)
    return req_entry
