"""
Amazon Private Label Product Hunter
Main orchestrator — runs the full pipeline end to end.

Usage:
    python main.py                         # run with default keywords from config
    python main.py --keywords "yoga mat" "desk organizer"
    python main.py --keyword-file keywords.txt
    python main.py --asin B08XYZ123       # analyze a single ASIN directly
    python main.py --report               # print winners from DB without re-scraping
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from config import SEED_KEYWORDS, ANTHROPIC
from storage.database import init_db, save_product, save_analysis, get_winners, log_run
from scrapers.amazon_scraper import (
    scrape_search, scrape_product_page, scrape_reviews, get_keyword_suggestions
)
from analysis.filter import filter_products, print_filter_summary
from analysis.profitability import calculate_profitability, format_profit_table
from analysis.ai_analysis import run_full_analysis
from alerts.telegram_bot import alert_winner, alert_run_summary

# ── Ensure output dirs exist ──────────────────────────────────────────────
Path("data/results").mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE STEPS
# ─────────────────────────────────────────────────────────────────────────────

def step1_collect(keywords: list, max_per_keyword: int = 20) -> list:
    """Scrape search results for all keywords. Returns flat list of raw products."""
    print(f"\n{'='*60}")
    print(f"STEP 1 — Collecting products for {len(keywords)} keywords")
    print(f"{'='*60}")

    all_products = []
    seen_asins = set()

    for keyword in keywords:
        # Also expand with autocomplete suggestions
        suggestions = get_keyword_suggestions(keyword)
        expanded = [keyword] + suggestions[:2]  # max 3 variants per seed

        for kw in expanded:
            products = scrape_search(kw, max_products=max_per_keyword)
            for p in products:
                asin = p.get("asin")
                if asin and asin not in seen_asins:
                    seen_asins.add(asin)
                    all_products.append(p)

    print(f"\n  Total unique products collected: {len(all_products)}")
    return all_products


def step2_enrich(products: list) -> list:
    """Fetch full product page for each candidate to get BSR, weight, category."""
    print(f"\n{'='*60}")
    print(f"STEP 2 — Enriching {len(products)} products with full page data")
    print(f"{'='*60}")

    enriched = []
    for i, p in enumerate(products, 1):
        asin = p.get("asin")
        print(f"  [{i}/{len(products)}] Enriching {asin}...")
        page_data = scrape_product_page(asin)
        merged = {**p, **{k: v for k, v in page_data.items() if v is not None}}
        enriched.append(merged)

    return enriched


def step3_filter(products: list):
    """Apply criteria filters. Returns (passed, failed)."""
    print(f"\n{'='*60}")
    print(f"STEP 3 — Filtering {len(products)} products")
    print(f"{'='*60}")

    passed, failed = filter_products(products)

    # Save all to DB
    for p in products:
        save_product(p)

    print(f"\n  Passed: {len(passed)} | Failed: {len(failed)}")
    for p in passed:
        print_filter_summary(p)

    return passed, failed


def step4_analyze(products: list) -> list:
    """Run AI analysis on each product that passed filters."""
    print(f"\n{'='*60}")
    print(f"STEP 4 — AI Analysis on {len(products)} products")
    print(f"{'='*60}")

    winners = []

    for i, product in enumerate(products, 1):
        asin = product.get("asin")
        print(f"\n  [{i}/{len(products)}] Analyzing {asin} — {product.get('title', '')[:50]}...")

        # Profitability
        profit = calculate_profitability(product)
        print(format_profit_table(profit))

        if not profit["viable"]:
            print(f"  ⚠️  Margin too low ({profit['margin_pct']}%) — skipping AI analysis")
            continue

        # Fetch reviews
        reviews = scrape_reviews(asin, max_pages=2)

        # AI analysis
        result = run_full_analysis(product, reviews, profit)

        # Save to DB
        save_analysis(asin, result)

        score = result.get("score", 0)
        print(f"\n  🎯 Score: {score}/10  |  {result.get('go_no_go')}  |  {result.get('verdict')}")

        if score >= 7.0:
            winners.append({**product, **result})
            print(f"  ⭐ WINNER ADDED TO LIST!")
            alert_winner(product, result)

    return winners


def export_run_report(passed: list, failed: list, keywords: list, timestamp: str):
    """Write a human-readable text report of passed and failed products."""
    lines = []
    sep = "=" * 60

    lines += [
        sep,
        "AMAZON PL HUNTER — FILTER REPORT",
        f"Generated:  {timestamp}",
        f"Keywords:   {', '.join(keywords)}",
        sep,
        "",
        "SUMMARY",
        f"  Total:          {len(passed) + len(failed)}",
        f"  Passed filter:  {len(passed)}",
        f"  Failed filter:  {len(failed)}",
        "",
    ]

    lines += [sep, f"PASSED ({len(passed)})", sep, ""]
    for i, p in enumerate(passed, 1):
        lines += [
            f"[{i}] ASIN:     {p.get('asin')}",
            f"    Title:    {(p.get('title') or 'N/A')[:70]}",
            f"    Price:    ${p.get('price')}",
            f"    Reviews:  {p.get('review_count'):,}" if p.get("review_count") else "    Reviews:  N/A",
            f"    BSR:      {p.get('bsr'):,}" if p.get("bsr") else "    BSR:      N/A",
            f"    Rating:   {p.get('rating')} ★",
            f"    Est Rev:  ${p.get('monthly_revenue', 0):.0f}/mo",
            f"    URL:      https://www.amazon.com/dp/{p.get('asin')}",
            "",
        ]

    lines += [sep, f"FAILED ({len(failed)})", sep, ""]
    for i, p in enumerate(failed, 1):
        lines += [
            f"[{i}] ASIN:     {p.get('asin')}",
            f"    Title:    {(p.get('title') or 'N/A')[:70]}",
            f"    Price:    ${p.get('price')}",
            f"    Reviews:  {p.get('review_count'):,}" if p.get("review_count") else "    Reviews:  N/A",
            f"    BSR:      {p.get('bsr'):,}" if p.get("bsr") else "    BSR:      N/A",
            f"    Rating:   {p.get('rating')} ★",
            f"    Est Rev:  ${p.get('monthly_revenue', 0):.0f}/mo",
            "    Reasons:",
        ]
        for reason in p.get("filter_failures", []):
            lines.append(f"      → {reason}")
        lines.append("")

    ts_file = timestamp.replace(":", "-").replace(" ", "_")
    path = f"data/results/filter_report_{ts_file}.txt"
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n  📄 Filter report saved to: {path}")
    return path


def step5_report(winners: list):
    """Print final report and save to JSON."""
    print(f"\n{'='*60}")
    print(f"STEP 5 — Final Report")
    print(f"{'='*60}")

    if not winners:
        print("\n  No winners found in this run. Adjust criteria or try new keywords.")
        return

    print(f"\n  🏆 {len(winners)} WINNER(S) FOUND:\n")
    for w in sorted(winners, key=lambda x: x.get("score", 0), reverse=True):
        print(f"  {'─'*50}")
        print(f"  ASIN:      {w.get('asin')}")
        print(f"  Title:     {w.get('title', 'N/A')[:60]}")
        print(f"  Score:     {w.get('score')}/10")
        print(f"  Price:     ${w.get('price')}")
        print(f"  Reviews:   {w.get('review_count')}")
        print(f"  Margin:    {w.get('margin_pct')}%")
        print(f"  Revenue:   ${w.get('monthly_revenue', 0):.0f}/mo (est.)")
        print(f"  Verdict:   {w.get('verdict')}")

        pain = w.get("pain_points") or []
        if pain:
            print(f"  Pain pts:  {'; '.join(pain[:2])}")

        brief_raw = w.get("product_brief", "")
        if brief_raw:
            try:
                brief = json.loads(brief_raw)
                if brief.get("usp"):
                    print(f"  USP:       {brief['usp']}")
                if brief.get("target_keywords"):
                    print(f"  Keywords:  {', '.join(brief['target_keywords'][:4])}")
            except Exception:
                pass

        print(f"  URL:       https://www.amazon.com/dp/{w.get('asin')}")

    # Save JSON report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"data/results/winners_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(winners, f, indent=2, default=str)
    print(f"\n  📄 Full report saved to: {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def run_hunt(keywords: list):
    """Run the complete product hunting pipeline."""
    started_at = datetime.now(timezone.utc).isoformat()
    print(f"\n🚀 Amazon PL Hunter starting at {started_at}")
    print(f"   Keywords: {keywords}")

    # Init DB
    init_db()

    # Run pipeline
    raw_products = step1_collect(keywords)
    enriched = step2_enrich(raw_products)
    passed, failed = step3_filter(enriched)
    export_run_report(passed, failed, keywords, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    winners = step4_analyze(passed)
    step5_report(winners)

    # Log run
    finished_at = datetime.now(timezone.utc).isoformat()
    log_run(started_at, finished_at, keywords,
            found=len(raw_products), passed=len(passed), winners=len(winners))

    # Summary alert
    alert_run_summary(len(raw_products), len(passed), len(winners), len(keywords))

    print(f"\n✅ Done! Run took: {finished_at}")
    return winners


def print_db_winners():
    """Print winners already in database (no new scraping)."""
    init_db()
    winners = get_winners(min_score=7.0)
    if not winners:
        print("No winners in database yet. Run a hunt first.")
        return
    print(f"\n{'='*60}")
    print(f"DATABASE WINNERS (score ≥ 7.0) — {len(winners)} found")
    print(f"{'='*60}")
    for w in winners:
        print(f"\n  ASIN: {w['asin']} | Score: {w['score']} | Margin: {w['margin_pct']}%")
        print(f"  Title: {w.get('title', 'N/A')[:70]}")
        print(f"  URL: https://www.amazon.com/dp/{w['asin']}")


def analyze_single_asin(asin: str):
    """Analyze a single ASIN you already found."""
    init_db()
    print(f"\n🔍 Analyzing single ASIN: {asin}")
    product = scrape_product_page(asin)
    if not product:
        print(f"Failed to fetch {asin}")
        return

    profit = calculate_profitability(product)
    print(format_profit_table(profit))

    reviews = scrape_reviews(asin, max_pages=3)
    result = run_full_analysis(product, reviews, profit)
    save_product({**product, "passed_filter": True})
    save_analysis(asin, result)

    print(f"\n  Score: {result.get('score')}/10")
    print(f"  Verdict: {result.get('verdict')}")

    brief_raw = result.get("product_brief", "")
    if brief_raw:
        try:
            brief = json.loads(brief_raw)
            print(f"\n  Product Brief:")
            print(json.dumps(brief, indent=4))
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Amazon PL Product Hunter")
    parser.add_argument("--keywords", nargs="+", help="Keywords to search")
    parser.add_argument("--keyword-file", help="File with one keyword per line")
    parser.add_argument("--asin", help="Analyze a single ASIN")
    parser.add_argument("--report", action="store_true", help="Print DB winners")
    args = parser.parse_args()

    if args.report:
        print_db_winners()
    elif args.asin:
        analyze_single_asin(args.asin)
    else:
        if args.keywords:
            keywords = args.keywords
        elif args.keyword_file:
            with open(args.keyword_file) as f:
                keywords = [line.strip() for line in f if line.strip()]
        else:
            keywords = SEED_KEYWORDS

        run_hunt(keywords)
