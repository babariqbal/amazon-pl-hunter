"""
Amazon search results scraper.
Uses requests + BeautifulSoup with rotating user agents.
For heavier scraping, swap in Playwright (see comments).
"""

import json
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

from config import AMAZON, SCRAPING

# ---------------------------------------------------------------------------
# User Agent Pool — rotate to avoid detection
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Optional: pass proxy dict like {"http": "http://user:pass@host:port"}
# Get rotating proxies from webshare.io (~$10/mo)
# ---------------------------------------------------------------------------
PROXY = None  # e.g. {"http": "http://...", "https": "http://..."}


def _headers() -> Dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        # Force USD pricing regardless of IP geolocation
        "Cookie": "i18n-prefs=USD; lc-acbus=en_US; sp-cdn=L5Z9:PK",
    }


def _sleep():
    delay = random.uniform(SCRAPING["delay_min"], SCRAPING["delay_max"])
    time.sleep(delay)


def _get(url: str) -> Optional[BeautifulSoup]:
    for attempt in range(SCRAPING["max_retries"]):
        try:
            resp = requests.get(
                url,
                headers=_headers(),
                proxies=PROXY,
                timeout=20,
            )
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            elif resp.status_code == 503:
                print(f"  [Scraper] 503 received, waiting 30s... (attempt {attempt+1})")
                time.sleep(30)
            else:
                print(f"  [Scraper] HTTP {resp.status_code} for {url}")
        except Exception as e:
            print(f"  [Scraper] Error: {e} (attempt {attempt+1})")
            time.sleep(10)
    return None


# ---------------------------------------------------------------------------
# Detect bot/CAPTCHA block
# ---------------------------------------------------------------------------
def _is_blocked(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    return (
        "enter the characters you see below" in text
        or "type the characters you see in this image" in text
        or "sorry, we just need to make sure you're not a robot" in text
        or soup.select_one("form[action='/errors/validateCaptcha']") is not None
    )


# ---------------------------------------------------------------------------
# Parse price from product page — multiple fallback selectors
# ---------------------------------------------------------------------------
def _parse_price(soup: BeautifulSoup) -> Optional[float]:
    # Strategy 1: JSON price blob embedded in page — most reliable source
    try:
        blob = soup.select_one(".twister-plus-buying-options-price-data")
        if blob:
            data = json.loads(blob.get_text(strip=True))
            for group in data.values():
                if isinstance(group, list) and group:
                    entry = group[0]
                    if entry.get("currencySymbol") == "$":
                        amt = entry.get("priceAmount")
                        if amt and float(amt) > 0:
                            return float(amt)
    except Exception:
        pass

    # Strategy 2: CSS selectors with non-USD currency guard
    selectors = [
        # Current layout (2024–2025)
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#apex_desktop .a-price .a-offscreen",
        ".apexPriceToPay .a-offscreen",
        # Generic fallback
        ".a-price .a-offscreen",
        # Legacy selectors
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        "#price_inside_buybox",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            # Skip empty spans and non-USD currencies (PKR, EUR, GBP, etc.)
            if not text or re.search(r'[A-Z]{2,}', text.replace("USD", "")):
                continue
            try:
                raw = re.sub(r'[^\d.]', '', text.replace(",", ""))
                val = float(raw)
                if val > 0:
                    return val
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Parse BSR from product page — multiple fallback selectors
# ---------------------------------------------------------------------------
def _parse_bsr(soup: BeautifulSoup) -> Optional[int]:
    # Strategy 1: new key-value layout (.po-best_sellers_rank)
    try:
        rank_el = soup.select_one(".po-best_sellers_rank .po-break-word")
        if rank_el:
            match = re.search(r"#([\d,]+)", rank_el.get_text())
            if match:
                return int(match.group(1).replace(",", ""))
    except Exception:
        pass

    # Strategy 2: detail bullets and product details tables
    selectors = (
        "#detailBulletsWrapper_feature_div li",
        "#productDetails_db_sections td",
        "#productDetails_db_sections th",
        "#productDetails_detailBullets_sections td",
        "#productDetails_detailBullets_sections th",
        "#prodDetails td",
        "#prodDetails th",
        ".a-section.a-spacing-small li",
    )
    try:
        for el in soup.select(", ".join(selectors)):
            text = el.get_text(" ", strip=True)
            if "Best Seller" in text or "Best Sellers Rank" in text:
                match = re.search(r"#([\d,]+)", text)
                if match:
                    return int(match.group(1).replace(",", ""))
    except Exception:
        pass

    # Strategy 3: scan all spans/tds for "#N in" pattern near "Best Seller"
    try:
        page_text = soup.get_text(" ")
        idx = page_text.find("Best Sellers Rank")
        if idx == -1:
            idx = page_text.find("Best Seller Rank")
        if idx != -1:
            snippet = page_text[idx:idx + 200]
            match = re.search(r"#([\d,]+)", snippet)
            if match:
                return int(match.group(1).replace(",", ""))
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Parse weight from product page
# ---------------------------------------------------------------------------
def _parse_weight(soup: BeautifulSoup) -> Optional[float]:
    try:
        for row in soup.select("tr.a-spacing-small"):
            th = row.find("th")
            td = row.find("td")
            if th and td and "weight" in th.get_text(strip=True).lower():
                text = td.get_text(strip=True)
                # Try to extract lbs
                match = re.search(r"([\d.]+)\s*pound", text, re.I)
                if match:
                    return float(match.group(1))
                # Try oz → lbs
                match = re.search(r"([\d.]+)\s*ounce", text, re.I)
                if match:
                    return float(match.group(1)) / 16
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Scrape individual ASIN product page
# ---------------------------------------------------------------------------
def scrape_product_page(asin: str) -> Dict:
    url = f"{AMAZON['base_url']}/dp/{asin}"
    soup = _get(url)
    if not soup:
        return {}

    if _is_blocked(soup):
        print(f"  [Scraper] ⚠️  Bot/CAPTCHA block detected for {asin} — skipping")
        return {}

    result = {"asin": asin, "url": url}

    # Title
    title_el = soup.select_one("#productTitle")
    result["title"] = title_el.get_text(strip=True) if title_el else None

    # Price — multi-selector with fallbacks
    price = _parse_price(soup)
    if price:
        result["price"] = price

    # Rating
    rating_el = soup.select_one("span[data-hook='rating-out-of-text'], #acrPopover")
    if rating_el:
        match = re.search(r"([\d.]+) out of", rating_el.get_text())
        if match:
            result["rating"] = float(match.group(1))

    # Review count
    review_el = soup.select_one("#acrCustomerReviewText")
    if review_el:
        match = re.search(r"([\d,]+)", review_el.get_text())
        if match:
            result["review_count"] = int(match.group(1).replace(",", ""))

    # Category
    cat_el = soup.select("#wayfinding-breadcrumbs_feature_div a")
    if cat_el:
        result["category"] = cat_el[0].get_text(strip=True)

    # BSR — multi-strategy with fallbacks
    result["bsr"] = _parse_bsr(soup)

    # Weight
    result["weight_lbs"] = _parse_weight(soup)

    if not result.get("price"):
        print(f"  [Scraper] ⚠️  Price still None for {asin} after all selectors")
    if not result.get("bsr"):
        print(f"  [Scraper] ⚠️  BSR still None for {asin} after all selectors")

    _sleep()
    return result


# ---------------------------------------------------------------------------
# Scrape search results page for a keyword
# Returns list of ASINs + basic info
# ---------------------------------------------------------------------------
def scrape_search(keyword: str, max_products: int = 20) -> List[Dict]:
    print(f"  [Scraper] Searching: '{keyword}'")
    url = AMAZON["search_url"].format(query=keyword.replace(" ", "+"))
    soup = _get(url)
    if not soup:
        print(f"  [Scraper] Failed to fetch search results for '{keyword}'")
        return []

    if _is_blocked(soup):
        print(f"  [Scraper] ⚠️  Bot/CAPTCHA block on search for '{keyword}'")
        return []

    products = []
    cards = soup.select('[data-component-type="s-search-result"]')

    for card in cards[:max_products]:
        try:
            asin = card.get("data-asin", "")
            if not asin:
                continue

            # Title
            title_el = card.select_one("h2 span")
            title = title_el.get_text(strip=True) if title_el else ""

            # Price — try multiple selectors on the search card
            price = None
            for price_sel in (".a-price .a-offscreen", ".a-color-price", ".a-price-whole"):
                price_el = card.select_one(price_sel)
                if price_el:
                    try:
                        raw = price_el.get_text(strip=True).replace("$", "").replace(",", "").strip()
                        val = float(raw)
                        if val > 0:
                            price = val
                            break
                    except Exception:
                        continue

            # Rating
            rating = None
            rating_el = card.select_one("span.a-icon-alt")
            if rating_el:
                match = re.search(r"([\d.]+) out of", rating_el.get_text())
                if match:
                    rating = float(match.group(1))

            # Review count
            review_count = None
            review_el = card.select_one("span.a-size-base.s-underline-text")
            if review_el:
                try:
                    review_count = int(review_el.get_text(strip=True).replace(",", ""))
                except Exception:
                    pass

            products.append({
                "asin": asin,
                "keyword": keyword,
                "title": title,
                "price": price,
                "rating": rating,
                "review_count": review_count,
            })

        except Exception as e:
            print(f"  [Scraper] Parse error on card: {e}")
            continue

    print(f"  [Scraper] Found {len(products)} products for '{keyword}'")
    _sleep()
    return products


# ---------------------------------------------------------------------------
# Scrape reviews for an ASIN
# ---------------------------------------------------------------------------
def scrape_reviews(asin: str, max_pages: int = 3) -> List[str]:
    reviews = []
    for page in range(1, max_pages + 1):
        url = (
            f"{AMAZON['base_url']}/product-reviews/{asin}"
            f"?reviewerType=all_reviews&pageNumber={page}&sortBy=recent"
        )
        soup = _get(url)
        if not soup:
            break

        for el in soup.select("[data-hook='review-body'] span"):
            text = el.get_text(strip=True)
            if len(text) > 30:
                reviews.append(text)

        _sleep()

    print(f"  [Scraper] Got {len(reviews)} reviews for {asin}")
    return reviews


# ---------------------------------------------------------------------------
# Free keyword suggestions from Amazon autocomplete
# ---------------------------------------------------------------------------
def get_keyword_suggestions(seed: str) -> List[str]:
    url = (
        "https://completion.amazon.com/api/2017/suggestions"
        f"?mid=ATVPDKIKX0DER&alias=aps&prefix={seed.replace(' ', '+')}"
    )
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        data = resp.json()
        suggestions = [s["value"] for s in data.get("suggestions", [])]
        return suggestions
    except Exception as e:
        print(f"  [Keywords] Error fetching suggestions for '{seed}': {e}")
        return []
