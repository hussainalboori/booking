import db
import ai_service

def handle_request(message_text):
    """Classifies the customer message and routes it to the correct handler."""
    # 1. AI Classification
    ai_result = ai_service.classify_request(message_text)
    category = ai_result.get("category")

    # Slow AI calls happen outside the state lock so they don't serialize every request.
    price_answer = None
    if category == "PRICE_QUESTION":
        price_answer = ai_service.generate_price_response(message_text, db.knowledge_base)

    with db.lock:
        return _route_request(message_text, ai_result, price_answer)

def _route_request(message_text, ai_result, price_answer):
    category = ai_result.get("category")

    # Base structure for the request entry
    req_entry = {
        "id": db.next_request_id(),
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
        response_data = handle_price_question(message_text, req_entry, price_answer)
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
    
    active_bookings = [b for b in db.bookings if b["status"] == "active"]

    # Find matching active booking
    booking_to_cancel = None

    # 1. Match by email
    if customer_email:
        for b in active_bookings:
            if b["customer_email"].lower() == customer_email.lower():
                booking_to_cancel = b
                break

    # 2. Match by customer name (all words of the shorter name must appear in the other,
    #    so "Joe" matches "Regular Joe" but "Jo" does not match "John Doe")
    if not booking_to_cancel and customer_name:
        for b in active_bookings:
            if _names_match(customer_name, b["customer_name"]):
                booking_to_cancel = b
                break

    # 3. Match by exact time slot mentioned (e.g. 02:00 PM, 2:00pm, 2pm)
    requested_slot = db.normalize_slot(extracted_slot)
    if not booking_to_cancel and requested_slot:
        for b in active_bookings:
            if db.normalize_slot(b["slot"]) == requested_slot:
                booking_to_cancel = b
                break

    # No guessing beyond this point: cancelling someone else's booking is worse than asking
    # the customer to clarify.

    # Process cancellation if booking found
    if booking_to_cancel:
        # VIP status comes from the booking owner, not from what the message claims,
        # so a non-VIP booking cannot get a free cancellation by mentioning a VIP name.
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
    extracted_email = ai_result.get("extracted_email")
    customer_name = ai_result.get("extracted_name") or "New Customer"
    customer_email = extracted_email or "customer@example.com"

    # Avoid double-booking a customer who already holds an active slot today
    if extracted_email:
        for b in db.bookings:
            if b["status"] == "active" and b["customer_email"].lower() == extracted_email.lower():
                req_entry["status"] = "already_booked"
                req_entry["action_taken"] = f"No new booking made; {b['customer_name']} already holds slot {b['slot']}."
                req_entry["response"] = f"Hi {customer_name}. You already have an appointment booked today at {b['slot']}. If you'd like to change it, please cancel the existing booking first."
                db.requests_log.append(req_entry)
                return req_entry

    # Honour a specifically requested time if it is open, otherwise take the earliest slot
    requested_slot = db.normalize_slot(ai_result.get("extracted_slot"))
    slot = db.find_available_slot(requested_slot) if requested_slot else None
    requested_unavailable = bool(requested_slot) and not slot
    if not slot:
        slot = db.get_next_available_slot()

    if slot and db.reserve_slot(slot):
        new_booking = {
            "id": len(db.bookings) + 1,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "slot": slot,
            "status": "active"
        }
        db.bookings.append(new_booking)
        
        req_entry["status"] = "booked_automatically"
        if requested_unavailable:
            req_entry["action_taken"] = f"Requested {requested_slot} unavailable; auto-booked earliest slot {slot} for {customer_name}"
            req_entry["response"] = f"Hi {customer_name}. Unfortunately {requested_slot} is not available, so we have booked you into the earliest open slot today ({slot}). Let us know if that doesn't work for you."
        elif requested_slot:
            req_entry["action_taken"] = f"Auto-booked requested slot {slot} for {customer_name}"
            req_entry["response"] = f"Hi {customer_name}. Your booking for {slot} today has been confirmed! We look forward to seeing you."
        else:
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
    
    # Default to standard single charge amount if extraction failed or is not a positive number;
    # this is above the auto-refund limit, so unclear amounts always go to staff.
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not amount > 0:
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

def handle_price_question(message_text, req_entry, answer=None):
    # Call AI service with knowledge base context (unless already generated by the caller)
    if answer is None:
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

def _names_match(a, b):
    """True if every word of the shorter name appears as a whole word in the longer one."""
    words_a, words_b = a.lower().split(), b.lower().split()
    if not words_a or not words_b:
        return False
    shorter, longer = sorted((words_a, words_b), key=len)
    return all(w in longer for w in shorter)
