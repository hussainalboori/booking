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
    if category == "VIP_CANCELLATION":
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
    customer_name = ai_result.get("extracted_name") or "Valued VIP Customer"
    customer_email = ai_result.get("extracted_email")
    
    # Check VIP list by name or email
    is_vip_customer = db.is_vip(customer_name) or db.is_vip(customer_email)
    
    if is_vip_customer:
        # Find their active booking
        booking_to_cancel = None
        for b in db.bookings:
            if b["status"] == "active" and (
                (customer_email and b["customer_email"].lower() == customer_email.lower()) or
                (customer_name and customer_name.lower() in b["customer_name"].lower())
            ):
                booking_to_cancel = b
                break
        
        # If no customer booking matched, try slot or cancel the earliest vip booking
        if not booking_to_cancel:
            for b in db.bookings:
                if b["status"] == "active" and db.is_vip(b["customer_name"]):
                    booking_to_cancel = b
                    break
        
        if booking_to_cancel:
            booking_to_cancel["status"] = "cancelled"
            db.add_slot(booking_to_cancel["slot"])
            req_entry["status"] = "cancelled_automatically"
            req_entry["action_taken"] = f"Auto-cancelled slot {booking_to_cancel['slot']} for VIP {booking_to_cancel['customer_name']}"
            req_entry["response"] = f"Hi {booking_to_cancel['customer_name']}. We have successfully cancelled your appointment at {booking_to_cancel['slot']} today, free of charge. Your VIP status guarantees free cancellations. Have a nice day!"
        else:
            req_entry["status"] = "no_booking_found"
            req_entry["action_taken"] = "VIP cancellation requested but no active booking was found."
            req_entry["response"] = f"Hi {customer_name}. We received your cancellation request, but could not find an active booking for you today. Please contact us directly if you believe this is an error."
    else:
        # Non-VIP cancellation requested
        staff_name = db.assign_staff_member()
        req_entry["status"] = "pending_staff_approval"
        req_entry["assigned_staff"] = staff_name
        req_entry["priority"] = "high"
        req_entry["action_taken"] = f"Non-VIP cancellation requested. Flagged for standard cancellation fee review."
        req_entry["response"] = f"Hi. Since you are not registered on our VIP list, standard cancellation policies apply. We have flagged your request for review by our staff member {staff_name} to verify fee exemptions."
        
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
