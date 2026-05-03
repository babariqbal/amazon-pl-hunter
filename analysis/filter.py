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


def check_criteria(product: Dict) -> Tuple[bool, list]:
    """
    Returns (passed: bool, reasons: list of failures).
    """
    failures = []
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
        failures.append(f"Price ${price} < min ${c['min_price']}")
    elif price > c["max_price"]:
        failures.append(f"Price ${price} > max ${c['max_price']}")

    # --- Review count (competition gauge) ---
    if reviews > c["max_reviews"]:
        failures.append(f"Reviews {reviews} > max {c['max_reviews']}")

    # --- BSR ---
    if bsr > c["max_bsr"]:
        failures.append(f"BSR {bsr} > max {c['max_bsr']}")
    if bsr < c["min_bsr"]:
        failures.append(f"BSR {bsr} < min {c['min_bsr']}")

    # --- Estimated revenue ---
    if revenue < c["min_monthly_revenue"]:
        failures.append(f"Est. revenue ${revenue:.0f} < min ${c['min_monthly_revenue']}")

    # --- Rating sweet spot (not too high = no room to improve) ---
    if rating > 0 and rating < c["min_rating"]:
        failures.append(f"Rating {rating} < min {c['min_rating']}")

    # --- Weight ---
    if weight and weight > c["max_weight_lbs"]:
        failures.append(f"Weight {weight}lbs > max {c['max_weight_lbs']}lbs")

    passed = len(failures) == 0
    return passed, failures


def filter_products(products: list) -> Tuple[list, list]:
    """
    Split products into (passed, failed).
    Attaches pass/fail metadata to each product.
    """
    passed = []
    failed = []

    for p in products:
        ok, reasons = check_criteria(p)
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
