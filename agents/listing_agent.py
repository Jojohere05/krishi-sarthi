"""Listing Agent – Converts vendor voice/text into a structured product listing.

Primary path uses the Gemini model via a small prompt.
A lightweight regex / heuristic fallback keeps things
feasible on low-resource setups but still uses simple
NLU-style matching rather than hardcoded values.
"""
import os
import re
import json
import requests
from difflib import get_close_matches
from dotenv import load_dotenv

from .utils import load_json, load_domain_config

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


def _domain_lists():
    """Return domain vocab lists from config and data.

    This function merges configured products/units with
    any product names already present in inventory so the
    system can adapt without code changes.
    """
    cfg = load_domain_config()
    config_products = [p.lower() for p in cfg.get("known_products", [])]
    units = [u.lower() for u in cfg.get("unit_patterns", [])]

    # Enrich product names from existing inventory
    inventory = load_json('inventory.json')
    inventory_products = {str(i.get('product_name', '')).lower() for i in inventory if i.get('product_name')}

    products = list({*config_products, *inventory_products})

    # Freshness keywords are keyed by score as strings in config
    freshness_keywords_cfg = cfg.get("freshness_keywords", {})
    freshness_keywords = {}
    for score_str, words in freshness_keywords_cfg.items():
        try:
            score = int(score_str)
        except ValueError:
            continue
        freshness_keywords[score] = [w.lower() for w in words]

    return products, units, freshness_keywords


def regex_parser(text: str) -> dict:
    """Fallback parser when LLM is unavailable.

    Uses regex plus simple NLP-ish heuristics and
    configuration-driven vocab to extract product,
    quantity, unit, price and freshness.
    """
    text_lower = text.lower()
    products, units, freshness_keywords = _domain_lists()

    # Extract product name (exact or fuzzy against domain vocab)
    product = "Unknown Product"
    tokens = re.findall(r"[\w']+", text_lower)

    # direct contains check first
    for candidate in products:
        if candidate and candidate in text_lower:
            product = candidate.capitalize()
            break

    if product == "Unknown Product" and tokens:
        # fuzzy match any token against known products
        for token in tokens:
            matches = get_close_matches(token, products, n=1, cutoff=0.8)
            if matches:
                product = matches[0].capitalize()
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
    if units:
        qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:' + '|'.join(units) + r')', text_lower)
    else:
        qty_match = None
    if qty_match:
        quantity = float(qty_match.group(1))
    else:
        # standalone number
        nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', text_lower)
        if nums and float(nums[0]) != price:
            quantity = float(nums[0])

    # Extract unit
    unit = "kg"
    for u in units:
        if re.search(r'\b' + re.escape(u) + r'\b', text_lower):
            unit = u
            break

    # Extract freshness using configured keyword buckets
    freshness = 4  # default: fresh
    for score, keywords in freshness_keywords.items():
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