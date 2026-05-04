# 🎯 Amazon PL Product Hunter

Automated Amazon private label product hunting using Python + Claude AI.
**Estimated cost: ~$20–40/month**

---

## 📁 Project Structure

```
amazon-pl-hunter/
├── config.py                    ← SETTINGS (edit this first)
├── main.py                      ← CLI runner
├── api.py                       ← FastAPI server (for n8n / WhatsApp bot)
├── requirements.txt
├── scrapers/
│   └── amazon_scraper.py        ← Amazon scraping logic
├── analysis/
│   ├── filter.py                ← Criteria filter
│   ├── profitability.py         ← FBA fee calculator
│   └── ai_analysis.py          ← Claude AI review mining + scoring
├── storage/
│   └── database.py              ← SQLite database + 48h cache
├── alerts/
│   └── telegram_bot.py          ← Telegram alerts
└── data/
    ├── products.db              ← Auto-created SQLite DB
    └── results/                 ← JSON winner reports saved here
```

---

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium    # optional, for JS-heavy pages
```

### 2. Set your Anthropic API key
Create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Edit config.py
Open `config.py` and adjust:
- **CRITERIA** — your product filters (price, reviews, BSR, etc.)
- **SEED_KEYWORDS** — what niches to hunt
- **PROFIT.target_margin_pct** — your minimum acceptable margin
- **TELEGRAM** — add bot token + chat ID for alerts (optional)

### 4. (Optional) Add proxies
In `scrapers/amazon_scraper.py`, set:
```python
PROXY = {"http": "http://user:pass@host:port", "https": "http://user:pass@host:port"}
```
Recommended: [webshare.io](https://webshare.io) rotating residential proxies (~$10/mo).

---

## 🚀 CLI Usage

### Run a full hunt (uses SEED_KEYWORDS from config.py)
```bash
python main.py
```

### Hunt specific keywords
```bash
python main.py --keywords "bamboo desk organizer" "silicone kitchen tools"
```

### Hunt from a keywords file (one per line)
```bash
python main.py --keyword-file my_keywords.txt
```

### Analyze a specific ASIN
```bash
python main.py --asin B08XYZABC1
```

### Print all winners from database
```bash
python main.py --report
```

### Bypass 48-hour cache (force re-scrape)
```bash
python main.py --asin B08XYZABC1 --refresh
python main.py --keywords "yoga mat" --refresh
```

---

## 💡 How It Works

```
1. COLLECT  → Scrape Amazon search results for your keywords
              + Amazon autocomplete suggests related keywords (free)

2. ENRICH   → Fetch full product pages to get BSR, weight, category
              ↳ Skipped if product was scraped within 48 hours (cache)

3. FILTER   → Apply your criteria (price, reviews, BSR, margin)
              Products that fail are saved to DB but skipped

4. ANALYZE  → For products that pass:
              a) Skipped if analysis exists within 48 hours (cache)
              b) Scrape customer reviews
              c) Claude Haiku mines reviews for pain points
              d) Claude Haiku scores the opportunity 1–10
              e) Claude Sonnet writes a full product brief (if score ≥ 6)

5. ALERT    → Winners (score ≥ 7) trigger a Telegram notification
              Full JSON report saved to data/results/
```

---

## ⚡ 48-Hour Cache

Products and analyses are cached in SQLite for 48 hours. If the same ASIN is requested again within that window, no scraping or AI calls are made — the stored result is returned instantly.

| Cache type | TTL | Bypassed by |
|---|---|---|
| Product page data | 48h | `--refresh` flag |
| AI analysis | 48h | `--refresh` flag |

---

## 🌐 HTTP API (for n8n / WhatsApp bot)

Start the API server:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/help` | Returns formatted command list |
| `GET` | `/user/{phone}` | Look up a WhatsApp user |
| `POST` | `/user` | Save / update a user's name |
| `PATCH` | `/user/{phone}/state` | Set user state (e.g. `awaiting_name`) |
| `POST` | `/asin` | Analyse a single ASIN |
| `POST` | `/hunt` | Keyword hunt — returns top N winners |
| `DELETE` | `/cache/asin/{asin}` | Clear cached data for one ASIN |
| `DELETE` | `/cache/hunt/{keyword}` | Clear all products under a keyword |

### Example requests

**Analyse ASIN:**
```json
POST /asin
{ "asin": "B0DS64V37F", "refresh": false }
```

**Keyword hunt:**
```json
POST /hunt
{ "keyword": "bamboo desk organizer", "top_n": 3, "refresh": false }
```

Every response includes a `formatted_message` field — ready to send directly to WhatsApp.

---

## 📱 WhatsApp Bot (n8n Flow)

The bot is powered by n8n and talks to the API above.

### Prerequisites
- n8n instance running
- API server accessible from n8n (same server or exposed via reverse proxy / ngrok)
- WhatsApp Business Cloud (Meta) or Twilio WhatsApp account

### Bot Commands
| Command | Description |
|---|---|
| `asin B0XXXXXXXXX` | Analyse a product by ASIN |
| `hunt bamboo organizer` | Find top 3 winning products for a keyword |
| `refresh asin B0XXXXXXXXX` | Force re-analyse, bypassing cache |
| `refresh hunt bamboo organizer` | Force re-scrape a keyword |
| `clear asin B0XXXXXXXXX` | Delete cached ASIN data |
| `clear hunt bamboo organizer` | Delete cached keyword data |
| `help` | Show command list |
| _(anything else)_ | Conversational AI — Amazon PL questions |

### n8n Flow Overview

```
[WhatsApp Trigger]
       ↓
[Extract Message]
       ↓
[GET /user/{phone}]
       ↓
[User Router]
   ├─ awaiting_name → [Save Name] → [Claude Welcome] → [Send] → STOP
   ├─ new_user      → [Set State] → [Ask Name]       → [Send] → STOP
   └─ known_user    → [Set user_name]
                            ↓
                    [Parse Command]
                            ↓
                    [Command Router]
                       ├─ asin       → [Waiting msg] → [Send] → [POST /asin]  ──→ [Merge]
                       │                                         error ──────────→ [Merge]
                       ├─ hunt       → [Waiting msg] → [Send] → [POST /hunt]  ──→ [Merge]
                       │                                         error ──────────→ [Merge]
                       ├─ clear_asin → [DELETE /cache/asin/...]               ──→ [Merge]
                       ├─ clear_hunt → [DELETE /cache/hunt/...]               ──→ [Merge]
                       ├─ help       → [GET /help]                            ──→ [Merge]
                       └─ chat       → [Claude AI]                            ──→ [Merge]
                                                                                      ↓
                                                                              [Send WhatsApp]
```

### New User Flow
When a user messages for the first time:
1. Bot asks for their name
2. User replies with their name — bot saves it and sends a personalised welcome
3. All future conversations use the user's name via the Claude system prompt

User data is stored in the `users` table in SQLite with a `state` field to track pending interactions.

---

## 💰 Cost Breakdown

| Item | Monthly Cost |
|---|---|
| VPS (Hetzner CX11) | $5 |
| Rotating proxies (webshare.io) | $10 |
| Claude API (Haiku bulk + Sonnet briefs) | $5–15 |
| **Total** | **~$20–30/month** |

### API cost per product analyzed:
- Review analysis (Haiku): ~$0.002
- Scoring (Haiku): ~$0.001
- Product brief (Sonnet): ~$0.015
- **Total per winner brief: ~$0.02** (2 cents!)

---

## 🤖 Telegram Setup (Free Alerts)

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions → get your **bot token**
3. Start a chat with your new bot
4. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find your **chat_id** in the response
6. Add both to `config.py` under `TELEGRAM`

---

## 📅 Automate with Cron (Run Daily)

```bash
# Run every day at 3am
crontab -e

# Add this line:
0 3 * * * cd /path/to/amazon-pl-hunter && python main.py >> logs/hunt.log 2>&1
```

---

## ⚠️ Important Notes

- **Respect robots.txt** — use reasonable delays (configured in config.py)
- Amazon may block IPs without proxies — start with low volume
- This is for research/validation purposes
- Review counts and BSR change daily — treat all data as estimates
- Always manually validate winners before ordering inventory
