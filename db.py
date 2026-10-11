# In-memory database state
import copy
import datetime
import re
import threading

# Guards all mutations of the in-memory state below. Flask serves requests on
# multiple threads, so check-then-act sequences (find slot -> reserve it) must be atomic.
lock = threading.RLock()

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

def normalize_slot(value):
    """Parses a time like '02:00 PM', '2pm', '2:00pm' or '14:00' into canonical 'HH:MM AM/PM' form.

    Returns None if the value is not a recognisable time. A bare number (e.g. '35')
    is rejected so prices or counts are never mistaken for times.
    """
    if not value or not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*', value, re.IGNORECASE)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if not meridiem and match.group(2) is None:
        return None
    if minute > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
    elif hour > 23:
        return None
    return datetime.time(hour, minute).strftime("%I:%M %p")

def _slot_sort_key(slot):
    normalized = normalize_slot(slot)
    if normalized:
        return (0, datetime.datetime.strptime(normalized, "%I:%M %p").time(), slot)
    return (1, datetime.time.min, slot)

def get_next_available_slot():
    """Returns the earliest available slot today, or None."""
    if len(slots) > 0:
        return slots[0]
    return None

def find_available_slot(requested):
    """Returns the available slot matching the requested time, or None."""
    normalized = normalize_slot(requested)
    if not normalized:
        return None
    for slot in slots:
        if normalize_slot(slot) == normalized:
            return slot
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
        slots.sort(key=_slot_sort_key)

def is_vip(name_or_email):
    """Checks if the customer is on the VIP list (case-insensitive exact match on name or email)."""
    if not name_or_email:
        return False
    name_or_email_lower = " ".join(name_or_email.lower().split())
    return any(" ".join(vip.lower().split()) == name_or_email_lower for vip in vip_customers)

def assign_staff_member():
    """Finds an available staff member or defaults to the first one."""
    for s in staff:
        if s["status"] == "available":
            return s["name"]
    return staff[0]["name"] if staff else "Unassigned"

def next_request_id():
    return len(requests_log) + 1

def find_request(request_id):
    for r in requests_log:
        if r["id"] == request_id:
            return r
    return None

_initial_state = {
    "staff": copy.deepcopy(staff),
    "slots": copy.deepcopy(slots),
    "bookings": copy.deepcopy(bookings),
}

def reset_state():
    """Restores the seed data in place (used by tests)."""
    with lock:
        staff[:] = copy.deepcopy(_initial_state["staff"])
        slots[:] = copy.deepcopy(_initial_state["slots"])
        bookings[:] = copy.deepcopy(_initial_state["bookings"])
        requests_log.clear()
