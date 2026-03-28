# 🌾 Krishi Saarthi — कृषि सारथी

**Voice-First Multi-Agent AI System for Rural Agricultural Commerce**

> Hackathon Project | Problem Statement #5 – Domain-Specialized AI Agents with Compliance Guardrails

---

## 📁 Project Structure

Top-level layout (important files only):

```bash
krishi-sarthi/
├─ main.py                 # FastAPI backend entrypoint (Krishi Saarthi API)
├─ requirements.txt        # Python backend dependencies
├─ agents/                 # Domain "agents" used by the conversation engine
│  ├─ conversation_agent.py   # Central voice-first assistant logic
│  ├─ listing_agent.py        # Vendor product extraction (Ollama + regex)
│  ├─ discovery_agent.py      # Consumer search & ranking (Ollama + rules)
│  ├─ udhar_agent.py          # Udhar (credit) ledger + audit trail
│  ├─ fallback_agent.py       # SMS / USSD style fallback
│  ├─ speech_utils.py         # STT (Whisper) + TTS (gTTS Hindi) helpers
│  └─ utils.py                # JSON I/O, helpers, distance, freshness labels
├─ data/                   # JSON "database" (created/updated at runtime)
│  ├─ vendors.json
│  ├─ consumers.json
│  ├─ inventory.json
│  ├─ orders.json
│  ├─ udhar_ledger.json
│  └─ pending_udhar.json
├─ frontend/               # Vite-based web app (npm run dev)
│  ├─ index.html           # Landing + assistant layout
│  ├─ style.css            # Green, mobile-style theme
│  ├─ script.js            # Mic handling, API calls, UI updates
│  ├─ package.json         # Frontend scripts & devDeps (Vite)
│  ├─ vite.config.mjs      # Dev server + /api proxy → FastAPI
│  └─ src/
│     └─ main.js           # Vite entry importing style.css + script.js
└─ .env / .env.example     # Backend configuration (Ollama, etc.)
```

---

## 🚀 How to Run (Backend + Frontend)

### 1. Clone & enter project

```bash
git clone <repo-url>
cd krishi-sarthi
```

### 2. Backend setup (FastAPI)

```bash
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # macOS / Linux

pip install -r requirements.txt

# Environment (Ollama, etc.)
copy .env.example .env    # Windows
# cp .env.example .env      # macOS / Linux
# Then edit .env to point OLLAMA_HOST / OLLAMA_MODEL if needed
```

### 3. Start backend API

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API base: http://localhost:8000  
- Docs: http://localhost:8000/docs

### 4. Frontend setup (Vite web app)

In a **new terminal**, from the `frontend/` folder:

```bash
cd frontend
npm install
npm run dev
```

- Vite dev server: usually http://localhost:5173/  
- Proxy is configured so all `/api/*` requests go to `http://localhost:8000`.

### 5. Use the app

1. Open `http://localhost:5173/` in a modern browser (Chrome/Edge).  
2. On the landing screen, choose **Vendor (विक्रेता)** or **Consumer (ग्राहक)**.  
3. On the assistant screen, press the big mic button and speak in Hindi.  
4. The app sends audio to `/api/voice-audio`, and shows:
    - Your recognized text (`user_text`) under **"आपकी बात"**, and  
    - Krishi Saarthi’s reply (`reply_text`) under **"सारथी का जवाब"**, plus spoken audio.

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

## 🏗️ High-Level Architecture

```
Browser (Vite Web App)
 ├─ Landing screen: choose Vendor / Consumer
 └─ Voice assistant screen: mic, bubbles, Hindi text
    │
    │  /api/voice-audio  (audio + state)
    ▼
FastAPI Backend (main.py)
 ├─ /api/voice           → text in / text out
 ├─ /api/voice-audio     → audio in / text + audio out
 └─ Conversation engine  → agents.conversation_agent.handle_conversation
    │
    ├─ ListingAgent      (agents/listing_agent.py)
    ├─ DiscoveryAgent    (agents/discovery_agent.py)
    ├─ UdharAgent        (agents/udhar_agent.py)
    └─ FallbackAgent     (agents/fallback_agent.py)
    │
    └─ JSON data in /data (vendors, consumers, inventory, orders, udhar_ledger, pending_udhar)
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