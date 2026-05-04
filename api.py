"""
HTTP API for Amazon PL Hunter — consumed by the n8n WhatsApp flow.

Start:  uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  GET    /user/{phone}            Look up a WhatsApp user (exists, name, state)
  POST   /user                    Save/update a user's name (clears state)
  PATCH  /user/{phone}/state      Set user state (e.g. "awaiting_name")
  POST   /asin                    Analyse a single ASIN
  POST   /hunt                    Keyword product hunt (returns top N winners)
  DELETE /cache/asin/{asin}       Clear cached data for one ASIN
  DELETE /cache/hunt/{keyword}    Clear all products scraped under a keyword
  GET    /health
  GET    /help
"""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from storage.database import (
    init_db, save_product, save_analysis,
    get_cached_product, get_cached_analysis,
    clear_asin_cache, clear_keyword_cache,
    get_user, upsert_user, set_user_state,
)
from scrapers.amazon_scraper import (
    scrape_product_page, scrape_reviews, scrape_search, get_keyword_suggestions,
)
from analysis.filter import filter_products
from analysis.profitability import calculate_profitability
from analysis.ai_analysis import run_full_analysis

app = FastAPI(title="Amazon PL Hunter API", version="1.0")


# ── Request models ─────────────────────────────────────────────────────────────

class AsinRequest(BaseModel):
    asin: str
    refresh: bool = False


class UserSaveRequest(BaseModel):
    phone: str
    name: str


class UserStateRequest(BaseModel):
    state: str | None = None


class HuntRequest(BaseModel):
    keyword: str
    top_n: int = 3
    refresh: bool = False


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()


# ── Utility endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/help")
def help_info():
    return {
        "formatted_message": (
            "*⚡ Quick commands:*\n\n"
            "•⁠ ⁠`asin B0XXXXXXXXX` — analyse a product\n"
            "•⁠ `⁠hunt bamboo organizer` — find top 3 winning products for idea\n"
            "•⁠ ⁠`refresh asin B0XXXXXXXXX` — force re-scrape of specific product\n"
            "•⁠ ⁠`refresh hunt bamboo organizer` — force re-scrape of specific idea\n\n"
            "Or just ask me anything about Amazon Private Label!"
        )
    }


# ── User management ───────────────────────────────────────────────────────────

@app.get("/user/{phone}")
def get_user_endpoint(phone: str):
    user = get_user(phone)
    if not user:
        return {"exists": False, "phone": phone, "name": None, "state": None}
    return {"exists": True, **user}


@app.post("/user")
def save_user_endpoint(req: UserSaveRequest):
    upsert_user(req.phone, req.name.strip())
    return {"ok": True, "phone": req.phone, "name": req.name.strip()}


@app.patch("/user/{phone}/state")
def update_user_state(phone: str, req: UserStateRequest):
    set_user_state(phone, req.state)
    return {"ok": True, "phone": phone, "state": req.state}


# ── ASIN analysis ──────────────────────────────────────────────────────────────

@app.post("/asin")
def analyze_asin(req: AsinRequest):
    asin = req.asin.strip().upper()

    if not req.refresh:
        cached_p = get_cached_product(asin)
        cached_a = get_cached_analysis(asin)
        if cached_p and cached_a:
            return _format_asin_response(cached_p, cached_a, cached=True)

    product = scrape_product_page(asin)
    if not product or not product.get("title"):
        raise HTTPException(404, f"Could not fetch product data for ASIN {asin}")

    product["asin"] = asin
    profit = calculate_profitability(product)
    reviews = scrape_reviews(asin, max_pages=2)
    result = run_full_analysis(product, reviews, profit)

    save_product({**product, "passed_filter": True})
    save_analysis(asin, result)

    return _format_asin_response(product, result, cached=False)


# ── Keyword hunt ───────────────────────────────────────────────────────────────

@app.post("/hunt")
def hunt_keyword(req: HuntRequest):
    keyword = req.keyword.strip()

    # Collect unique products from keyword + autocomplete variants
    suggestions = get_keyword_suggestions(keyword)
    expanded = [keyword] + suggestions[:2]

    seen: set = set()
    raw_products = []
    for kw in expanded:
        for p in scrape_search(kw, max_products=20):
            asin = p.get("asin")
            if asin and asin not in seen:
                seen.add(asin)
                raw_products.append(p)

    if not raw_products:
        raise HTTPException(404, f"No products found for keyword: {keyword}")

    # Enrich (cache-aware)
    enriched = []
    for p in raw_products:
        asin = p.get("asin")
        if not req.refresh:
            cached = get_cached_product(asin)
            if cached:
                enriched.append({**p, **cached})
                continue
        page_data = scrape_product_page(asin)
        enriched.append({**p, **{k: v for k, v in page_data.items() if v is not None}})

    # Filter
    passed, _ = filter_products(enriched)

    for p in enriched:
        save_product(p)

    if not passed:
        return {
            "keyword": keyword,
            "winners": [],
            "total_found": len(enriched),
            "formatted_message": (
                f"Searched *{keyword}*: found {len(enriched)} products but none passed "
                "quality filters (price $20-$60, BSR < 50k, reviews < 500, est revenue > $8k/mo). "
                "Try a broader keyword."
            ),
        }

    # Analyse passed products; stop once we have enough winners
    winners = []
    for product in passed:
        if len(winners) >= req.top_n:
            break
        asin = product.get("asin")

        if not req.refresh:
            cached_a = get_cached_analysis(asin)
            if cached_a:
                if cached_a.get("score", 0) >= 7.0:
                    winners.append({**product, **cached_a})
                continue

        profit = calculate_profitability(product)
        if not profit["viable"]:
            continue

        reviews = scrape_reviews(asin, max_pages=2)
        result = run_full_analysis(product, reviews, profit)
        save_analysis(asin, result)

        if result.get("score", 0) >= 7.0:
            winners.append({**product, **result})

    winners = sorted(winners, key=lambda x: x.get("score", 0), reverse=True)[: req.top_n]

    return _format_hunt_response(keyword, winners, len(enriched))


# ── Cache management ───────────────────────────────────────────────────────────

@app.delete("/cache/asin/{asin}")
def clear_asin(asin: str):
    clear_asin_cache(asin.upper())
    return {"message": f"Cache cleared for ASIN {asin.upper()}."}


@app.delete("/cache/hunt/{keyword}")
def clear_hunt(keyword: str):
    asins = clear_keyword_cache(keyword)
    return {"message": f"Cache cleared for '{keyword}' — {len(asins)} product(s)."}


# ── Response formatters ────────────────────────────────────────────────────────

def _parse_json_field(value, default):
    if isinstance(value, list):
        return value
    try:
        return json.loads(value or "[]")
    except Exception:
        return default


def _format_asin_response(product: dict, analysis: dict, cached: bool) -> dict:
    brief_raw = analysis.get("product_brief", "")
    brief = {}
    if brief_raw:
        try:
            brief = json.loads(brief_raw) if isinstance(brief_raw, str) else brief_raw
        except Exception:
            pass

    pain_points = _parse_json_field(analysis.get("pain_points"), [])
    score = analysis.get("score", 0)
    go_no_go = analysis.get("go_no_go", "N/A")
    verdict = analysis.get("verdict", "")
    margin_pct = analysis.get("margin_pct") or 0
    net_profit = analysis.get("net_profit") or 0
    bsr = product.get("bsr")

    lines = [
        "📦 *Product Analysis*" + (" _(cached)_" if cached else ""),
        "",
        f"*{(product.get('title') or 'N/A')[:65]}*",
        f"ASIN: *{product.get('asin')}*",
        f"💰 ${product.get('price')}  ⭐ {product.get('rating')} ({product.get('review_count', 0):,} reviews)",
        f"📊 BSR: {bsr:,}" if bsr else "📊 BSR: N/A",
        f"💵 Est. Revenue: ${product.get('monthly_revenue', 0):,.0f}/mo",
        "",
        f"🎯 *Score: {score}/10 — {go_no_go}*",
        f"📈 Margin: {margin_pct:.1f}%  |  Net profit: ${net_profit:.2f}/unit",
        f"💬 {verdict}",
    ]

    if pain_points:
        lines += ["", "⚠️ *Top Pain Points:*"] + [f"  • {p}" for p in pain_points[:3]]

    if brief.get("usp"):
        lines += ["", f"🚀 *USP:* {brief['usp']}"]

    if brief.get("target_keywords"):
        lines.append(f"🔑 Keywords: {', '.join(brief['target_keywords'][:4])}")

    if brief.get("suggested_price"):
        lines.append(f"💲 Suggested price: ${brief['suggested_price']}")

    lines += ["", f"🔗 https://www.amazon.com/dp/{product.get('asin')}"]

    return {
        "asin": product.get("asin"),
        "title": product.get("title"),
        "price": product.get("price"),
        "score": score,
        "go_no_go": go_no_go,
        "verdict": verdict,
        "margin_pct": margin_pct,
        "net_profit": net_profit,
        "monthly_revenue": product.get("monthly_revenue"),
        "pain_points": pain_points,
        "product_brief": brief,
        "cached": cached,
        "formatted_message": "\n".join(lines),
    }


def _format_hunt_response(keyword: str, winners: list, total_found: int) -> dict:
    if not winners:
        return {
            "keyword": keyword,
            "winners": [],
            "total_found": total_found,
            "formatted_message": (
                f"No winning products found for *{keyword}*. "
                "All candidates passed filters but scored below 7.0. "
                "Try a different keyword."
            ),
        }

    lines = [
        f"🏆 *Top {len(winners)} Winners for '{keyword}'*",
        f"_(screened from {total_found} products)_",
        "",
    ]

    for i, w in enumerate(winners, 1):
        brief = {}
        brief_raw = w.get("product_brief", "")
        if brief_raw:
            try:
                brief = json.loads(brief_raw) if isinstance(brief_raw, str) else brief_raw
            except Exception:
                pass

        bsr = w.get("bsr")
        lines += [
            f"*#{i} — Score: {w.get('score')}/10 — {w.get('go_no_go')}*",
            f"{w.get('asin')} — {(w.get('title') or 'N/A')[:55]}",
            f"💰 ${w.get('price')}  ⭐ {w.get('rating')}  📊 BSR {bsr:,}" if bsr else f"💰 ${w.get('price')}",
            f"💵 ${w.get('monthly_revenue', 0):,.0f}/mo  |  Margin {w.get('margin_pct', 0):.1f}%",
            f"💬 {w.get('verdict', '')}",
        ]
        if brief.get("usp"):
            lines.append(f"🚀 {brief['usp']}")
        lines += [f"🔗 https://www.amazon.com/dp/{w.get('asin')}", ""]

    return {
        "keyword": keyword,
        "total_found": total_found,
        "winners": [
            {
                "asin": w.get("asin"),
                "title": w.get("title"),
                "score": w.get("score"),
                "go_no_go": w.get("go_no_go"),
                "verdict": w.get("verdict"),
                "margin_pct": w.get("margin_pct"),
                "monthly_revenue": w.get("monthly_revenue"),
            }
            for w in winners
        ],
        "formatted_message": "\n".join(lines),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
