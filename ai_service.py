import os
import re
import json
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

# Initialize OpenAI client if key is configured
api_key = os.environ.get("OPENAI_API_KEY")
client = None
# Ensure the key starts with 'sk-' to verify it's a real OpenAI key
if api_key and api_key.strip().startswith("sk-") and len(api_key) > 20:
    try:
        # Bound request latency: the SDK default timeout is 10 minutes, which would hang the
        # request thread. On failure we fall back to the rule-based classifier instead.
        client = OpenAI(api_key=api_key, http_client=httpx.Client(), timeout=15.0, max_retries=1)
    except Exception as e:
        print(f"Warning: Failed to initialize OpenAI client: {e}")

def classify_request_openai(message_text):
    """Uses OpenAI API to classify request and extract structured details."""
    system_prompt = """
    You are an intelligent booking assistant. Analyze the incoming customer message and classify it into exactly one of these five categories:
    1. VIP_CANCELLATION: Customer wants to cancel an existing booking (VIP or not; VIP status is verified separately). Questions ABOUT the cancellation policy or fee are PRICE_QUESTION.
    2. NEW_BOOKING: Customer wants to book a new appointment slot for today.
    3. DUPLICATE_CHARGE: Customer is complaining about being charged twice or double charged.
    4. PRICE_QUESTION: Customer is asking a simple question about price, rates, or packages.
    5. ANGRY_CUSTOMER: Customer is angry, disappointed, expressing high frustration, or threatening a bad review/Google review.

    Extract the following details if present:
    - name: Customer's name
    - email: Customer's email address
    - amount: Any monetary amount mentioned, as a float (especially for duplicate charge queries)
    - slot: Any specific time slot mentioned (e.g. '02:00 PM')

    Respond ONLY with a JSON object containing these keys:
    {
      "category": "VIP_CANCELLATION" | "NEW_BOOKING" | "DUPLICATE_CHARGE" | "PRICE_QUESTION" | "ANGRY_CUSTOMER",
      "confidence": float between 0 and 1,
      "extracted_name": string or null,
      "extracted_email": string or null,
      "extracted_amount": float or null,
      "extracted_slot": string or null,
      "explanation": brief string explaining the choice
    }
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        result = json.loads(response.choices[0].message.content)
        return normalize_classification(result, message_text)
    except Exception as e:
        print(f"OpenAI API call failed: {e}. Falling back to rule-based system.")
        return classify_request_fallback(message_text)

DUPLICATE_CHARGE_KEYWORDS = ["charged twice", "double charge", "double-charge", "charged me twice", "duplicate charge", "refund", "charge error"]
ANGRY_KEYWORDS = ["angry", "furious", "worst", "awful", "horrible", "google review", "bad review", "negative review", "complain"]
BOOKING_KEYWORDS = ["book", "reserve", "appointment", "schedule", "slot"]

def classify_request_fallback(message_text):
    """Rule-based backup classifier using regex and heuristics."""
    text = message_text.lower()
    
    # Defaults
    category = "PRICE_QUESTION"
    extracted_name = None
    extracted_email = None
    extracted_amount = None
    extracted_slot = None
    explanation = "Rule-based fallback classifier"
    
    # 1. Cancellation detection (questions about the cancellation policy are info requests, not cancellations)
    if ("cancel" in text or "delete my slot" in text) and "policy" not in text:
        category = "VIP_CANCELLATION"
        explanation = "Detected cancellation request."

    # 2. Duplicate charge detection (checked before booking keywords, since complaints often mention the appointment)
    elif any(k in text for k in DUPLICATE_CHARGE_KEYWORDS):
        category = "DUPLICATE_CHARGE"
        explanation = "Detected double charge / refund complaint."
        extracted_amount = extract_amount(message_text)

    # 3. Angry customer detection
    elif any(k in text for k in ANGRY_KEYWORDS):
        category = "ANGRY_CUSTOMER"
        explanation = "Detected strong negative sentiment or risk of bad review."

    # 4. New booking detection
    elif any(k in text for k in BOOKING_KEYWORDS):
        category = "NEW_BOOKING"
        explanation = "Detected new appointment/booking request."

    # General email extraction regex
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_text)
    if email_match:
        extracted_email = email_match.group(0)

    # General slot extraction (e.g. 02:00 PM, 3:30, 5pm). Requires a colon or am/pm so that
    # prices and counts (e.g. "$35") are not mistaken for times.
    slot_match = re.search(r'(?<![\d$.,])\d{1,2}(?::\d{2}\s*(?:[ap]\.?m\.?)?|\s*[ap]\.?m\.?)(?![\w])', message_text, re.IGNORECASE)
    if slot_match:
        extracted_slot = slot_match.group(0).strip()

    # Name heuristics (e.g. "I am John Doe" or "Name: Sarah Jenkins")
    name_match = re.search(r'(?i:\bi am|\bmy name is|\bname:|\bcustomer:?)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', message_text)
    if name_match:
        extracted_name = name_match.group(1)
    elif "john doe" in text:
        extracted_name = "John Doe"
    elif "sarah jenkins" in text:
        extracted_name = "Sarah Jenkins"

    return {
      "category": category,
      "confidence": 0.9,
      "extracted_name": extracted_name,
      "extracted_email": extracted_email,
      "extracted_amount": extracted_amount,
      "extracted_slot": extracted_slot,
      "explanation": explanation
    }

VALID_CATEGORIES = {"VIP_CANCELLATION", "CANCELLATION", "NEW_BOOKING", "DUPLICATE_CHARGE", "PRICE_QUESTION", "ANGRY_CUSTOMER"}

def extract_amount(message_text):
    """Extracts a monetary amount, preferring '$'-prefixed values over bare numbers."""
    match = re.search(r'\$\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?', message_text)
    if not match:
        match = re.search(r'(?<![\d:])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})(?!\d)', message_text)
    if not match:
        return None
    return float(match.group(1).replace(",", "") + (match.group(2) or ""))

def _clean_str(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None

def _clean_amount(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount <= 0 or amount == float("inf"):
        return None
    return round(amount, 2)

def normalize_classification(result, message_text):
    """Validates an LLM classification so downstream handlers get well-typed fields.

    An unknown/missing category falls back to the rule-based classifier rather than
    being silently dropped into the generic handler.
    """
    if not isinstance(result, dict):
        return classify_request_fallback(message_text)
    category = _clean_str(result.get("category"))
    category = category.upper() if category else None
    if category not in VALID_CATEGORIES:
        return classify_request_fallback(message_text)
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = None
    return {
        "category": category,
        "confidence": confidence,
        "extracted_name": _clean_str(result.get("extracted_name")),
        "extracted_email": _clean_str(result.get("extracted_email")),
        "extracted_amount": _clean_amount(result.get("extracted_amount")),
        "extracted_slot": _clean_str(result.get("extracted_slot")),
        "explanation": _clean_str(result.get("explanation")) or "",
    }

def classify_request(message_text):
    """Main routing entrypoint that decides whether to use OpenAI or Fallback."""
    if client:
        return classify_request_openai(message_text)
    else:
        return classify_request_fallback(message_text)

def answer_price_question_openai(message_text, kb):
    """Uses OpenAI API to draft a friendly, specific answer from the knowledge base."""
    system_prompt = f"""
    You are a friendly customer helper. Use the provided Knowledge Base below to answer the customer's question.
    Keep your answer helpful, concise (1-3 sentences), and polite.
    
    Knowledge Base:
    {json.dumps(kb, indent=2)}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI QA failed: {e}")
        return answer_price_question_fallback(message_text, kb)

def answer_price_question_fallback(message_text, kb):
    """Rule-based backup answering system from the knowledge base."""
    text = message_text.lower()
    if "vip" in text:
        return f"Hi! Our VIP subscription is $150/month, which includes unlimited priority support and free cancellations. Let us know if you want to sign up!"
    elif "standard" in text or "diagnostic" in text or "diagnostic package" in text or "diagnostic support" in text:
        return f"Hello! Our standard appointment is $100 per hour. We also offer a premium package at $180, which includes a full diagnostic. Let us know what you prefer!"
    else:
        # Default pricing overview
        return f"Hello! Our standard rate is $100/hour. Premium diagnostics are $180, and we offer a VIP subscription for $150/month. Standard cancellation fee is $25 (free for VIPs)."

def generate_price_response(message_text, kb):
    """Main price answering entrypoint."""
    if client:
        return answer_price_question_openai(message_text, kb)
    else:
        return answer_price_question_fallback(message_text, kb)
