"""
AI Analysis Layer
Uses Claude Haiku for bulk review analysis + scoring.
Uses Claude Sonnet for final product brief generation.
"""

import json
import anthropic
from typing import Dict, List
from config import ANTHROPIC


client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


# ---------------------------------------------------------------------------
# PROMPT 1 — Review Analysis (Haiku — cheap, fast)
# ---------------------------------------------------------------------------
REVIEW_ANALYSIS_PROMPT = """You are an Amazon private label product researcher.

Analyze these customer reviews for a product and extract actionable insights.

REVIEWS:
{reviews}

Respond ONLY with a valid JSON object (no markdown, no preamble):
{{
  "pain_points": ["list of top 5 specific complaints customers have"],
  "praised_aspects": ["list of top 3 things customers love"],
  "improvement_opportunities": ["list of 3 specific ways a new product could be better"],
  "red_flags": ["any concerns: patent risk, brand dominance, safety issues, legal problems"],
  "sentiment_summary": "one sentence overall sentiment"
}}"""


# ---------------------------------------------------------------------------
# PROMPT 2 — Opportunity Scoring (Haiku)
# ---------------------------------------------------------------------------
SCORING_PROMPT = """You are an Amazon private label expert scoring a product opportunity.

PRODUCT DATA:
- Title: {title}
- Price: ${price}
- Reviews: {review_count}
- Rating: {rating}
- BSR: {bsr}
- Est. Monthly Revenue: ${monthly_revenue}
- Net Margin: {margin_pct}%
- Pain Points Found: {pain_points}
- Improvement Ideas: {improvement_opportunities}
- Red Flags: {red_flags}

Score this opportunity from 1–10 based on:
- Demand (revenue, BSR) — 30%
- Competition weakness (low reviews, room to improve) — 30%
- Margin viability — 20%
- Differentiation potential — 20%

Respond ONLY with valid JSON (no markdown):
{{
  "score": 7.5,
  "score_breakdown": {{
    "demand": 8,
    "competition_weakness": 7,
    "margin": 8,
    "differentiation": 7
  }},
  "verdict": "one sentence verdict on why this is/isn't a good opportunity",
  "go_no_go": "GO" or "NO-GO" or "MAYBE"
}}"""


# ---------------------------------------------------------------------------
# PROMPT 3 — Full Product Brief (Sonnet — higher quality)
# ---------------------------------------------------------------------------
BRIEF_PROMPT = """You are an experienced Amazon private label seller writing a product launch brief.

PRODUCT DATA:
{product_json}

Write a complete, actionable product brief that a sourcing team could use.

Respond ONLY with valid JSON (no markdown):
{{
  "product_name": "suggested product name",
  "target_customer": "specific customer profile in one sentence",
  "niche": "micro-niche description",
  "usp": "unique selling proposition in one sentence",
  "differentiation_plan": [
    "specific improvement 1 (fix a pain point)",
    "specific improvement 2 (add feature or bundle)",
    "specific improvement 3 (packaging or branding angle)"
  ],
  "target_keywords": ["main keyword", "secondary keyword 1", "secondary keyword 2", "long tail 1"],
  "suggested_price": 29.99,
  "estimated_launch_budget": 3000,
  "sourcing_notes": "what to search on Alibaba, MOQ estimate, key specs to request",
  "risks": ["risk 1", "risk 2"],
  "next_steps": ["step 1", "step 2", "step 3"]
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_haiku(prompt: str) -> str:
    msg = client.messages.create(
        model=ANTHROPIC["haiku_model"],
        max_tokens=ANTHROPIC["max_tokens"],
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_sonnet(prompt: str) -> str:
    msg = client.messages.create(
        model=ANTHROPIC["sonnet_model"],
        max_tokens=ANTHROPIC["max_tokens"],
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _parse_json(text: str) -> dict:
    """Safely parse JSON, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [AI] JSON parse error: {e}")
        return {}


# ---------------------------------------------------------------------------
# Main Analysis Functions
# ---------------------------------------------------------------------------

def analyze_reviews(reviews: List[str]) -> Dict:
    """Mine reviews for pain points and opportunities. Uses Haiku."""
    if not reviews:
        return {
            "pain_points": [],
            "praised_aspects": [],
            "improvement_opportunities": [],
            "red_flags": [],
            "sentiment_summary": "No reviews available",
        }

    # Batch reviews — send up to 80 at once to save tokens
    sample = reviews[:80]
    reviews_text = "\n---\n".join(sample)

    prompt = REVIEW_ANALYSIS_PROMPT.format(reviews=reviews_text)
    print("  [AI] Analyzing reviews with Haiku...")
    response = _call_haiku(prompt)
    return _parse_json(response)


def score_opportunity(product: Dict, review_analysis: Dict, profit: Dict) -> Dict:
    """Score the product opportunity 1–10. Uses Haiku."""
    prompt = SCORING_PROMPT.format(
        title=product.get("title", "Unknown"),
        price=product.get("price", 0),
        review_count=product.get("review_count", 0),
        rating=product.get("rating", 0),
        bsr=product.get("bsr", "Unknown"),
        monthly_revenue=product.get("monthly_revenue", 0),
        margin_pct=profit.get("margin_pct", 0),
        pain_points=review_analysis.get("pain_points", []),
        improvement_opportunities=review_analysis.get("improvement_opportunities", []),
        red_flags=review_analysis.get("red_flags", []),
    )
    print("  [AI] Scoring opportunity with Haiku...")
    response = _call_haiku(prompt)
    return _parse_json(response)


def generate_product_brief(product: Dict, review_analysis: Dict,
                           profit: Dict, scoring: Dict) -> Dict:
    """Generate full product brief. Uses Sonnet for quality."""
    combined = {
        **product,
        "review_analysis": review_analysis,
        "profitability": profit,
        "scoring": scoring,
    }
    # Remove noisy fields
    for key in ["raw_json", "filter_failures"]:
        combined.pop(key, None)

    prompt = BRIEF_PROMPT.format(product_json=json.dumps(combined, indent=2))
    print("  [AI] Generating product brief with Sonnet...")
    response = _call_sonnet(prompt)
    return _parse_json(response)


def run_full_analysis(product: Dict, reviews: List[str], profit: Dict) -> Dict:
    """
    Run the complete AI analysis pipeline for one product.
    Returns a combined result dict.
    """
    # Step 1: Review mining
    review_analysis = analyze_reviews(reviews)

    # Step 2: Opportunity scoring
    scoring = score_opportunity(product, review_analysis, profit)

    # Step 3: Product brief (only if score >= 6 to save API costs)
    score = scoring.get("score", 0)
    brief = {}
    if score >= 6.0:
        brief = generate_product_brief(product, review_analysis, profit, scoring)
    else:
        print(f"  [AI] Score {score} < 6.0 — skipping brief generation")

    return {
        "asin": product.get("asin"),
        "score": score,
        "go_no_go": scoring.get("go_no_go", "NO-GO"),
        "verdict": scoring.get("verdict", ""),
        "margin_pct": profit.get("margin_pct", 0),
        "net_profit": profit.get("net_profit", 0),
        "pain_points": review_analysis.get("pain_points", []),
        "diff_ideas": review_analysis.get("improvement_opportunities", []),
        "red_flags": review_analysis.get("red_flags", []),
        "product_brief": json.dumps(brief) if brief else "",
        "score_breakdown": scoring.get("score_breakdown", {}),
    }
