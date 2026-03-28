"""
Krishi Saarthi – FastAPI Backend
Multi-agent AI system for rural agricultural commerce.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uvicorn

from agents.listing_agent import extract_product
from agents.discovery_agent import search_products
from agents.udhar_agent import create_udhar, pay_udhar, get_audit_log
from agents.fallback_agent import parse_sms, get_ussd_tree
from agents.utils import load_json, save_json
from agents.conversation_agent import handle_conversation

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = FastAPI(
    title="Krishi Saarthi API",
    description="Voice-first multi-agent AI system for rural agricultural commerce",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────
class ListingRequest(BaseModel):
    voice_text: str
    vendor_id: int


class DiscoveryRequest(BaseModel):
    query_text: str
    consumer_id: int


class UdharCreateRequest(BaseModel):
    vendor_id: int
    consumer_name: str
    amount: float


class UdharPayRequest(BaseModel):
    transaction_id: str
    amount_paid: Optional[float] = None


class SMSRequest(BaseModel):
    message: str


class VoiceRequest(BaseModel):
    user_id: int
    role: str  # "vendor" or "consumer"
    voice_text: str
    language: Optional[str] = "hi"
    state: Optional[Dict[str, Any]] = None


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "online", "project": "Krishi Saarthi", "version": "1.0.0"}


@app.get("/api/health")
def health():
    return {"status": "healthy"}


@app.post("/api/voice")
def voice_endpoint(req: VoiceRequest):
    """Single conversational endpoint for all voice-first flows.

    This behaves like a human assistant: it detects intent, manages
    multi-step state, and always returns Hindi reply_text suitable
    for text-to-speech.
    """
    result = handle_conversation(
        user_id=req.user_id,
        role=req.role,
        voice_text=req.voice_text,
        state=req.state or {},
    )
    # Ensure minimal contract is always present
    if "reply_text" not in result:
        result["reply_text"] = "Mujhe samajh nahi aaya, kripya dobara boliye."
    result.setdefault("action", None)
    result.setdefault("data", {})
    result.setdefault("next_state", {})
    return result


@app.get("/api/vendors")
def get_vendors():
    """Return list of all vendors."""
    return load_json('vendors.json')


@app.get("/api/consumers")
def get_consumers():
    """Return list of all consumers."""
    return load_json('consumers.json')


@app.post("/api/listing")
def listing_endpoint(req: ListingRequest):
    """
    Listing Agent: Convert vendor voice/text into structured product listing.
    Saves the product to inventory.
    """
    if not req.voice_text.strip():
        raise HTTPException(status_code=400, detail="voice_text cannot be empty")

    product = extract_product(req.voice_text)

    # Save to inventory
    inventory = load_json('inventory.json')
    from datetime import datetime
    new_item = {
        "id": max((i['id'] for i in inventory), default=0) + 1,
        "vendor_id": req.vendor_id,
        "product_name": product.get("product", "Unknown"),
        "price": product.get("price", 0),
        "unit": product.get("unit", "kg"),
        "quantity": product.get("quantity", 0),
        "freshness": product.get("freshness", 3),
        "timestamp": datetime.now().isoformat(timespec='seconds')
    }
    inventory.append(new_item)
    save_json('inventory.json', inventory)

    return {
        "success": True,
        "extracted": product,
        "saved_item": new_item,
        "message": f"Product '{new_item['product_name']}' listed successfully!"
    }


@app.post("/api/discovery")
def discovery_endpoint(req: DiscoveryRequest):
    """
    Discovery Agent: Search and rank products based on consumer voice query.
    """
    if not req.query_text.strip():
        raise HTTPException(status_code=400, detail="query_text cannot be empty")

    result = search_products(req.query_text, req.consumer_id)
    return result


@app.post("/api/udhar/create")
def udhar_create_endpoint(req: UdharCreateRequest):
    """
    Udhar Agent: Create a new credit entry with immutable audit trail.
    """
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if not req.consumer_name.strip():
        raise HTTPException(status_code=400, detail="consumer_name cannot be empty")

    result = create_udhar(req.vendor_id, req.consumer_name.strip(), req.amount)
    return result


@app.post("/api/udhar/pay")
def udhar_pay_endpoint(req: UdharPayRequest):
    """
    Udhar Agent: Record payment against an udhar transaction.
    """
    if not req.transaction_id.strip():
        raise HTTPException(status_code=400, detail="transaction_id cannot be empty")

    result = pay_udhar(req.transaction_id.strip().upper(), req.amount_paid)
    if not result['success']:
        raise HTTPException(status_code=404, detail=result['message'])
    return result


@app.get("/api/udhar/audit/{vendor_id}")
def udhar_audit_endpoint(vendor_id: int):
    """
    Udhar Agent: Fetch full audit log for a vendor's udhar transactions.
    """
    return get_audit_log(vendor_id)


@app.post("/api/fallback/sms")
def sms_endpoint(req: SMSRequest):
    """
    Fallback Agent: Parse SMS command and return plain-text response.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    response = parse_sms(req.message)
    return {"input": req.message, "response": response}


@app.get("/api/fallback/ussd")
def ussd_endpoint():
    """
    Fallback Agent: Return static USSD menu tree.
    """
    return get_ussd_tree()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)