"""Discovery Agent – Answers consumer voice queries with ranked nearby products.

The agent prefers a small LLM call for intent
and keyword extraction but falls back to
configuration-driven heuristics with simple
NLU-style matching (no heavy models).
"""
import os
import re
import json
import requests
from difflib import get_close_matches
from dotenv import load_dotenv
from .utils import (
    load_json,
    load_domain_config,
    get_consumer_by_id,
    get_vendor_by_id,
    euclidean_distance,
    normalize_freshness,
)

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


def _product_vocab() -> list:
    """Combine configured product names with those seen in inventory."""
    cfg = load_domain_config()
    config_products = [p.lower() for p in cfg.get("known_products", [])]
    inventory = load_json('inventory.json')
    inventory_products = {str(i.get('product_name', '')).lower() for i in inventory if i.get('product_name')}
    return list({*config_products, *inventory_products})


def regex_intent_extractor(query: str) -> dict:
    """Fallback: extract keywords from query using regex and fuzzy matching."""
    query_lower = query.lower()
    vocab = _product_vocab()
    keywords: list[str] = []

    # direct substring matches
    for p in vocab:
        if p and p in query_lower:
            keywords.append(p)

    # try fuzzy match on individual tokens if nothing obvious
    if not keywords:
        tokens = re.findall(r"[\w']+", query_lower)
        for token in tokens:
            matches = get_close_matches(token, vocab, n=1, cutoff=0.8)
            if matches:
                keywords.append(matches[0])
                break

    # Determine intent
    intent = "search"
    if any(w in query_lower for w in ['cheap', 'cheapest', 'less price', 'sasta', 'low price']):
        intent = "cheapest"
    elif any(w in query_lower for w in ['fresh', 'freshest', 'best quality', 'achi quality']):
        intent = "freshest"
    elif any(w in query_lower for w in ['near', 'nearby', 'close', 'paas']):
        intent = "nearest"

    return {"keywords": keywords, "intent": intent, "source": "regex_fallback"}


def llm_intent_extractor(query: str) -> dict:
    """
    Use Gemini to extract intent and product keywords from consumer query.
    """
    if not GEMINI_API_KEY:
        raise ValueError("No GEMINI_API_KEY")

    prompt = f"""You are a rural market assistant. Extract intent and product keywords from this consumer query.

Query: "{query}"

Return ONLY a JSON object (no markdown):
{{
  "keywords": ["product1", "product2"],
  "intent": "cheapest|freshest|nearest|search"
}}

intent meanings:
- cheapest: user wants lowest price
- freshest: user wants freshest/best quality  
- nearest: user wants closest vendor
- search: general search

Keep keywords as simple English product names (lowercase).
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 100}
    }

    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json=payload,
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    raw = data['candidates'][0]['content']['parts'][0]['text'].strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    result = json.loads(raw)
    result['source'] = 'gemini'
    return result


def search_products(query_text: str, consumer_id: int) -> dict:
    """
    Main entry point for Discovery Agent.
    Returns ranked list of matching inventory items.
    """
    # Extract intent
    try:
        intent_data = llm_intent_extractor(query_text)
    except Exception as e:
        print(f"[DiscoveryAgent] LLM failed ({e}), using regex fallback")
        intent_data = regex_intent_extractor(query_text)

    keywords = intent_data.get("keywords", [])
    intent = intent_data.get("intent", "search")

    # If no keywords found, try direct text matching against vocab
    if not keywords:
        query_lower = query_text.lower()
        vocab = _product_vocab()
        for p in vocab:
            if p and p in query_lower:
                keywords.append(p)

    # Load data
    inventory = load_json('inventory.json')
    consumer = get_consumer_by_id(consumer_id)

    # Filter inventory by keywords
    results = []
    for item in inventory:
        if item.get('quantity', 0) <= 0:
            continue
        item_name = item['product_name'].lower()
        match = False
        if keywords:
            for kw in keywords:
                if kw in item_name or item_name in kw:
                    match = True
                    break
        else:
            match = True  # No keywords = show all

        if match:
            vendor = get_vendor_by_id(item['vendor_id'])
            dist = 0.0
            if consumer and vendor:
                dist = euclidean_distance(
                    consumer.get('lat', 0), consumer.get('lng', 0),
                    vendor.get('lat', 0), vendor.get('lng', 0)
                )
            results.append({
                **item,
                "vendor_name": vendor.get('name', 'Unknown'),
                "distance_km": round(dist, 2),
                "freshness_label": normalize_freshness(item.get('freshness', 3))
            })

    # Rank by intent
    if intent == "cheapest":
        results.sort(key=lambda x: x['price'])
    elif intent == "freshest":
        results.sort(key=lambda x: (-x['freshness'], x['distance_km']))
    elif intent == "nearest":
        results.sort(key=lambda x: x['distance_km'])
    else:
        # Default: score = freshness * 0.4 - distance * 0.3 - price * 0.001
        results.sort(key=lambda x: (-(x['freshness'] * 0.4 - x['distance_km'] * 0.3)))

    return {
        "query": query_text,
        "intent": intent,
        "keywords": keywords,
        "source": intent_data.get("source", "unknown"),
        "results": results[:10]  # Top 10
    }