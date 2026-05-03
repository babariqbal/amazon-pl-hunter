# 🎯 Amazon PL Product Hunter

Automated Amazon private label product hunting using Python + Claude AI.
**Estimated cost: ~$20–40/month** (vs $150+ for no-code tools).

---

## 📁 Project Structure

```
amazon-pl-hunter/
├── config.py                    ← YOUR SETTINGS (edit this first)
├── main.py                      ← Run this
├── requirements.txt
├── scrapers/
│   └── amazon_scraper.py        ← Amazon scraping logic
├── analysis/
│   ├── filter.py                ← Criteria filter
│   ├── profitability.py         ← FBA fee calculator
│   └── ai_analysis.py          ← Claude AI review mining + scoring
├── storage/
│   └── database.py              ← SQLite database
├── alerts/
│   └── telegram_bot.py          ← Free Telegram alerts
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
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
Or create a `.env` file and load with `python-dotenv`.

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

## 🚀 Usage

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

### Analyze a specific ASIN you found manually
```bash
python main.py --asin B08XYZABC1
```

### Print all winners from database
```bash
python main.py --report
```

---

## 💡 How It Works

```
1. COLLECT  → Scrape Amazon search results for your keywords
              + Amazon autocomplete suggests related keywords (free)

2. ENRICH   → Fetch full product pages to get BSR, weight, category

3. FILTER   → Apply your criteria (price, reviews, BSR, margin)
              Products that fail are saved to DB but skipped

4. ANALYZE  → For products that pass:
              a) Scrape customer reviews
              b) Claude Haiku mines reviews for pain points
              c) Claude Haiku scores the opportunity 1–10
              d) Claude Sonnet writes a full product brief (if score ≥ 6)

5. ALERT    → Winners (score ≥ 7) trigger a Telegram notification
              Full JSON report saved to data/results/
```

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
