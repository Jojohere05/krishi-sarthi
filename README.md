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

---

## 🧭 Product Workflow

This is how a typical session flows end‑to‑end.

### 1. Choose role (landing screen)

1. User opens the web app at `http://localhost:5173/`.
2. First screen asks: **Continue as Vendor (विक्रेता)** or **Continue as Consumer (ग्राहक)**.
3. Based on the button they click, the frontend sets the role and opens the voice assistant screen.

### 2. Talk to the assistant (voice + Hindi text)

1. User presses the big mic button and speaks in Hindi.
2. Frontend records audio → sends it to `POST /api/voice-audio` along with:
     - `user_id` (demo: 1), `role` (vendor/consumer), and
     - `state` (previous `next_state` from backend).
3. Backend (main.py):
     - Uses `speech_utils.transcribe_audio_to_text` to convert audio → Hindi text (`user_text`).
     - Passes `user_text` + `state` into `handle_conversation` in `agents/conversation_agent.py`.
     - That function detects intent, runs the correct flow (vendor or consumer), reads/writes JSON in `/data`, and returns `reply_text`, `action`, `data`, and updated `next_state`.
     - Backend optionally generates Hindi speech audio from `reply_text` and returns `audio_base64`.
4. Frontend shows both:
     - **"आपकी बात"** = `user_text` (what STT heard), and
     - **"सारथी का जवाब"** = `reply_text` (assistant’s Hindi answer), and plays the audio.
5. Frontend stores `next_state` and sends it back on the next turn, so multi‑step flows continue naturally.

### 3. Vendor flows (examples)

- **Register shop** → `_vendor_register_shop` in `agents/conversation_agent.py`
    - Asks for shop name, then what items are sold; writes a new vendor into `data/vendors.json`.
- **Add product** → `_vendor_add_product`
    - Asks for product details by voice.
    - Uses `agents/listing_agent.extract_product` (Ollama + regex) to understand quantity, unit, price, freshness.
    - Confirms the details in Hindi, then writes a new item into `data/inventory.json`.
- **View orders** → `_vendor_view_orders`
    - Reads recent entries from `data/orders.json`.
    - Speaks and shows which consumer, address, quantity and product were ordered.
- **Udhar (credit)** → `_vendor_view_udhar`, `_vendor_mark_paid`, `_vendor_create_udhar`
    - Uses `agents/udhar_agent.py` and `data/udhar_ledger.json` / `data/pending_udhar.json` for creating and managing credit with full audit trail.

### 4. Consumer flows (examples)

- **Register user** → `_consumer_register`
    - Collects name and address; writes to `data/consumers.json`.
- **Search + compare vendors** → `_consumer_search_and_prepare_order`
    - Uses `agents/discovery_agent.search_products` to find matching inventory.
    - Compares multiple vendors (price, freshness, distance) and lets the user pick one by voice.
- **Place order** → `_consumer_choose_vendor_and_ask_qty` + `_consumer_place_order`
    - Asks for quantity, then writes an order into `data/orders.json` linking consumer and vendor.
- **View / pay udhar** → `_consumer_view_udhar`, `_consumer_pay_udhar`
    - Reads udhar info from `data/udhar_ledger.json` and pending requests from `data/pending_udhar.json`.
    - Guides the user through confirming or paying udhar using simple Hindi prompts.

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