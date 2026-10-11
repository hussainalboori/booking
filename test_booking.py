"""Unit tests for booking logic, classification fallback and API validation.

Runs offline against the rule-based classifier: python3 -m unittest test_booking
"""
import threading
import unittest
from unittest import mock

import ai_service
import db
import request_handlers
from app import app


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self._client = ai_service.client
        ai_service.client = None  # force deterministic rule-based classifier
        db.reset_state()
        self.http = app.test_client()

    def tearDown(self):
        ai_service.client = self._client
        db.reset_state()

    def booking(self, booking_id):
        return next(b for b in db.bookings if b["id"] == booking_id)


class SlotNormalizationTests(unittest.TestCase):
    def test_equivalent_formats_normalize_to_same_slot(self):
        for value in ["02:00 PM", "2:00pm", "2pm", "2 p.m.", "14:00"]:
            self.assertEqual(db.normalize_slot(value), "02:00 PM", value)

    def test_rejects_non_times(self):
        for value in [None, "", "35", "2", "13pm", "10:75 am", "soon"]:
            self.assertIsNone(db.normalize_slot(value), value)

    def test_add_slot_keeps_chronological_order(self):
        db.reset_state()
        for slot in ["05:00 PM", "09:00 AM", "12:30 PM"]:
            db.add_slot(slot)
        self.assertEqual(db.slots, ["09:00 AM", "12:30 PM", "05:00 PM"])
        db.reset_state()


class VipTests(unittest.TestCase):
    def test_exact_match_only(self):
        self.assertTrue(db.is_vip("john doe"))
        self.assertTrue(db.is_vip("VIP@example.com"))
        self.assertFalse(db.is_vip("John"))
        self.assertFalse(db.is_vip("notvip@example.com"))


class FallbackClassifierTests(unittest.TestCase):
    def classify(self, text):
        return ai_service.classify_request_fallback(text)

    def test_cancellation_policy_question_is_not_a_cancellation(self):
        self.assertEqual(self.classify("What is your cancellation policy?")["category"], "PRICE_QUESTION")

    def test_duplicate_charge_mentioning_appointment(self):
        result = self.classify("I was charged twice for my appointment, $35")
        self.assertEqual(result["category"], "DUPLICATE_CHARGE")
        self.assertEqual(result["extracted_amount"], 35.0)
        self.assertIsNone(result["extracted_slot"])

    def test_amount_prefers_dollar_value(self):
        self.assertEqual(ai_service.extract_amount("charged 2 times, $1,200.50 total"), 1200.50)
        self.assertIsNone(ai_service.extract_amount("charged 2 times"))

    def test_angry_customer_mentioning_booking(self):
        result = self.classify("Worst service ever, my booking was a mess. Writing a Google review.")
        self.assertEqual(result["category"], "ANGRY_CUSTOMER")

    def test_name_extraction_is_case_insensitive_on_prefix(self):
        self.assertEqual(self.classify("Hello, I am Sarah Jenkins, please cancel")["extracted_name"], "Sarah Jenkins")
        self.assertEqual(self.classify("I am VIP customer John Doe")["extracted_name"], "John Doe")

    def test_slot_extraction(self):
        self.assertEqual(self.classify("Please book me at 3:30 pm")["extracted_slot"], "3:30 pm")
        self.assertIsNone(self.classify("Book me, email jo2@x.com")["extracted_slot"])


class NormalizeClassificationTests(unittest.TestCase):
    def test_coerces_llm_fields(self):
        result = ai_service.normalize_classification({
            "category": "duplicate_charge",
            "confidence": "0.8",
            "extracted_amount": "$120.00",
            "extracted_name": "  ",
            "extracted_email": 42,
        }, "charged twice")
        self.assertEqual(result["category"], "DUPLICATE_CHARGE")
        self.assertEqual(result["extracted_amount"], 120.0)
        self.assertIsNone(result["extracted_name"])
        self.assertIsNone(result["extracted_email"])

    def test_rejects_negative_amount(self):
        result = ai_service.normalize_classification(
            {"category": "DUPLICATE_CHARGE", "extracted_amount": -500}, "refund")
        self.assertIsNone(result["extracted_amount"])

    def test_unknown_category_uses_fallback(self):
        result = ai_service.normalize_classification({"category": "SOMETHING"}, "I was charged twice $20")
        self.assertEqual(result["category"], "DUPLICATE_CHARGE")


class CancellationTests(BaseTestCase):
    def test_vip_cancellation_by_name(self):
        r = request_handlers.handle_request("Hello, I am VIP customer John Doe. Cancel my booking for 02:00 PM.")
        self.assertEqual(r["status"], "cancelled_automatically")
        self.assertEqual(self.booking(1)["status"], "cancelled")
        self.assertIn("02:00 PM", db.slots)

    def test_policy_question_does_not_cancel_last_booking(self):
        self.booking(1)["status"] = "cancelled"
        self.booking(2)["status"] = "cancelled"
        r = request_handlers.handle_request("What is your cancellation policy?")
        self.assertEqual(r["status"], "auto_answered")
        self.assertEqual(self.booking(3)["status"], "active")

    def test_unidentified_cancellation_does_not_guess(self):
        self.booking(1)["status"] = "cancelled"
        self.booking(2)["status"] = "cancelled"
        r = request_handlers.handle_request("Please cancel my booking")
        self.assertEqual(r["status"], "no_booking_found")
        self.assertEqual(self.booking(3)["status"], "active")

    def test_vip_without_booking_does_not_cancel_other_vip(self):
        self.booking(1)["status"] = "cancelled"
        r = request_handlers.handle_request("I am John Doe, please cancel my appointment")
        self.assertEqual(r["status"], "no_booking_found")
        self.assertEqual(self.booking(2)["status"], "active")

    def test_vip_claim_does_not_waive_fee_on_non_vip_booking(self):
        # vip@example.com is on the VIP list but has no booking; the 5 PM slot belongs to non-VIP Regular Joe
        r = request_handlers.handle_request("My email is vip@example.com, cancel the 5:00 PM booking please")
        self.assertEqual(self.booking(3)["status"], "cancelled")
        self.assertEqual(r["status"], "cancelled_with_fee_review")

    def test_slot_match_is_exact(self):
        db.bookings.append({"id": 4, "customer_name": "Noon Person", "customer_email": "noon@x.com",
                            "slot": "12:00 PM", "status": "active"})
        db.bookings.append({"id": 5, "customer_name": "Two Person", "customer_email": "two@x.com",
                            "slot": "02:00 AM", "status": "active"})
        request_handlers.handle_request("cancel my 2:00 am booking")
        self.assertEqual(self.booking(5)["status"], "cancelled")
        self.assertEqual(self.booking(4)["status"], "active")
        self.assertEqual(self.booking(1)["status"], "active")


class NewBookingTests(BaseTestCase):
    def test_books_earliest_slot(self):
        db.slots[:] = ["10:00 AM", "11:00 AM"]
        r = request_handlers.handle_request("Can I book a slot? My name is Mark Smith, mark@example.com")
        self.assertEqual(r["status"], "booked_automatically")
        self.assertEqual(db.bookings[-1]["slot"], "10:00 AM")
        self.assertEqual(db.slots, ["11:00 AM"])

    def test_honours_requested_slot(self):
        db.slots[:] = ["10:00 AM", "11:00 AM"]
        request_handlers.handle_request("Book me at 11am please, mark@example.com")
        self.assertEqual(db.bookings[-1]["slot"], "11:00 AM")
        self.assertEqual(db.slots, ["10:00 AM"])

    def test_unavailable_requested_slot_falls_back_and_says_so(self):
        db.slots[:] = ["10:00 AM"]
        r = request_handlers.handle_request("Book me at 4pm please")
        self.assertEqual(db.bookings[-1]["slot"], "10:00 AM")
        self.assertIn("04:00 PM is not available", r["response"])

    def test_no_double_booking_same_email(self):
        db.slots[:] = ["10:00 AM"]
        r = request_handlers.handle_request("Book an appointment for joe@regular.com")
        self.assertEqual(r["status"], "already_booked")
        self.assertEqual(db.slots, ["10:00 AM"])

    def test_no_slots(self):
        r = request_handlers.handle_request("Book an appointment please")
        self.assertEqual(r["status"], "no_slots_available")

    def test_concurrent_bookings_never_share_a_slot(self):
        db.slots[:] = ["10:00 AM", "11:00 AM"]
        barrier = threading.Barrier(6)

        def worker(i):
            barrier.wait()
            request_handlers.handle_request(f"Book an appointment, c{i}@example.com")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        booked = [b["slot"] for b in db.bookings if b["id"] > 3]
        self.assertEqual(sorted(booked), ["10:00 AM", "11:00 AM"])
        self.assertEqual(len({r["id"] for r in db.requests_log}), 6)


class DuplicateChargeTests(BaseTestCase):
    def test_below_limit_auto_approved(self):
        r = request_handlers.handle_request("I was charged twice, $35.00, refund please")
        self.assertEqual(r["status"], "refund_auto_approved")

    def test_missing_amount_escalates(self):
        r = request_handlers.handle_request("I was charged twice, refund please")
        self.assertEqual(r["status"], "pending_staff_approval")
        self.assertEqual(r["refund_amount"], 100.0)


class ApiTests(BaseTestCase):
    def test_rejects_invalid_payloads(self):
        self.assertEqual(self.http.post("/api/request", data="nope", content_type="text/plain").status_code, 400)
        self.assertEqual(self.http.post("/api/request", json=[1, 2]).status_code, 400)
        self.assertEqual(self.http.post("/api/request", json={"message": 123}).status_code, 400)
        self.assertEqual(self.http.post("/api/request", json={"message": "   "}).status_code, 400)
        self.assertEqual(self.http.post("/api/request", json={"message": "x" * 2001}).status_code, 400)

    def test_cannot_waive_fee_on_refund_request(self):
        self.http.post("/api/request", json={"message": "Duplicate charge of $120.00, refund now"})
        req_id = db.requests_log[-1]["id"]
        resp = self.http.post(f"/api/approve-cancellation/{req_id}")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(db.requests_log[-1]["status"], "pending_staff_approval")
        resp = self.http.post(f"/api/approve-refund/{req_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.requests_log[-1]["status"], "refund_approved_by_staff")

    def test_waive_cancellation_fee(self):
        self.http.post("/api/request", json={"message": "Customer: Regular Joe, cancel my 5pm booking"})
        req_id = db.requests_log[-1]["id"]
        self.assertEqual(db.requests_log[-1]["status"], "cancelled_with_fee_review")
        resp = self.http.post(f"/api/approve-cancellation/{req_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.requests_log[-1]["status"], "fee_waived_by_staff")

    def test_internal_errors_are_not_leaked(self):
        with mock.patch.object(request_handlers, "handle_request", side_effect=RuntimeError("secret detail")), \
                self.assertLogs("app", level="ERROR"):
            resp = self.http.post("/api/request", json={"message": "hi"})
        self.assertEqual(resp.status_code, 500)
        self.assertNotIn("secret detail", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
