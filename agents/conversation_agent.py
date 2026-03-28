"""Conversation Agent – Central voice-first engine for /api/voice.

This module turns free-form voice text into a conversational
experience for rural vendors and consumers. It is designed to:
- detect high-level intent (via Ollama + keyword fallback),
- manage simple multi-step conversation state,
- call existing domain agents (listing, discovery, udhar), and
- always return Hindi reply text for TTS.
"""
from __future__ import annotations

import os
import re
import json
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

from .utils import load_json, save_json, get_vendor_by_id, get_consumer_by_id
from .listing_agent import extract_product
from .discovery_agent import search_products
from .udhar_agent import create_udhar, pay_udhar, get_audit_log

# Load environment variables (for Ollama configuration)
load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL_CONVERSATION", os.getenv("OLLAMA_MODEL", "phi3:latest"))
PENDING_UDHAR_FILE = "pending_udhar.json"


def _safe_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure we always have a mutable dict state."""
    return dict(state) if isinstance(state, dict) else {}


def _call_ollama(prompt: str) -> Optional[Dict[str, Any]]:
    """Small helper to call a local Ollama model and parse JSON response.

    Returns a dict when parsing succeeds, otherwise None. Any exception is
    swallowed so that callers can gracefully fall back to keyword logic.
    """
    if not OLLAMA_MODEL:
        return None

    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        raw = str(data.get("response", "")).strip()
    except Exception:
        return None

    # Strip optional markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Extract first JSON object
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


# ──────────────────────────────────────────────
# Intent detection
# ──────────────────────────────────────────────

VENDOR_INTENTS = {
    "register_shop",
    "add_product",
    "view_orders",
    "view_udhar",
    "mark_paid",
    "create_udhar",
}

CONSUMER_INTENTS = {
    "register_user",
    "search_product",
    "place_order",
    "view_udhar",
    "pay_udhar",
}


def _detect_intent_llm(role: str, voice_text: str) -> Optional[str]:
    """Try to detect intent using the LLM.

    Returns intent string or None if LLM is unavailable/uncertain.
    """
    role = role.lower()
    allowed = VENDOR_INTENTS if role == "vendor" else CONSUMER_INTENTS

    prompt = f"""You are a voice assistant for a rural commerce app.
User role: {role}
User sentence: "{voice_text}"

Choose exactly ONE intent from this list (or "unknown" if you are not sure):
{sorted(allowed)}

Return ONLY a JSON object like:
{{"intent": "register_shop"}}
"""

    data = _call_ollama(prompt)
    if not data:
        return None

    intent = str(data.get("intent", "")).strip()
    return intent if intent in allowed else None


def _detect_intent_keyword(role: str, voice_text: str) -> str:
    """Fallback keyword-based intent detection.

    Very lightweight and biased towards Hindi phrases.
    """
    text = voice_text.lower()
    role = role.lower()

    if role == "vendor":
        if any(k in text for k in ["register", "registration", "dukaan", "shop"]):
            return "register_shop"
        if any(k in text for k in ["product add", "naya product", "maal add", "bechna", "listing"]):
            return "add_product"
        # More specific "udhar dena" style phrases first
        if any(k in text for k in ["udhar dena", "karza dena", "credit dena"]):
            return "create_udhar"
        if any(k in text for k in ["order", "orders", "booking", "order dekh", "order dekho"]):
            return "view_orders"
        if any(k in text for k in ["udhar", "baki", "karza"]):
            return "view_udhar"
        if any(k in text for k in ["mark paid", "paid ho gaya", "chuka diya", "clear udhar"]):
            return "mark_paid"

    else:  # consumer
        if any(k in text for k in ["register", "registration", "naam", "address", "pata", "naya grahak"]):
            return "register_user"
        if any(k in text for k in ["chahiye", "kharidna", "lena hai", "dhoond", "search", "sasta", "cheap"]):
            return "search_product"
        if any(k in text for k in ["order", "book", "mangwana", "bhej do"]):
            return "place_order"
        if any(k in text for k in ["udhar", "baki", "karza"]):
            return "view_udhar"
        if any(k in text for k in ["pay", "bhugtaan", "chukana", "udhar bharna"]):
            return "pay_udhar"

    return "unknown"


def detect_intent(role: str, voice_text: str) -> str:
    """Hybrid intent detection: LLM first, then keyword fallback."""
    intent = _detect_intent_llm(role, voice_text)
    if intent:
        return intent
    return _detect_intent_keyword(role, voice_text)


# ──────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────


def _next_id(items: list, key: str = "id") -> int:
    return max((i.get(key, 0) for i in items), default=0) + 1


def _parse_yes_no(text: str) -> Optional[bool]:
    t = text.lower().strip()
    if any(k in t for k in ["haan", "ha", "yes", "theek", "thik", "ok"]):
        return True
    if any(k in t for k in ["nahin", "nahi", "no", "mat"]):
        return False
    return None


def _parse_number(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_option_choice(text: str) -> Optional[int]:
    """Parse a vendor option choice like "pehla", "dusra", "teesra" or 1/2/3."""
    t = text.lower()
    if any(k in t for k in ["pehla", "first", "1", "ek"]):
        return 1
    if any(k in t for k in ["dusra", "doosra", "second", "2", "do"]):
        return 2
    if any(k in t for k in ["teesra", "third", "3", "teen"]):
        return 3
    return None


# ──────────────────────────────────────────────
# Vendor flows
# ──────────────────────────────────────────────


def _vendor_register_shop(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")

    # Step 1: ask for shop name
    if stage is None or stage == "vendor_home":
        next_state = {
            "role": "vendor",
            "stage": "awaiting_shop_name",
            "current_intent": "register_shop",
        }
        return {
            "reply_text": "Apni dukaan ka naam batayein.",
            "action": "register_shop_ask_name",
            "data": {},
            "next_state": next_state,
        }

    # Step 2: got shop name
    if stage == "awaiting_shop_name":
        shop_name = voice_text.strip()
        if not shop_name:
            return {
                "reply_text": "Mujhe dukaan ka naam clear nahi laga, kripya dobara boliye.",
                "action": "register_shop_retry_name",
                "data": {},
                "next_state": {
                    **state,
                    "stage": "awaiting_shop_name",
                },
            }
        vendors = load_json("vendors.json")
        new_id = _next_id(vendors)
        vendors.append({"id": new_id, "name": shop_name, "lat": 0, "lng": 0})
        save_json("vendors.json", vendors)

        next_state = {
            "role": "vendor",
            "stage": "awaiting_shop_items",
            "current_intent": "register_shop",
            "context": {"vendor_id": new_id, "shop_name": shop_name},
        }
        return {
            "reply_text": f"Dhanyavaad. Aapki dukaan {shop_name} register ho gayi hai. Aap kya bechte hain? Jaise tamatar, aloo, pyaaz.",
            "action": "register_shop_ask_items",
            "data": {"vendor_id": new_id},
            "next_state": next_state,
        }

    # Step 3: got items list
    if stage == "awaiting_shop_items":
        items_text = voice_text.strip()
        ctx = state.get("context", {})
        vendor_id = ctx.get("vendor_id", user_id)
        vendors = load_json("vendors.json")
        for v in vendors:
            if v.get("id") == vendor_id:
                # store raw items text – lightweight
                v["items"] = items_text
                break
        save_json("vendors.json", vendors)

        shop_name = ctx.get("shop_name", "aapki dukaan")
        next_state = {
            "role": "vendor",
            "stage": "vendor_home",
            "current_intent": None,
            "context": {"vendor_id": vendor_id, "shop_name": shop_name},
        }
        return {
            "reply_text": f"Registration poora ho gaya. {shop_name} ke liye ab aap naya product add kar sakte hain, orders dekh sakte hain, ya udhar dekh sakte hain.",
            "action": "register_shop_done",
            "data": {"vendor_id": vendor_id},
            "next_state": next_state,
        }

    # Fallback
    return {
        "reply_text": "Mujhe registration ka step samajh nahi aaya, kripya phir se boliye.",
        "action": "register_shop_confused",
        "data": {},
        "next_state": {"role": "vendor", "stage": "vendor_home"},
    }


def _vendor_add_product(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")
    ctx = state.get("context", {})
    vendor_id = ctx.get("vendor_id", user_id)

    # Step 1: ask for product details
    if stage is None or stage in {"vendor_home", "awaiting_shop_items"}:
        next_state = {
            "role": "vendor",
            "stage": "awaiting_product_details",
            "current_intent": "add_product",
            "context": {"vendor_id": vendor_id},
        }
        return {
            "reply_text": "Kripya product detail boliye, jaise: 50 kilo tamatar 40 rupaye kilo.",
            "action": "add_product_ask_details",
            "data": {},
            "next_state": next_state,
        }

    # Step 2: parse product details (but do not save yet)
    if stage == "awaiting_product_details":
        product = extract_product(voice_text)
        qty = product.get("quantity", 0)
        unit = product.get("unit", "kg")
        name = product.get("product", "maal")
        price = product.get("price", 0)

        if qty <= 0 or price <= 0 or not name:
            return {
                "reply_text": "Mujhe quantity ya daam clear nahi laga, kripya dobara detail boliye.",
                "action": "add_product_retry_details",
                "data": {},
                "next_state": {
                    **state,
                    "stage": "awaiting_product_details",
                    "context": {"vendor_id": vendor_id},
                },
            }

        msg = f"Aap {qty} {unit} {name} {price} rupaye {unit} mein bech rahe hain. Kya yeh sahi hai?"
        next_state = {
            "role": "vendor",
            "stage": "awaiting_product_confirm",
            "current_intent": "add_product",
            "context": {"vendor_id": vendor_id, "pending_product": product},
        }
        return {
            "reply_text": msg,
            "action": "add_product_confirm",
            "data": {"preview": product},
            "next_state": next_state,
        }

    # Step 3: confirmation
    if stage == "awaiting_product_confirm":
        answer = _parse_yes_no(voice_text)
        ctx = state.get("context", {})
        vendor_id = ctx.get("vendor_id", vendor_id)
        pending = ctx.get("pending_product") or {}

        if answer is None:
            return {
                "reply_text": "Kripya sirf haan ya nahin boliye. Kya product detail sahi hai?",
                "action": "add_product_confirm_retry",
                "data": {},
                "next_state": state,
            }

        if not answer:
            # go back to details
            next_state = {
                "role": "vendor",
                "stage": "awaiting_product_details",
                "current_intent": "add_product",
                "context": {"vendor_id": vendor_id},
            }
            return {
                "reply_text": "Thik hai, kripya dobara product detail boliye.",
                "action": "add_product_restart",
                "data": {},
                "next_state": next_state,
            }

        # Save to inventory
        inventory = load_json("inventory.json")
        new_item = {
            "id": _next_id(inventory),
            "vendor_id": vendor_id,
            "product_name": pending.get("product", "Unknown"),
            "price": pending.get("price", 0),
            "unit": pending.get("unit", "kg"),
            "quantity": pending.get("quantity", 0),
            "freshness": pending.get("freshness", 3),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        inventory.append(new_item)
        save_json("inventory.json", inventory)

        next_state = {
            "role": "vendor",
            "stage": "vendor_home",
            "current_intent": None,
            "context": {"vendor_id": vendor_id},
        }
        return {
            "reply_text": f"Product add ho gaya: {new_item['product_name']} {new_item['price']} rupaye {new_item['unit']}.",
            "action": "add_product_saved",
            "data": {"item": new_item},
            "next_state": next_state,
        }

    # Fallback
    return {
        "reply_text": "Mujhe product flow samajh nahi aaya, kripya dobara simple tarike se batayein.",
        "action": "add_product_confused",
        "data": {},
        "next_state": {"role": "vendor", "stage": "vendor_home"},
    }


def _vendor_create_udhar(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Vendor-initiated udhar creation with later consumer voice confirmation.

    This function only creates a pending udhar request. The actual immutable
    udhar entry is written to the ledger only after the consumer confirms
    in their own conversation flow.
    """
    stage = state.get("stage")
    ctx = state.get("context", {})
    vendor_id = ctx.get("vendor_id", user_id)

    # Step 1: ask for consumer name
    if stage is None or stage == "vendor_home":
        next_state = {
            "role": "vendor",
            "stage": "awaiting_udhar_consumer_name_vendor",
            "current_intent": "create_udhar",
            "context": {"vendor_id": vendor_id},
        }
        return {
            "reply_text": "Kis grahak ko udhar dena hai? Kripya naam batayein.",
            "action": "create_udhar_ask_consumer_name",
            "data": {},
            "next_state": next_state,
        }

    # Step 2: capture consumer name
    if stage == "awaiting_udhar_consumer_name_vendor":
        consumer_name = voice_text.strip()
        if not consumer_name:
            return {
                "reply_text": "Grahak ka naam clear nahi aaya, kripya dobara boliye.",
                "action": "create_udhar_retry_consumer_name",
                "data": {},
                "next_state": state,
            }
        next_state = {
            "role": "vendor",
            "stage": "awaiting_udhar_amount_vendor",
            "current_intent": "create_udhar",
            "context": {"vendor_id": vendor_id, "consumer_name": consumer_name},
        }
        return {
            "reply_text": "Kitna udhar dena hai? Rakam batayein, jaise 200 rupaye.",
            "action": "create_udhar_ask_amount",
            "data": {},
            "next_state": next_state,
        }

    # Step 3: capture amount and create pending request
    if stage == "awaiting_udhar_amount_vendor":
        amount = _parse_number(voice_text)
        ctx = state.get("context", {})
        consumer_name = ctx.get("consumer_name", "Grahak")
        if not amount or amount <= 0:
            return {
                "reply_text": "Mujhe rakam samajh nahi aayi, kripya dobara boliye (jaise 200 rupaye).",
                "action": "create_udhar_retry_amount",
                "data": {},
                "next_state": state,
            }

        pending_list = load_json(PENDING_UDHAR_FILE)
        pending_id = f"PU{int(time.time() * 1000)}"
        pending_entry = {
            "id": pending_id,
            "vendor_id": vendor_id,
            "consumer_name": consumer_name,
            "amount": float(amount),
            "status": "awaiting_consumer",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "created_by": vendor_id,
        }
        pending_list.append(pending_entry)
        save_json(PENDING_UDHAR_FILE, pending_list)

        next_state = {
            "role": "vendor",
            "stage": "vendor_home",
            "current_intent": None,
            "context": {"vendor_id": vendor_id},
        }
        reply = (
            f"Thik hai, {consumer_name} ke liye {int(amount)} rupaye udhar ka request bana diya gaya hai. "
            f"Jab grahak haan bolega tab hum udhar register karenge."
        )
        return {
            "reply_text": reply,
            "action": "create_udhar_pending_created",
            "data": {"pending_udhar": pending_entry},
            "next_state": next_state,
        }

    # Fallback
    return {
        "reply_text": "Mujhe udhar creation flow samajh nahi aaya, kripya phir se batayein.",
        "action": "create_udhar_confused",
        "data": {},
        "next_state": {"role": "vendor", "stage": "vendor_home"},
    }


def _vendor_view_orders(user_id: int, state: Dict[str, Any]) -> Dict[str, Any]:
    ctx = state.get("context", {})
    vendor_id = ctx.get("vendor_id", user_id)
    orders = load_json("orders.json")
    my_orders = [o for o in orders if o.get("vendor_id") == vendor_id]

    if not my_orders:
        reply = "Abhi aapke paas koi naya order nahi hai."
    else:
        parts = []
        for o in my_orders[:3]:
            cname = o.get("consumer_name", "ek grahak")
            caddr = o.get("consumer_address") or ""
            qty = o.get("quantity", 0)
            unit = o.get("unit", "kg")
            pname = o.get("product_name", "maal")
            if caddr:
                parts.append(f"{cname}, pata {caddr}, ne {qty} {unit} {pname} order kiya hai.")
            else:
                parts.append(f"{cname} ne {qty} {unit} {pname} order kiya hai.")
        reply = "Aapke kuch orders hain. " + " ".join(parts)

    next_state = {
        "role": "vendor",
        "stage": "vendor_home",
        "current_intent": None,
        "context": {"vendor_id": vendor_id},
    }
    return {
        "reply_text": reply,
        "action": "view_orders",
        "data": {"orders": my_orders},
        "next_state": next_state,
    }


def _vendor_view_udhar(user_id: int, state: Dict[str, Any]) -> Dict[str, Any]:
    ctx = state.get("context", {})
    vendor_id = ctx.get("vendor_id", user_id)
    audit = get_audit_log(vendor_id)
    txns = audit.get("transactions", [])

    if not txns:
        reply = "Abhi kisi grahak ka udhar record nahi hai."
    else:
        total = len(txns)
        open_txns = [t for t in txns if t.get("status") != "paid"]
        if not open_txns:
            reply = f"Aapke sabhi {total} udhar transactions paid dikh rahe hain."
        else:
            names = {t.get("consumer_name", "") for t in open_txns}
            reply = f"Kuch grahakon ka udhar baaki hai: " + ", ".join(sorted(n for n in names if n)) + "."

    next_state = {
        "role": "vendor",
        "stage": "vendor_home",
        "current_intent": None,
        "context": {"vendor_id": vendor_id},
    }
    return {
        "reply_text": reply,
        "action": "view_udhar_vendor",
        "data": audit,
        "next_state": next_state,
    }


def _vendor_mark_paid(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")

    if stage is None or stage == "vendor_home":
        next_state = {
            "role": "vendor",
            "stage": "awaiting_udhar_txn_id_vendor",
            "current_intent": "mark_paid",
        }
        return {
            "reply_text": "Kripya udhar transaction ID batayein, jaise UABC12.",
            "action": "mark_paid_ask_txn",
            "data": {},
            "next_state": next_state,
        }

    if stage == "awaiting_udhar_txn_id_vendor":
        txn_id = voice_text.strip().replace(" ", "").upper()
        result = pay_udhar(txn_id)
        if not result.get("success"):
            reply = f"Transaction ID samajh nahi aaya ya nahi mila. {result.get('message', '')}"
        else:
            reply = f"Thik hai. {result.get('message', '')}"

        next_state = {
            "role": "vendor",
            "stage": "vendor_home",
            "current_intent": None,
        }
        return {
            "reply_text": reply,
            "action": "mark_paid_done",
            "data": result,
            "next_state": next_state,
        }

    return {
        "reply_text": "Mujhe udhar mark paid flow samajh nahi aaya, kripya dobara batayein.",
        "action": "mark_paid_confused",
        "data": {},
        "next_state": {"role": "vendor", "stage": "vendor_home"},
    }


# ──────────────────────────────────────────────
# Consumer flows
# ──────────────────────────────────────────────


def _consumer_register(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")

    if stage is None or stage == "consumer_home":
        next_state = {
            "role": "consumer",
            "stage": "awaiting_consumer_name",
            "current_intent": "register_user",
        }
        return {
            "reply_text": "Apna naam batayein.",
            "action": "register_user_ask_name",
            "data": {},
            "next_state": next_state,
        }

    if stage == "awaiting_consumer_name":
        name = voice_text.strip()
        if not name:
            return {
                "reply_text": "Naam clear nahi aaya, kripya dobara boliye.",
                "action": "register_user_retry_name",
                "data": {},
                "next_state": {"role": "consumer", "stage": "awaiting_consumer_name"},
            }
        next_state = {
            "role": "consumer",
            "stage": "awaiting_consumer_address",
            "current_intent": "register_user",
            "context": {"pending_name": name},
        }
        return {
            "reply_text": "Apna address batayein, jaise gaon ya basti ka naam.",
            "action": "register_user_ask_address",
            "data": {},
            "next_state": next_state,
        }

    if stage == "awaiting_consumer_address":
        address = voice_text.strip()
        ctx = state.get("context", {})
        name = ctx.get("pending_name", "Grahak")

        consumers = load_json("consumers.json")
        new_id = _next_id(consumers)
        consumer_entry = {"id": new_id, "name": name, "lat": 0, "lng": 0, "address": address}
        consumers.append(consumer_entry)
        save_json("consumers.json", consumers)

        next_state = {
            "role": "consumer",
            "stage": "consumer_home",
            "current_intent": None,
            "context": {"consumer_id": new_id, "name": name, "address": address},
        }
        return {
            "reply_text": f"Dhanyavaad {name}, aapka registration ho gaya. Ab aap kya kharidna chahte hain?",
            "action": "register_user_done",
            "data": {"consumer_id": new_id},
            "next_state": next_state,
        }

    return {
        "reply_text": "Mujhe registration flow samajh nahi aaya, kripya phir se batayein.",
        "action": "register_user_confused",
        "data": {},
        "next_state": {"role": "consumer", "stage": "consumer_home"},
    }


def _consumer_search_and_prepare_order(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    # Step 1: search products, then let user compare vendors and choose one
    ctx = state.get("context", {})
    consumer_id = ctx.get("consumer_id", user_id)

    search_result = search_products(voice_text, consumer_id)
    results = search_result.get("results", [])

    if not results:
        return {
            "reply_text": "Abhi aapke query ke hisaab se koi product nahi mila. Kripya doosre tarike se bolke dekhiye.",
            "action": "search_product_empty",
            "data": search_result,
            "next_state": {
                "role": "consumer",
                "stage": "consumer_home",
                "current_intent": None,
                "context": ctx,
            },
        }

    top = results[:3]
    option_ctx = []
    parts = []
    for idx, item in enumerate(top, start=1):
        pname = item.get("product_name", "maal")
        price = item.get("price", 0)
        unit = item.get("unit", "kg")
        vname = item.get("vendor_name", "vendor")
        dist = item.get("distance_km", 0)
        parts.append(f"{idx}) {vname}, {price} rupaye {unit}, {pname}, lagbhag {dist} kilometer.")
        option_ctx.append(
            {
                "product_name": pname,
                "price": price,
                "unit": unit,
                "vendor_id": item.get("vendor_id"),
                "vendor_name": vname,
            }
        )

    reply = (
        "Maine kuch options dhundhe hain. "
        + " ".join(parts)
        + " Kaun sa vendor chunna chahenge? Pehla, doosra ya teesra?"
    )

    next_state = {
        "role": "consumer",
        "stage": "awaiting_vendor_choice",
        "current_intent": "place_order",
        "context": {
            **ctx,
            "consumer_id": consumer_id,
            "vendor_options": option_ctx,
        },
    }
    return {
        "reply_text": reply,
        "action": "search_product_suggest_options",
        "data": {"options": top},
        "next_state": next_state,
    }


def _consumer_choose_vendor_and_ask_qty(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Handle choice among multiple vendor options, then ask for quantity."""
    ctx = state.get("context", {})
    consumer_id = ctx.get("consumer_id", user_id)
    options = ctx.get("vendor_options") or []
    choice = _parse_option_choice(voice_text)

    if not choice or choice < 1 or choice > len(options):
        return {
            "reply_text": "Mujhe vendor ka number clear nahi aaya. Kripya boliye pehla, doosra ya teesra vendor.",
            "action": "choose_vendor_retry",
            "data": {},
            "next_state": state,
        }

    chosen = options[choice - 1]
    pname = chosen.get("product_name", "maal")
    price = chosen.get("price", 0)
    unit = chosen.get("unit", "kg")
    vname = chosen.get("vendor_name", "vendor")

    reply = f"Aapne {vname} ko chuna hai. {pname} kitna lena chahenge?"

    next_state = {
        "role": "consumer",
        "stage": "awaiting_order_quantity",
        "current_intent": "place_order",
        "context": {
            **ctx,
            "consumer_id": consumer_id,
            "pending_order_item": chosen,
        },
    }
    return {
        "reply_text": reply,
        "action": "choose_vendor_done",
        "data": {"chosen": chosen},
        "next_state": next_state,
    }


def _consumer_place_order(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")
    ctx = state.get("context", {})

    if stage != "awaiting_order_quantity":
        # If user directly said something like "order karna hai" without search,
        # we first search using the same sentence.
        return _consumer_search_and_prepare_order(user_id, voice_text, state)

    consumer_id = ctx.get("consumer_id", user_id)
    item = ctx.get("pending_order_item") or {}
    qty = _parse_number(voice_text)
    if not qty or qty <= 0:
        return {
            "reply_text": "Mujhe quantity samajh nahi aayi, kripya kitna lena hai woh clear bolein (jaise 2 kilo).",
            "action": "place_order_retry_qty",
            "data": {},
            "next_state": state,
        }

    orders = load_json("orders.json")
    new_id = _next_id(orders)
    order = {
        "id": new_id,
        "consumer_id": consumer_id,
        "consumer_name": ctx.get("name", "Grahak"),
        "vendor_id": item.get("vendor_id"),
        "vendor_name": item.get("vendor_name"),
        "product_name": item.get("product_name"),
        "unit": item.get("unit", "kg"),
        "quantity": qty,
        "price": item.get("price", 0),
        "consumer_address": ctx.get("address"),
        "status": "pending",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    orders.append(order)
    save_json("orders.json", orders)

    reply = (
        f"Aapka {qty} {order['unit']} {order['product_name']} ka order {order['vendor_name']} ke yahan se confirm ho gaya hai."
    )
    next_state = {
        "role": "consumer",
        "stage": "consumer_home",
        "current_intent": None,
        "context": {**ctx, "consumer_id": consumer_id},
    }
    return {
        "reply_text": reply,
        "action": "place_order_done",
        "data": {"order": order},
        "next_state": next_state,
    }


def _consumer_view_udhar(user_id: int, state: Dict[str, Any]) -> Dict[str, Any]:
    ctx = state.get("context", {})
    name = (ctx.get("name") or "").lower()
    stage = state.get("stage")

    # Check if there is any pending udhar request for this consumer
    pending_list = load_json(PENDING_UDHAR_FILE)
    pending_for_me = None
    if name:
        for p in pending_list:
            cname = str(p.get("consumer_name", "")).lower()
            if p.get("status") == "awaiting_consumer" and cname.startswith(name):
                pending_for_me = p
                break

    # If we are already in the confirmation step, handle yes/no
    if stage == "awaiting_pending_udhar_confirm" and ctx.get("pending_udhar"):
        pending = ctx["pending_udhar"]
        answer = _parse_yes_no(state.get("_last_input", ""))  # voice_text is not passed here; will be set in handle
        # This helper relies on handle_conversation to stuff the latest
        # utterance into state["_last_input"] just before calling us.
        if answer is None:
            return {
                "reply_text": "Kripya sirf haan ya nahin boliye. Kya aap udhar confirm karte hain?",
                "action": "confirm_udhar_retry",
                "data": {},
                "next_state": state,
            }

        # Reload list to update status safely
        updated = load_json(PENDING_UDHAR_FILE)
        for p in updated:
            if p.get("id") == pending.get("id"):
                if answer:
                    p["status"] = "confirmed"
                    p["voice_confirmation"] = "haan"
                    p["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
                    # Write real udhar entry to ledger with extra meta
                    create_udhar(
                        vendor_id=p.get("vendor_id"),
                        consumer_name=p.get("consumer_name", "Grahak"),
                        amount=p.get("amount", 0),
                        meta={
                            "created_by": p.get("created_by"),
                            "voice_confirmation": "haan",
                        },
                    )
                    reply = "Udhar confirm ho gaya aur ledger mein add kar diya gaya hai."
                else:
                    p["status"] = "rejected"
                    p["rejected_at"] = datetime.now().isoformat(timespec="seconds")
                    reply = "Thik hai, yeh udhar request cancel kar diya gaya hai."
                break
        save_json(PENDING_UDHAR_FILE, updated)

        next_state = {
            "role": "consumer",
            "stage": "consumer_home",
            "current_intent": None,
            "context": {k: v for k, v in ctx.items() if k != "pending_udhar"},
        }
        return {
            "reply_text": reply,
            "action": "view_udhar_consumer_after_confirm",
            "data": {},
            "next_state": next_state,
        }

    # Fresh prompt when pending udhar exists
    if pending_for_me and stage in {None, "consumer_home"}:
        vendor = get_vendor_by_id(pending_for_me.get("vendor_id"))
        vname = vendor.get("name", "ek vendor")
        amount = int(pending_for_me.get("amount", 0))
        reply = f"{vname} vendor aapko {amount} rupaye udhar dena chahte hain. Kya aap confirm karte hain?"
        next_state = {
            "role": "consumer",
            "stage": "awaiting_pending_udhar_confirm",
            "current_intent": "view_udhar",
            "context": {**ctx, "pending_udhar": pending_for_me},
        }
        return {
            "reply_text": reply,
            "action": "view_udhar_consumer_pending_prompt",
            "data": {"pending_udhar": pending_for_me},
            "next_state": next_state,
        }

    # Otherwise, normal udhar summary
    ledger = load_json("udhar_ledger.json")

    def _is_for_me(txn: Dict[str, Any]) -> bool:
        cname = str(txn.get("consumer_name", "")).lower()
        return bool(name and cname.startswith(name))

    my_txns = [t for t in ledger if _is_for_me(t)]

    if not my_txns:
        reply = "Abhi aapke naam par koi udhar record nahi mila."
    else:
        open_txns = [t for t in my_txns if t.get("status") != "paid"]
        if not open_txns:
            reply = "Aapka saara udhar clear dikh raha hai. Dhanyavaad."
        else:
            total_due = sum(t.get("amount", 0) for t in open_txns)
            reply = f"Aapko kul lagbhag {int(total_due)} rupaye udhar chukane hain."

    next_state = {
        "role": "consumer",
        "stage": "consumer_home",
        "current_intent": None,
        "context": ctx,
    }
    return {
        "reply_text": reply,
        "action": "view_udhar_consumer",
        "data": {"transactions": my_txns},
        "next_state": next_state,
    }


def _consumer_pay_udhar(user_id: int, voice_text: str, state: Dict[str, Any]) -> Dict[str, Any]:
    stage = state.get("stage")

    if stage is None or stage == "consumer_home":
        next_state = {
            "role": "consumer",
            "stage": "awaiting_udhar_txn_id_consumer",
            "current_intent": "pay_udhar",
        }
        return {
            "reply_text": "Kripya udhar transaction ID batayein jise aap pay karna chahte hain.",
            "action": "pay_udhar_ask_txn",
            "data": {},
            "next_state": next_state,
        }

    if stage == "awaiting_udhar_txn_id_consumer":
        txn_id = voice_text.strip().replace(" ", "").upper()
        result = pay_udhar(txn_id)
        if not result.get("success"):
            reply = f"Transaction ID samajh nahi aaya ya nahi mila. {result.get('message', '')}"
        else:
            reply = f"Bhugtaan record ho gaya. {result.get('message', '')}"

        next_state = {
            "role": "consumer",
            "stage": "consumer_home",
            "current_intent": None,
        }
        return {
            "reply_text": reply,
            "action": "pay_udhar_done",
            "data": result,
            "next_state": next_state,
        }

    return {
        "reply_text": "Mujhe udhar payment flow samajh nahi aaya, kripya phir se batayein.",
        "action": "pay_udhar_confused",
        "data": {},
        "next_state": {"role": "consumer", "stage": "consumer_home"},
    }


# ──────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────


def handle_conversation(user_id: int, role: str, voice_text: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Main entry point for the conversational engine.

    Parameters
    ----------
    user_id: numeric identifier for the caller (vendor_id or consumer_id)
    role: "vendor" or "consumer" (case-insensitive)
    voice_text: speech-to-text text from the user
    state: opaque dict carried by the client between turns
    """
    role = (role or "").lower().strip() or "consumer"
    state = _safe_state(state)
    stage = state.get("stage")

    if not voice_text or not voice_text.strip():
        return {
            "reply_text": "Mujhe kuch bhi clear nahi suna, kripya dobara boliye.",
            "action": "no_input",
            "data": {},
            "next_state": {**state, "role": role, "stage": stage or ("vendor_home" if role == "vendor" else "consumer_home")},
        }

    # Store last input for helpers that need to re-parse inside flows
    state["_last_input"] = voice_text

    # If we are in the middle of a flow, continue that flow without re-detecting intent
    current_intent = state.get("current_intent")

    if role == "vendor":
        if current_intent == "register_shop" or stage in {"awaiting_shop_name", "awaiting_shop_items"}:
            return _vendor_register_shop(user_id, voice_text, state)
        if current_intent == "add_product" or stage in {"awaiting_product_details", "awaiting_product_confirm"}:
            return _vendor_add_product(user_id, voice_text, state)
        if current_intent == "create_udhar" or stage in {"awaiting_udhar_consumer_name_vendor", "awaiting_udhar_amount_vendor"}:
            return _vendor_create_udhar(user_id, voice_text, state)
        if current_intent == "mark_paid" or stage == "awaiting_udhar_txn_id_vendor":
            return _vendor_mark_paid(user_id, voice_text, state)

        # New vendor turn: detect intent
        intent = detect_intent(role, voice_text)
        if intent == "register_shop":
            return _vendor_register_shop(user_id, voice_text, {"role": "vendor"})
        if intent == "add_product":
            return _vendor_add_product(user_id, voice_text, {"role": "vendor", "stage": "vendor_home", "context": state.get("context", {})})
        if intent == "view_orders":
            return _vendor_view_orders(user_id, state)
        if intent == "view_udhar":
            return _vendor_view_udhar(user_id, state)
        if intent == "create_udhar":
            return _vendor_create_udhar(user_id, voice_text, {"role": "vendor", "stage": "vendor_home", "context": state.get("context", {})})
        if intent == "mark_paid":
            return _vendor_mark_paid(user_id, voice_text, state)

        # Unknown vendor intent
        return {
            "reply_text": "Mujhe samajh nahi aaya aap kya karna chahte hain. Aap bol sakte hain: naya product add karo, udhar dekho, ya orders dekho.",
            "action": "unknown_vendor_intent",
            "data": {"raw_text": voice_text},
            "next_state": {"role": "vendor", "stage": "vendor_home", "current_intent": None, "context": state.get("context", {})},
        }

    else:  # consumer
        if current_intent == "register_user" or stage in {"awaiting_consumer_name", "awaiting_consumer_address"}:
            return _consumer_register(user_id, voice_text, state)
        if current_intent == "place_order" and stage == "awaiting_vendor_choice":
            return _consumer_choose_vendor_and_ask_qty(user_id, voice_text, state)
        if current_intent == "place_order" or stage == "awaiting_order_quantity":
            return _consumer_place_order(user_id, voice_text, state)
        if current_intent == "view_udhar" and stage == "awaiting_pending_udhar_confirm":
            return _consumer_view_udhar(user_id, state)
        if current_intent == "pay_udhar" or stage == "awaiting_udhar_txn_id_consumer":
            return _consumer_pay_udhar(user_id, voice_text, state)

        # New consumer turn: detect intent
        intent = detect_intent(role, voice_text)
        if intent == "register_user":
            return _consumer_register(user_id, voice_text, {"role": "consumer"})
        if intent == "search_product":
            return _consumer_search_and_prepare_order(user_id, voice_text, {"role": "consumer", "stage": "consumer_home", "context": state.get("context", {})})
        if intent == "place_order":
            return _consumer_place_order(user_id, voice_text, state)
        if intent == "view_udhar":
            return _consumer_view_udhar(user_id, state)
        if intent == "pay_udhar":
            return _consumer_pay_udhar(user_id, voice_text, state)

        # Unknown consumer intent
        return {
            "reply_text": "Mujhe samajh nahi aaya. Aap bol sakte hain: mujhe tamatar chahiye, ya mera udhar batao, ya registration karna hai.",
            "action": "unknown_consumer_intent",
            "data": {"raw_text": voice_text},
            "next_state": {"role": "consumer", "stage": "consumer_home", "current_intent": None, "context": state.get("context", {})},
        }
