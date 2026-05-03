"""
Amazon search results scraper.
Uses requests + BeautifulSoup with rotating user agents.
For heavier scraping, swap in Playwright (see comments).
"""

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
# Parse BSR from product page
# ---------------------------------------------------------------------------
def _parse_bsr(soup: BeautifulSoup) -> Optional[int]:
    try:
        for li in soup.select("#detailBulletsWrapper_feature_div li, #productDetails_db_sections td"):
            text = li.get_text(" ", strip=True)
            if "Best Seller" in text or "Best Sellers Rank" in text:
                match = re.search(r"#([\d,]+)", text)
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

    result = {"asin": asin, "url": url}

    # Title
    title_el = soup.select_one("#productTitle")
    result["title"] = title_el.get_text(strip=True) if title_el else None

    # Price
    price_el = soup.select_one(".a-price .a-offscreen")
    if price_el:
        try:
            result["price"] = float(price_el.get_text(strip=True).replace("$", "").replace(",", ""))
        except Exception:
            pass

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

    # BSR
    result["bsr"] = _parse_bsr(soup)

    # Weight
    result["weight_lbs"] = _parse_weight(soup)

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

            # Price
            price = None
            price_el = card.select_one(".a-price .a-offscreen")
            if price_el:
                try:
                    price = float(price_el.get_text(strip=True).replace("$", "").replace(",", ""))
                except Exception:
                    pass

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
