# 🌾 Krishi Saarthi — कृषि सारथी

**Voice-First Multi-Agent AI System for Rural Agricultural Commerce**

> Hackathon Project | Problem Statement #5 – Domain-Specialized AI Agents with Compliance Guardrails

---

## 🚀 Quick Start (5 minutes)

### 1. Clone & Setup
```bash
git clone <repo-url>
cd krishi-saarthi
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy and configure environment (API key optional!)
cp .env.example .env
# Edit .env and add GEMINI_API_KEY if you have one (works without it too)
```

### 3. Run Backend
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs at: http://localhost:8000  
API Docs: http://localhost:8000/docs

### 4. Open Frontend
```bash
# From project root, in a NEW terminal:
cd frontend
python -m http.server 3000
# Then open http://localhost:3000 in Chrome
```

> ⚠️ **Use Chrome** for best Web Speech API support. Serve via HTTP server (not file://) for mic permissions.

---

## 🎬 Demo Script (2-3 min)

### Scene 1 — Vendor Lists a Product (30s)
1. Click **Vendor Listing** tab
2. Select "Ramesh Patil"
3. Click 🎤 and say: *"Mere paas 50 kilo tamatar hai, price 25 rupaye kilo, bilkul fresh"*
4. Click **List Product**
5. Show extracted structure: product, price, quantity, freshness score
6. Point out: "Extracted by AI (or Regex Fallback if no API key)"

### Scene 2 — Buyer Finds Best Product (30s)
1. Click **Buyer Discovery** tab
2. Select "Anita Rao"
3. Say or type: *"I want fresh tomatoes near me at cheap price"*
4. Click **Search Products**
5. Show ranked results table with freshness badges, distances, vendor names
6. Point out intent badge: "cheapest / freshest / nearest"

### Scene 3 — Udhar with Audit Trail (60s)
1. Click **Udhar Ledger** tab
2. Create udhar: Select vendor, type/speak consumer name "Vijay Kumar", amount 500
3. Click **Create Udhar** → show transaction ID
4. Click **Record Payment** with the auto-filled transaction ID
5. Type Vendor ID `1` → Click **Show Audit Log**
6. Show immutable audit trail: CREATE event + PAY event with timestamps

### Scene 4 — Offline SMS Fallback (30s)
1. Click **Offline / SMS** tab
2. Type `HELP` → show command list
3. Type `PRICE TOMATO` → show prices from all vendors
4. Type `UDHAR SITA 300` → create udhar via SMS
5. Show USSD tree on right side

---

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────┐
│                   FRONTEND (Browser)                 │
│  Voice Input (Web Speech API) + Text Fallback        │
│  4 Scenes: Listing | Discovery | Udhar | SMS         │
└────────────────────┬────────────────────────────────┘
                     │ REST API (FastAPI)
┌────────────────────▼────────────────────────────────┐
│                 BACKEND (FastAPI)                    │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │ Listing     │  │ Discovery    │                   │
│  │ Agent       │  │ Agent        │                   │
│  │ LLM + Regex │  │ LLM + Filter │                   │
│  └─────────────┘  └──────────────┘                  │
│                                                      │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │ Udhar       │  │ Fallback     │                   │
│  │ Agent       │  │ Agent        │                   │
│  │ Audit Trail │  │ SMS / USSD   │                   │
│  └─────────────┘  └──────────────┘                  │
│                                                      │
│  Data: vendors.json | inventory.json | udhar_ledger  │
└──────────────────────────────────────────────────────┘
```

## ✨ Key Technical Highlights

| Feature | Implementation |
|---------|---------------|
| Voice Input | Web Speech API, multi-language (en-IN) |
| LLM Integration | Google Gemini Flash via REST API |
| Fallback | Regex parser runs if API fails/unavailable |
| Audit Trail | Immutable append-only JSON log per transaction |
| Offline Mode | SMS command parser + USSD tree simulation |
| Compliance | Every udhar action timestamped and logged |
| No Hardcoded Keys | All secrets via `.env` variables |

## 📊 Business Impact

- **Time saved**: Vendor listing: 5 min → 30 sec voice input
- **Dispute reduction**: Immutable udhar audit trail eliminates "he said / she said"
- **Reach**: SMS fallback works on ₹500 feature phones, no smartphone needed
- **Discovery**: Buyers find best price/freshness in seconds vs. visiting multiple vendors