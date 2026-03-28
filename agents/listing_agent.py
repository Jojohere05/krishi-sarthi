"""
Listing Agent – Converts vendor voice/text into a structured product listing.
Uses LLM (Gemini) with a regex fallback.
"""
import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ──────────────────────────────────────────────
# Regex fallback parser
# ──────────────────────────────────────────────
UNIT_PATTERNS = ['kg', 'gram', 'grams', 'g', 'litre', 'liter', 'l', 'piece',
                 'pieces', 'bunch', 'bunches', 'dozen', 'dozens', 'quintal']

FRESHNESS_KEYWORDS = {
    5: ['very fresh', 'just picked', 'just harvested', 'aaj ka', 'fresh today', 'bilkul fresh'],
    4: ['fresh', 'kal ka', 'yesterday', 'good'],
    3: ['average', 'normal', 'okay', 'theek hai'],
    2: ['old', 'purana', 'not fresh'],
    1: ['very old', 'bahut purana', 'stale']
}

KNOWN_VEGETABLES = [
    'tomato', 'tomatoes', 'onion', 'onions', 'potato', 'potatoes', 'spinach',
    'cauliflower', 'brinjal', 'cabbage', 'carrot', 'peas', 'garlic', 'ginger',
    'chilli', 'chili', 'coriander', 'mint', 'banana', 'mango', 'apple', 'grape',
    'wheat', 'rice', 'dal', 'lentil', 'corn', 'maize'
]


def regex_parser(text: str) -> dict:
    """
    Fallback regex parser when LLM is unavailable.
    Extracts product, quantity, unit, price, freshness from natural language.
    """
    text_lower = text.lower()

    # Extract product name
    product = "Unknown Product"
    for veg in KNOWN_VEGETABLES:
        if veg in text_lower:
            product = veg.capitalize()
            break

    # Extract price (number followed by rupee keywords or preceded by Rs/₹)
    price = 0
    price_match = re.search(r'(?:rs\.?|₹|rupees?|price\s+(?:is\s+)?)\s*(\d+(?:\.\d+)?)', text_lower)
    if not price_match:
        # Try standalone numbers near price words
        price_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:rs\.?|₹|rupees?|per\s+\w+)', text_lower)
    if price_match:
        price = float(price_match.group(1))

    # Extract quantity
    quantity = 0
    qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:' + '|'.join(UNIT_PATTERNS) + r')', text_lower)
    if qty_match:
        quantity = float(qty_match.group(1))
    else:
        # standalone number
        nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', text_lower)
        if nums and float(nums[0]) != price:
            quantity = float(nums[0])

    # Extract unit
    unit = "kg"
    for u in UNIT_PATTERNS:
        if re.search(r'\b' + u + r'\b', text_lower):
            unit = u
            break

    # Extract freshness
    freshness = 4  # default: fresh
    for score, keywords in FRESHNESS_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                freshness = score
                break

    return {
        "product": product,
        "quantity": quantity,
        "unit": unit,
        "price": price,
        "freshness": freshness,
        "source": "regex_fallback"
    }


def llm_parser(text: str) -> dict:
    """
    Use Gemini Flash to extract structured product info from voice text.
    Returns dict or raises exception on failure.
    """
    if not GEMINI_API_KEY:
        raise ValueError("No GEMINI_API_KEY set")

    prompt = f"""You are an agricultural product listing assistant for rural Indian farmers.
Extract product details from this vendor's voice/text input and return ONLY a JSON object.

Input: "{text}"

Return exactly this JSON structure (no markdown, no explanation):
{{
  "product": "product name in English",
  "quantity": <number>,
  "unit": "kg/gram/piece/bunch/dozen/litre",
  "price": <number in INR per unit>,
  "freshness": <integer 1-5 where 5=very fresh, 1=very old>
}}

Rules:
- product: capitalize first letter
- quantity: numeric value only
- unit: one of kg, gram, piece, bunch, dozen, litre, quintal
- price: number only (INR)
- freshness: 1-5 integer based on context clues
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
    }

    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data['candidates'][0]['content']['parts'][0]['text'].strip()

    # Strip markdown fences if present
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    result = json.loads(raw)
    result['source'] = 'gemini'
    return result


def extract_product(voice_text: str) -> dict:
    """
    Main entry point for Listing Agent.
    Tries LLM first, falls back to regex on any failure.
    """
    try:
        return llm_parser(voice_text)
    except Exception as e:
        print(f"[ListingAgent] LLM failed ({e}), using regex fallback")
        result = regex_parser(voice_text)
        return result