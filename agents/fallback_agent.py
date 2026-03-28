"""Fallback Agent – Simulates SMS/USSD channel for offline rural users.

Parses simple text commands and routes to internal functions.
Command words are looked up from configuration and
matched with a tiny fuzzy layer so we are not tied
to hardcoded keywords.
"""
import os
from difflib import get_close_matches

from .utils import load_json, load_domain_config, get_vendor_by_id, normalize_freshness
from .udhar_agent import create_udhar, pay_udhar


DEFAULT_VENDOR_ID = int(os.getenv("SMS_DEFAULT_VENDOR_ID", "1"))


def _command_map() -> dict:
    """Return configured SMS commands from domain config.

    The structure is {canonical: [alias1, alias2, ...]}.
    """
    cfg = load_domain_config()
    return cfg.get("sms_commands", {})


def _normalise_command(token: str) -> str | None:
    """Map an incoming token to a canonical command using aliases + fuzzy match."""
    token = token.upper()
    if not token:
        return None

    commands = _command_map()
    # direct alias hit
    for canonical, aliases in commands.items():
        if token == canonical or token in (a.upper() for a in aliases):
            return canonical

    # fuzzy match against all known aliases if no direct hit
    all_aliases: list[str] = []
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in commands.items():
        for a in aliases:
            upper = a.upper()
            all_aliases.append(upper)
            alias_to_canonical[upper] = canonical

    if all_aliases:
        match = get_close_matches(token, all_aliases, n=1, cutoff=0.8)
        if match:
            return alias_to_canonical.get(match[0])

    return None


def parse_sms(sms_text: str) -> str:
    """
    Parse an SMS command and return a plain-text response.

    Supported commands:
      PRICE <product>              → Show prices for a product
      BUY <product> <qty>          → Confirm intent to buy (mock)
      UDHAR <name> <amount>        → Create udhar via SMS (uses vendor_id=1 as default)
      PAY <txn_id>                 → Mark udhar as paid
      LIST                         → List all available products
      HELP                         → Show command list
    """
    text = sms_text.strip()
    parts = text.split()

    if not parts:
        return "Empty message. Send HELP for commands."

    cmd = _normalise_command(parts[0])

    if not cmd:
        return f"Unknown command: '{parts[0]}'. Send HELP for list of commands."

    # ── HELP ──
    if cmd == "HELP":
        return (
            "Krishi Saarthi SMS Commands:\n"
            "PRICE <item> - Check price\n"
            "BUY <item> <qty> - Place buy intent\n"
            "UDHAR <name> <amount> - Create credit\n"
            "PAY <txnID> - Pay udhar\n"
            "LIST - All products\n"
            "HELP - This message"
        )

    # ── LIST ──
    elif cmd == "LIST":
        inventory = load_json('inventory.json')
        lines = ["Available Products:"]
        for item in inventory[:8]:
            lines.append(f"- {item['product_name']}: ₹{item['price']}/{item['unit']} [{normalize_freshness(item['freshness'])}]")
        return "\n".join(lines)

    # ── PRICE <product> ──
    elif cmd == "PRICE" and len(parts) >= 2:
        product = parts[1].capitalize()
        inventory = load_json('inventory.json')
        matches = [i for i in inventory if product.lower() in i['product_name'].lower()]
        if not matches:
            return f"No listings found for '{product}'."
        lines = [f"Prices for {product}:"]
        for m in matches:
            vendor = get_vendor_by_id(m['vendor_id'])
            lines.append(f"- {vendor.get('name','?')}: ₹{m['price']}/{m['unit']} (Qty:{m['quantity']})")
        return "\n".join(lines)

    # ── BUY <product> <qty> ──
    elif cmd == "BUY" and len(parts) >= 3:
        product = parts[1].capitalize()
        try:
            qty = float(parts[2])
        except ValueError:
            return "Invalid quantity. Example: BUY TOMATO 5"
        inventory = load_json('inventory.json')
        matches = [i for i in inventory if product.lower() in i['product_name'].lower() and i['quantity'] >= qty]
        if not matches:
            return f"No stock for {product} (qty {qty}). Try LIST."
        best = sorted(matches, key=lambda x: x['price'])[0]
        vendor = get_vendor_by_id(best['vendor_id'])
        total = best['price'] * qty
        return (
            f"BUY CONFIRMED (mock):\n"
            f"{product} x{qty}{best['unit']}\n"
            f"Vendor: {vendor.get('name','?')}\n"
            f"Price: ₹{best['price']}/{best['unit']}\n"
            f"Total: ₹{total}\n"
            f"Visit vendor to complete purchase."
        )

    # ── UDHAR <name> <amount> ──
    elif cmd == "UDHAR" and len(parts) >= 3:
        name = parts[1].capitalize()
        try:
            amount = float(parts[2])
        except ValueError:
            return "Invalid amount. Example: UDHAR RAM 500"
        result = create_udhar(vendor_id=DEFAULT_VENDOR_ID, consumer_name=name, amount=amount)
        if result['success']:
            return f"Udhar created!\nID: {result['transaction_id']}\nFor: {name}\nAmount: ₹{amount}\nSave this ID to pay later."
        return f"Error: {result['message']}"

    # ── PAY <txnID> ──
    elif cmd == "PAY" and len(parts) >= 2:
        txn_id = parts[1].upper()
        result = pay_udhar(txn_id)
        if result['success']:
            return f"Payment recorded!\nTxn: {txn_id}\n{result['message']}"
        return f"Error: {result['message']}"

    else:
        return f"Unknown command: '{parts[0]}'. Send HELP for list of commands."


def get_ussd_tree() -> dict:
    """
    Return a static USSD menu tree structure for simulation.
    """
    return {
        "welcome": "Welcome to Krishi Saarthi\n1. Check Prices\n2. My Udhar\n3. List Products\n4. Help\n0. Exit",
        "menu": {
            "1": {
                "prompt": "Enter product name:",
                "action": "PRICE_LOOKUP"
            },
            "2": {
                "prompt": "Enter your name:",
                "action": "UDHAR_STATUS"
            },
            "3": {
                "prompt": "Showing all products...",
                "action": "LIST_ALL"
            },
            "4": {
                "prompt": "Send SMS to 1234:\nPRICE <item>\nBUY <item> <qty>\nUDHAR <name> <amount>\nPAY <txnID>",
                "action": "HELP"
            }
        }
    }