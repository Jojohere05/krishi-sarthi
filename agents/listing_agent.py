"""Listing Agent – Converts vendor voice/text into a structured product listing.

Primary path uses a local Ollama LLM via a small prompt.
A lightweight regex / heuristic fallback keeps things
feasible on low-resource setups but still uses simple
NLU-style matching rather than hardcoded values.
"""
import os
import re
import json
import requests
import time
from difflib import get_close_matches
from dotenv import load_dotenv

from .utils import load_json, load_domain_config

# Load environment variables from the project root .env when available
load_dotenv()

# Ollama configuration – local, lightweight, no external API keys needed
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL_LISTING", os.getenv("OLLAMA_MODEL", "phi3:3.8b-mini"))

# Simple in-memory cache so repeated inputs do not
# trigger repeated LLM calls during the same process.
_LISTING_CACHE: dict[str, dict] = {}


def _extract_json_object(text: str):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


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
    """Use a local Ollama model to extract structured product info.

    Uses a small, efficient model by default (phi3:3.8b-mini)
    and keeps a simple in-memory cache keyed by the input
    text. Any error will bubble up so the caller can fall
    back to regex.
    """
    if not OLLAMA_MODEL:
        raise ValueError("No OLLAMA_MODEL configured")

    # Return cached result when available
    cached = _LISTING_CACHE.get(text)
    if cached is not None:
        return cached

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

    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",  # ask Ollama to format as JSON
        "stream": False,
    }

    last_error: Exception | None = None
    # Small retry loop for transient connection issues
    for _ in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=20)
            resp.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            time.sleep(1)
            continue
        except Exception as e:
            last_error = e
            break

        data = resp.json()
        raw = str(data.get("response", "")).strip()
        print("[ListingAgent] RAW LLM RESPONSE:", raw)

        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        result = _extract_json_object(raw)
        if result is None:
            last_error = Exception("LLM did not return valid JSON")
            break
        result['source'] = 'ollama'
        _LISTING_CACHE[text] = result
        return result

    if last_error is not None:
        raise last_error
    raise RuntimeError("Ollama call failed for listing model")


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