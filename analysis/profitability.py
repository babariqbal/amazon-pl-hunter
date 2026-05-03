"""
FBA Profitability Calculator
Estimates net margin per unit based on selling price and product weight.
"""

from typing import Dict
from config import FBA, PROFIT


def get_fba_fee(price: float, weight_lbs: float) -> float:
    """
    Estimate FBA fulfillment fee based on weight.
    Uses simplified US fee schedule (2024).
    """
    if weight_lbs <= 0:
        weight_lbs = 0.5  # assume small/light if unknown

    if weight_lbs <= 1.0:
        return FBA["small_standard_fee"]
    elif weight_lbs <= 2.0:
        return FBA["large_standard_fee"]
    elif weight_lbs <= 3.0:
        return 6.10
    elif weight_lbs <= 5.0:
        return 7.17
    else:
        return 8.50 + (weight_lbs - 5) * 0.42


def calculate_profitability(product: Dict) -> Dict:
    """
    Returns profitability breakdown for a product.
    """
    price = product.get("price") or 0
    weight = product.get("weight_lbs") or 0.5

    if price <= 0:
        return {
            "viable": False,
            "reason": "No price data",
            "net_profit": 0,
            "margin_pct": 0,
        }

    # --- Revenue ---
    selling_price = price

    # --- Costs ---
    referral_fee = round(selling_price * FBA["referral_fee_pct"], 2)
    fba_fee = round(get_fba_fee(selling_price, weight), 2)
    storage_fee = FBA["storage_fee_per_unit"]
    misc_fee = FBA["misc_fee"]
    cogs = round(selling_price * PROFIT["cogs_ratio"], 2)   # 25% of price from Alibaba
    ppc = PROFIT["ppc_per_unit"]

    total_costs = referral_fee + fba_fee + storage_fee + misc_fee + cogs + ppc
    net_profit = round(selling_price - total_costs, 2)
    margin_pct = round((net_profit / selling_price) * 100, 1) if selling_price else 0

    viable = margin_pct >= PROFIT["target_margin_pct"]

    return {
        "viable": viable,
        "selling_price": selling_price,
        "cogs": cogs,
        "referral_fee": referral_fee,
        "fba_fee": fba_fee,
        "storage_fee": storage_fee,
        "misc_fee": misc_fee,
        "ppc": ppc,
        "total_costs": round(total_costs, 2),
        "net_profit": net_profit,
        "margin_pct": margin_pct,
        "target_margin_pct": PROFIT["target_margin_pct"],
    }


def format_profit_table(calc: Dict) -> str:
    """Pretty-print the profitability breakdown."""
    lines = [
        f"  Selling Price:     ${calc.get('selling_price', 0):.2f}",
        f"  COGS (est.):      -${calc.get('cogs', 0):.2f}",
        f"  Amazon Referral:  -${calc.get('referral_fee', 0):.2f}",
        f"  FBA Fee:          -${calc.get('fba_fee', 0):.2f}",
        f"  Storage:          -${calc.get('storage_fee', 0):.2f}",
        f"  Misc (inbound):   -${calc.get('misc_fee', 0):.2f}",
        f"  PPC (ads):        -${calc.get('ppc', 0):.2f}",
        f"  ─────────────────────────",
        f"  Net Profit/unit:   ${calc.get('net_profit', 0):.2f}",
        f"  Net Margin:        {calc.get('margin_pct', 0):.1f}%",
        f"  Viable (>={calc.get('target_margin_pct')}%):  {'✅ YES' if calc.get('viable') else '❌ NO'}",
    ]
    return "\n".join(lines)
