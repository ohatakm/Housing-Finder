"""
budget_tools.py — Monthly cost estimator for Bay Area rentals
"""

from strands import tool

# ── Regional data ─────────────────────────────────────────────────────────────

# Average monthly utility costs by area (electricity + gas + internet + water)
UTILITY_ESTIMATES = {
    "sf":        {"electricity": 80,  "gas": 40,  "internet": 65, "water": 35},
    "south bay": {"electricity": 95,  "gas": 35,  "internet": 60, "water": 40},
    "east bay":  {"electricity": 85,  "gas": 38,  "internet": 60, "water": 38},
    "peninsula": {"electricity": 90,  "gas": 36,  "internet": 65, "water": 38},
    "north bay": {"electricity": 88,  "gas": 42,  "internet": 60, "water": 40},
    "all":       {"electricity": 87,  "gas": 38,  "internet": 62, "water": 38},
}

# Monthly commute cost estimates by mode
# (Caltrain, BART, Muni, driving — avg gas + wear + parking at destination)
COMMUTE_COSTS = {
    "bart":     {"monthly_pass": 120, "notes": "BART monthly clipper discount ~$120-180 depending on distance"},
    "caltrain": {"monthly_pass": 180, "notes": "Caltrain monthly pass ~$150-220 depending on zones"},
    "muni":     {"monthly_pass": 81,  "notes": "Muni monthly pass $81 (unlimited rides)"},
    "driving":  {"monthly_pass": 320, "notes": "Estimated gas + wear ~$200 + downtown parking ~$120-300/mo"},
    "bike":     {"monthly_pass": 25,  "notes": "Bike maintenance estimate ~$25/mo"},
    "remote":   {"monthly_pass": 0,   "notes": "Work from home — no commute cost"},
    "walk":     {"monthly_pass": 0,   "notes": "Walking distance — no commute cost"},
}

# Typical move-in cost multipliers
MOVE_IN_MULTIPLIERS = {
    "standard":    {"first": 1, "last": 1, "deposit": 1, "notes": "First + last month + 1 month deposit"},
    "deposit_only":{"first": 1, "last": 0, "deposit": 1, "notes": "First month + 1 month deposit"},
    "first_only":  {"first": 1, "last": 0, "deposit": 0, "notes": "First month only"},
    "high":        {"first": 1, "last": 1, "deposit": 2, "notes": "First + last + 2 month deposit (common in SF)"},
}

# Parking cost estimates by area (monthly, if not included in rent)
PARKING_COSTS = {
    "sf":        {"street": 0, "garage": 250, "notes": "SF street parking is free but competitive; garages avg $200-350/mo"},
    "south bay": {"street": 0, "garage": 80,  "notes": "Most South Bay apartments include parking or charge $50-120/mo"},
    "east bay":  {"street": 0, "garage": 100, "notes": "Oakland/Berkeley garages avg $80-150/mo"},
    "peninsula": {"street": 0, "garage": 120, "notes": "Peninsula garages avg $100-150/mo"},
    "north bay": {"street": 0, "garage": 60,  "notes": "North Bay parking usually free or low cost"},
    "all":       {"street": 0, "garage": 140, "notes": "Varies widely by city"},
}

# Renter's insurance estimate
RENTERS_INSURANCE = 18  # $/mo average in CA

# ── Tool ──────────────────────────────────────────────────────────────────────

@tool
def estimate_monthly_budget(
    rent: int,
    area: str = "sf",
    parking_needed: bool = False,
    commute_mode: str = "bart",
    move_in_type: str = "standard",
    utilities_included: bool = False,
    roommates: int = 0,
) -> str:
    """Estimate total monthly cost of a Bay Area rental beyond just rent.

    Args:
        rent: Monthly rent in USD
        area: sf, south bay, east bay, peninsula, north bay, or all
        parking_needed: True if parking is not included and tenant needs a spot
        commute_mode: bart, caltrain, muni, driving, bike, remote, or walk
        move_in_type: standard, deposit_only, first_only, or high
        utilities_included: True if utilities are included in rent
        roommates: Number of roommates splitting costs (0 = living alone)
    """
    area_key = area.lower().strip()
    if area_key not in UTILITY_ESTIMATES:
        area_key = "all"

    divisor = roommates + 1  # total people sharing costs

    # ── Utilities ──
    if utilities_included:
        util_total = 0
        util_note = "Utilities included in rent"
    else:
        u = UTILITY_ESTIMATES[area_key]
        util_total = u["electricity"] + u["gas"] + u["internet"] + u["water"]
        util_per_person = round(util_total / divisor)
        util_note = (
            f"Electricity ~${round(u['electricity']/divisor)}, "
            f"Gas ~${round(u['gas']/divisor)}, "
            f"Internet ~${round(u['internet']/divisor)}, "
            f"Water ~${round(u['water']/divisor)}"
        )
        util_total = util_per_person

    # ── Parking ──
    if parking_needed:
        p = PARKING_COSTS[area_key]
        parking_cost = round(p["garage"] / divisor)
        parking_note = p["notes"]
    else:
        parking_cost = 0
        parking_note = "Parking included or not needed"

    # ── Commute ──
    mode_key = commute_mode.lower().strip()
    if mode_key not in COMMUTE_COSTS:
        mode_key = "bart"
    c = COMMUTE_COSTS[mode_key]
    commute_cost = round(c["monthly_pass"] / divisor)
    commute_note = c["notes"]

    # ── Renter's insurance ──
    insurance = round(RENTERS_INSURANCE / divisor)

    # ── Monthly total ──
    monthly_total = rent + util_total + parking_cost + commute_cost + insurance

    # ── Move-in costs ──
    mi = MOVE_IN_MULTIPLIERS.get(move_in_type, MOVE_IN_MULTIPLIERS["standard"])
    move_in_cost = rent * (mi["first"] + mi["last"] + mi["deposit"])
    move_in_note = mi["notes"]

    # ── 3-month runway (move-in + 2 more months) ──
    three_month = move_in_cost + (monthly_total * 2)

    roommate_note = f" (split {divisor} ways)" if roommates > 0 else ""

    return (
        f"BUDGET ESTIMATE FOR ${rent:,}/mo RENT IN {area.upper()}{roommate_note}\n"
        f"{'='*55}\n\n"
        f"MONTHLY COSTS\n"
        f"  Rent:               ${rent:,}\n"
        f"  Utilities:          ${util_total:,}   — {util_note}\n"
        f"  Parking:            ${parking_cost:,}   — {parking_note}\n"
        f"  Commute ({mode_key}): ${commute_cost:,}   — {commute_note}\n"
        f"  Renter's insurance: ${insurance}\n"
        f"  ─────────────────────────────\n"
        f"  TOTAL/MONTH:        ${monthly_total:,}\n\n"
        f"MOVE-IN COSTS ({move_in_type})\n"
        f"  {move_in_note}\n"
        f"  Estimated move-in:  ${move_in_cost:,}\n\n"
        f"FINANCIAL RUNWAY\n"
        f"  Move-in + 2 months: ${three_month:,}\n"
        f"  Recommended savings before signing: ${three_month:,}+\n"
    )
