"""
Telegram Bot Alerts — free, instant notifications when winners are found.
Setup: message @BotFather on Telegram → /newbot → get token
Then message your bot and get your chat_id from:
https://api.telegram.org/bot<TOKEN>/getUpdates
"""

import requests
from config import TELEGRAM


def _enabled() -> bool:
    return bool(TELEGRAM.get("bot_token") and TELEGRAM.get("chat_id"))


def send_message(text: str):
    """Send a plain text message to your Telegram chat."""
    if not _enabled():
        return  # silently skip if not configured

    url = f"https://api.telegram.org/bot{TELEGRAM['bot_token']}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM["chat_id"],
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
        if resp.status_code != 200:
            print(f"  [Telegram] Failed: {resp.text}")
    except Exception as e:
        print(f"  [Telegram] Error: {e}")


def alert_winner(product: dict, analysis: dict):
    """Send a formatted winner alert."""
    brief_raw = analysis.get("product_brief", "")
    brief = {}
    if brief_raw:
        import json
        try:
            brief = json.loads(brief_raw)
        except Exception:
            pass

    lines = [
        "🏆 *NEW PRODUCT WINNER FOUND*",
        "",
        f"*ASIN:* `{product.get('asin')}`",
        f"*Title:* {product.get('title', 'N/A')[:60]}...",
        f"*Score:* {analysis.get('score')}/10  |  *Verdict:* {analysis.get('go_no_go')}",
        f"*Price:* ${product.get('price')}  |  *Reviews:* {product.get('review_count')}",
        f"*Net Margin:* {analysis.get('margin_pct')}%  |  *Net Profit:* ${analysis.get('net_profit')}/unit",
        "",
        "*Top Pain Points:*",
    ]

    for p in (analysis.get("pain_points") or [])[:3]:
        lines.append(f"• {p}")

    if brief.get("usp"):
        lines += ["", f"*USP:* {brief['usp']}"]

    if brief.get("target_keywords"):
        lines += ["", f"*Keywords:* {', '.join(brief['target_keywords'][:4])}"]

    lines += ["", f"🔗 https://www.amazon.com/dp/{product.get('asin')}"]

    send_message("\n".join(lines))


def alert_run_summary(found: int, passed: int, winners: int, keyword_count: int):
    """Send end-of-run summary."""
    msg = (
        f"📊 *Hunt Run Complete*\n"
        f"Keywords searched: {keyword_count}\n"
        f"Products found: {found}\n"
        f"Passed filters: {passed}\n"
        f"Winners (score ≥7): {winners}"
    )
    send_message(msg)
