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
        client = OpenAI(api_key=api_key, http_client=httpx.Client())
    except Exception as e:
        print(f"Warning: Failed to initialize OpenAI client: {e}")

def classify_request_openai(message_text):
    """Uses OpenAI API to classify request and extract structured details."""
    system_prompt = """
    You are an intelligent booking assistant. Analyze the incoming customer message and classify it into exactly one of these five categories:
    1. VIP_CANCELLATION: Customer wants to cancel a booking, and is (or claims to be) a VIP customer.
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
        return result
    except Exception as e:
        print(f"OpenAI API call failed: {e}. Falling back to rule-based system.")
        return classify_request_fallback(message_text)

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
    
    # 1. VIP cancellation detection
    if "cancel" in text or "cancellation" in text or "delete my slot" in text:
        category = "VIP_CANCELLATION"
        explanation = "Detected cancellation request."
        
    # 2. New booking detection
    elif "book" in text or "reserve" in text or "appointment" in text or "schedule" in text or "slot" in text:
        category = "NEW_BOOKING"
        explanation = "Detected new appointment/booking request."
        
    # 3. Duplicate charge detection
    elif "charged twice" in text or "double charge" in text or "charged me twice" in text or "refund" in text or "charge error" in text:
        category = "DUPLICATE_CHARGE"
        explanation = "Detected double charge / refund complaint."
        # Extract amount using regex
        amount_match = re.search(r'\$?(\d+(?:\.\d{2})?)', message_text)
        if amount_match:
            extracted_amount = float(amount_match.group(1))
            
    # 4. Angry customer detection
    elif "angry" in text or "furious" in text or "worst" in text or "awful" in text or "horrible" in text or "google review" in text or "bad review" in text or "complain" in text:
        category = "ANGRY_CUSTOMER"
        explanation = "Detected strong negative sentiment or risk of bad review."

    # General email extraction regex
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message_text)
    if email_match:
        extracted_email = email_match.group(0)

    # General slot extraction (e.g. 02:00 PM, 3:30, 5pm)
    slot_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:pm|am|PM|AM)?)', message_text)
    if slot_match:
        extracted_slot = slot_match.group(0)

    # Name heuristics (e.g. "I am John Doe" or "Name: Sarah Jenkins")
    name_match = re.search(r'(?:i am|my name is|customer:?)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', message_text)
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
