"""
Filter layer — applies your product criteria to raw scraped data.
Products that pass all checks move on to AI analysis.
"""

from typing import Dict, Tuple
from config import CRITERIA


def estimate_monthly_revenue(price: float, review_count: int, bsr: int) -> float:
    """
    Rough revenue estimate using the 'Jungle Scout estimator' formula.
    Real tools use proprietary sales data — this is a proxy.

    Logic:
    - Lower BSR = more sales
    - More reviews = more established product
    - We estimate daily sales from BSR, then multiply by price
    """
    if not price or not bsr:
        return 0.0

    # Daily sales estimate based on BSR (rough empirical curve)
    if bsr < 1000:
        daily_sales = 50
    elif bsr < 3000:
        daily_sales = 30
    elif bsr < 5000:
        daily_sales = 20
    elif bsr < 10000:
        daily_sales = 12
    elif bsr < 20000:
        daily_sales = 6
    elif bsr < 50000:
        daily_sales = 3
    elif bsr < 100000:
        daily_sales = 1
    else:
        daily_sales = 0.3

    monthly_revenue = daily_sales * 30 * price
    return round(monthly_revenue, 2)


def check_criteria(product: Dict) -> Tuple[bool, list, list]:
    """
    Returns (passed: bool, failures: list, checks: list of (passed, label, detail)).
    """
    failures = []
    checks = []  # (passed: bool, label: str, detail: str)
    c = CRITERIA

    price = product.get("price") or 0
    reviews = product.get("review_count") or 0
    bsr = product.get("bsr") or 999999
    rating = product.get("rating") or 0
    weight = product.get("weight_lbs") or 0
    revenue = product.get("monthly_revenue") or estimate_monthly_revenue(price, reviews, bsr)

    # Store estimated revenue back
    product["monthly_revenue"] = revenue

    # --- Price range ---
    if price < c["min_price"]:
        msg = f"${price} < min ${c['min_price']}"
        failures.append(f"Price {msg}")
        checks.append((False, "Price", msg))
    elif price > c["max_price"]:
        msg = f"${price} > max ${c['max_price']}"
        failures.append(f"Price {msg}")
        checks.append((False, "Price", msg))
    else:
        checks.append((True, "Price", f"${price} in [${c['min_price']}–${c['max_price']}]"))

    # --- Review count (competition gauge) ---
    if reviews > c["max_reviews"]:
        msg = f"{reviews} > max {c['max_reviews']}"
        failures.append(f"Reviews {msg}")
        checks.append((False, "Reviews", msg))
    else:
        checks.append((True, "Reviews", f"{reviews} ≤ max {c['max_reviews']}"))

    # --- BSR ---
    if bsr > c["max_bsr"]:
        msg = f"{bsr} > max {c['max_bsr']}"
        failures.append(f"BSR {msg}")
        checks.append((False, "BSR", msg))
    elif bsr < c["min_bsr"]:
        msg = f"{bsr} < min {c['min_bsr']}"
        failures.append(f"BSR {msg}")
        checks.append((False, "BSR", msg))
    else:
        checks.append((True, "BSR", f"{bsr} in [{c['min_bsr']}–{c['max_bsr']}]"))

    # --- Estimated revenue ---
    if revenue < c["min_monthly_revenue"]:
        msg = f"${revenue:.0f} < min ${c['min_monthly_revenue']}"
        failures.append(f"Est. revenue {msg}")
        checks.append((False, "Est. Revenue", msg))
    else:
        checks.append((True, "Est. Revenue", f"${revenue:.0f} ≥ min ${c['min_monthly_revenue']}"))

    # --- Rating sweet spot (not too high = no room to improve) ---
    if rating > 0 and rating < c["min_rating"]:
        msg = f"{rating} < min {c['min_rating']}"
        failures.append(f"Rating {msg}")
        checks.append((False, "Rating", msg))
    elif rating == 0:
        checks.append((True, "Rating", "N/A (skipped)"))
    else:
        checks.append((True, "Rating", f"{rating} ≥ min {c['min_rating']}"))

    # --- Weight ---
    if weight and weight > c["max_weight_lbs"]:
        msg = f"{weight}lbs > max {c['max_weight_lbs']}lbs"
        failures.append(f"Weight {msg}")
        checks.append((False, "Weight", msg))
    elif weight:
        checks.append((True, "Weight", f"{weight}lbs ≤ max {c['max_weight_lbs']}lbs"))
    else:
        checks.append((True, "Weight", "N/A (skipped)"))

    passed = len(failures) == 0
    return passed, failures, checks


def filter_products(products: list) -> Tuple[list, list]:
    """
    Split products into (passed, failed).
    Attaches pass/fail metadata to each product.
    """
    passed = []
    failed = []

    for p in products:
        ok, reasons, _checks = check_criteria(p)
        p["passed_filter"] = ok
        p["filter_failures"] = reasons
        if ok:
            passed.append(p)
        else:
            failed.append(p)

    print(f"  [Filter] {len(passed)} passed / {len(failed)} failed out of {len(products)} products")
    return passed, failed


def print_filter_summary(product: Dict):
    status = "✅ PASS" if product.get("passed_filter") else "❌ FAIL"
    print(f"  {status} | {product.get('asin')} | ${product.get('price')} | "
          f"Reviews: {product.get('review_count')} | BSR: {product.get('bsr')} | "
          f"Est. Rev: ${product.get('monthly_revenue', 0):.0f}/mo")
    if not product.get("passed_filter"):
        for r in product.get("filter_failures", []):
            print(f"         → {r}")
