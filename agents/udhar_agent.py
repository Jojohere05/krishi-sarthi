"""
Udhar Agent – Manages informal credit (create, pay, audit trail).
Every operation is immutably logged in udhar_ledger.json.
"""
from datetime import datetime
from .utils import load_json, save_json, get_vendor_by_id
import uuid


def _timestamp() -> str:
    return datetime.now().isoformat(timespec='seconds')


def create_udhar(vendor_id: int, consumer_name: str, amount: float, meta: dict | None = None) -> dict:
    """Create a new udhar (credit) entry with initial audit log entry.

    The optional ``meta`` dict can be used by higher-level
    conversational flows to attach extra audit information
    like voice confirmations, created_by, etc. This keeps
    the core ledger structure stable while allowing richer
    context.
    """
    ledger = load_json('udhar_ledger.json')
    vendor = get_vendor_by_id(vendor_id)
    vendor_name = vendor.get('name', f'Vendor {vendor_id}')

    txn_id = "U" + str(uuid.uuid4())[:6].upper()
    now = _timestamp()

    entry = {
        "id": txn_id,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "consumer_name": consumer_name,
        "amount": amount,
        "status": "pending",
        "timestamp": now,
        "audit_log": [
            {
                "action": "CREATE",
                "timestamp": now,
                "details": f"Vendor {vendor_name} ne {consumer_name} ko ₹{amount} ka udhar diya."
            }
        ]
    }

    if meta:
        entry.update(meta)

    ledger.append(entry)
    save_json('udhar_ledger.json', ledger)

    return {
        "success": True,
        "transaction_id": txn_id,
        "message": f"₹{amount} ka udhar {consumer_name} ke naam par bana diya gaya hai. Transaction ID: {txn_id}",
        "entry": entry
    }


def pay_udhar(transaction_id: str, amount_paid: float = None) -> dict:
    """
    Mark an udhar as paid (full or partial). Appends PAY event to audit log.
    """
    ledger = load_json('udhar_ledger.json')

    for txn in ledger:
        if txn['id'] == transaction_id:
            if txn['status'] == 'paid':
                return {"success": False, "message": f"Transaction {transaction_id} ka pura bhugtaan pehle hi ho chuka hai."}

            now = _timestamp()
            pay_amount = amount_paid if amount_paid else txn['amount']

            # Determine if partial or full
            if pay_amount >= txn['amount']:
                txn['status'] = 'paid'
                detail = f"₹{pay_amount} ka pura bhugtaan mil gaya hai. Status 'paid' ho gaya hai."
            else:
                txn['status'] = 'partial'
                txn['amount'] = txn['amount'] - pay_amount
                detail = f"₹{pay_amount} ka hissaana bhugtaan mil gaya hai. Ab baki ₹{txn['amount']} reh gaya hai."

            txn['audit_log'].append({
                "action": "PAY",
                "timestamp": now,
                "details": detail
            })

            save_json('udhar_ledger.json', ledger)
            return {
                "success": True,
                "message": detail,
                "entry": txn
            }

    return {"success": False, "message": f"Transaction ID '{transaction_id}' nahi mila."}


def get_audit_log(vendor_id: int) -> dict:
    """
    Fetch all udhar transactions for a vendor with full audit trails.
    """
    ledger = load_json('udhar_ledger.json')
    vendor_txns = [t for t in ledger if t.get('vendor_id') == vendor_id]
    vendor = get_vendor_by_id(vendor_id)

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.get('name', 'Unknown'),
        "total_transactions": len(vendor_txns),
        "transactions": vendor_txns
    }