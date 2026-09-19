# In-memory database state

# 2 Staff members available
staff = [
    {"id": 1, "name": "Alice", "status": "available"},
    {"id": 2, "name": "Bob", "status": "available"}
]

# Slots available for booking today (initially empty because slots 02:00 PM, 03:30 PM, and 05:00 PM are already booked below)
slots = []

# VIP customer list (emails/names for matching)
vip_customers = [
    "vip@example.com",
    "john.doe@vip.com",
    "vip_customer@booking.com",
    "John Doe",
    "Sarah Jenkins"
]

# Knowledge base definitions
knowledge_base = {
    "pricing": "Standard appointment: $100 per hour. Premium package: $180 (includes full diagnostic). VIP subscription: $150/month (unlimited priority support).",
    "cancellation_policy": "Standard customers must cancel 24 hours in advance to avoid a $25 fee. VIP customers can cancel anytime for free.",
    "services": "We offer standard consulting, technical diagnostic support, and VIP priority consultations."
}

# Refunds exceeding $50 require staff approval
REFUND_LIMIT = 50.0

# Current active bookings (to enable cancellation scenarios)
bookings = [
    {
        "id": 1,
        "customer_name": "John Doe",
        "customer_email": "john.doe@vip.com",
        "slot": "02:00 PM",
        "status": "active"
    },
    {
        "id": 2,
        "customer_name": "Sarah Jenkins",
        "customer_email": "sarah.j@vip.com",
        "slot": "03:30 PM",
        "status": "active"
    },
    {
        "id": 3,
        "customer_name": "Regular Joe",
        "customer_email": "joe@regular.com",
        "slot": "05:00 PM",
        "status": "active"
    }
]

# Log of all incoming customer requests & outcomes
requests_log = []

def get_next_available_slot():
    """Returns the earliest available slot today, or None."""
    if len(slots) > 0:
        return slots[0]
    return None

def reserve_slot(slot):
    """Removes a slot from the available list when booked."""
    if slot in slots:
        slots.remove(slot)
        return True
    return False

def add_slot(slot):
    """Adds a slot back to the available list (e.g. on cancellation)."""
    if slot and slot not in slots:
        slots.append(slot)
        def parse_time(t):
            try:
                import datetime
                return datetime.datetime.strptime(t.strip(), "%I:%M %p")
            except Exception:
                return t
        slots.sort(key=parse_time)

def is_vip(name_or_email):
    """Checks if the customer is on the VIP list."""
    if not name_or_email:
        return False
    name_or_email_lower = name_or_email.lower().strip()
    for vip in vip_customers:
        if vip.lower().strip() in name_or_email_lower or name_or_email_lower in vip.lower().strip():
            return True
    return False

def assign_staff_member():
    """Finds an available staff member or defaults to the first one."""
    for s in staff:
        if s["status"] == "available":
            return s["name"]
    return staff[0]["name"] if staff else "Unassigned"
