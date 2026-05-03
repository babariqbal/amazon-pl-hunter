# ============================================================
#  Amazon PL Hunter — Configuration
# ============================================================

# --- Product Criteria (edit these to match your strategy) ---
CRITERIA = {
    "min_price": 20,
    "max_price": 60,
    "max_reviews": 500,
    "min_monthly_revenue": 8000,   # estimated
    "max_weight_lbs": 2.0,
    "min_rating": 3.5,             # sweet spot: demand exists but room to improve
    "min_bsr": 1,
    "max_bsr": 50000,
}

# --- FBA Fee Estimation (US marketplace) ---
FBA = {
    "referral_fee_pct": 0.15,       # 15% for most categories
    "small_standard_fee": 3.22,     # under 1lb
    "large_standard_fee": 5.40,     # 1–2lb
    "storage_fee_per_unit": 0.50,   # estimated monthly
    "misc_fee": 1.00,               # inbound shipping, prep, etc.
}

# --- Profitability Targets ---
PROFIT = {
    "target_margin_pct": 30,        # minimum net margin %
    "cogs_ratio": 0.25,             # assume COGS = 25% of sale price (Alibaba sourcing)
    "ppc_per_unit": 4.00,           # estimated ad spend per unit sold
}

# --- Anthropic API ---
ANTHROPIC = {
    "haiku_model": "claude-haiku-4-5-20251001",   # cheap, fast — bulk analysis
    "sonnet_model": "claude-sonnet-4-6",           # smarter — final product briefs
    "max_tokens": 1500,
}

# --- Scraping ---
SCRAPING = {
    "delay_min": 3,
    "delay_max": 8,
    "max_retries": 3,
    "headless": True,
    "timeout_ms": 30000,
}

# --- Amazon Marketplace ---
AMAZON = {
    "base_url": "https://www.amazon.com",
    "search_url": "https://www.amazon.com/s?k={query}&ref=nb_sb_noss",
}

# --- Categories to Hunt (Amazon department names) ---
TARGET_CATEGORIES = [
    "Kitchen & Dining",
    "Sports & Outdoors",
    "Home & Garden",
    "Office Products",
    "Pet Supplies",
    "Baby",
    "Health & Household",
]

# --- Keywords to Search ---
SEED_KEYWORDS = [
    "bamboo organizer",
    "desk cable organizer",
    "silicone kitchen tool set",
    "workout resistance bands set",
    "reusable water bottle",
    "wooden phone stand",
    "minimalist wallet",
    "travel toiletry bag",
    "yoga mat strap",
    "laptop stand adjustable",
]

# --- Telegram Alerts (optional — leave empty to disable) ---
TELEGRAM = {
    "bot_token": "",   # get from @BotFather
    "chat_id": "",     # your chat ID
}

# --- Storage ---
DATABASE_PATH = "data/products.db"
RESULTS_DIR = "data/results"
