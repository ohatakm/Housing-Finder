"""
Bay Area Housing Finder — Streamlit UI
Run with: streamlit run streamlit_app.py
"""

import re
import urllib.parse

import boto3
import streamlit as st

from budget_tools import estimate_monthly_budget, COMMUTE_COSTS, UTILITY_ESTIMATES, PARKING_COSTS, MOVE_IN_MULTIPLIERS, RENTERS_INSURANCE
from listing_tools import _fetch_rss, AREA_CODES, AREA_ZIPS, SOURCES, fetch_all_sources, search_listings, get_listing_details
from filter_tools import filter_listings
from favorites_tools import (
    _load_favorites,
    save_favorite,
    view_favorites,
    remove_favorite,
)
from strands import Agent
from strands.models.bedrock import BedrockModel

# ── Constants ────────────────────────────────────────────────────────────────

PROFILE  = "GSB570-BedrockOnly-490332585640"
MODEL_ID = "us.amazon.nova-pro-v1:0"

SYSTEM_PROMPT = """You are a Bay Area housing assistant helping post-grads and young professionals
find rental housing. You search Craigslist Bay Area across apartments, rooms/shared housing, and sublets to help users find the best options.

When a user describes what they're looking for use search_listings, then filter_listings if needed,
then get_listing_details for promising ones.

For EVERY listing always include:
- Title, Price, Neighborhood, Key features, Why it matches
- The full Craigslist URL (never omit it)

Use save_favorite / view_favorites / remove_favorite when asked.
When a user asks about total costs, affordability, or move-in budget, use estimate_monthly_budget.
"""

SORT_OPTIONS = [
    "Default",
    "Price: Low to High",
    "Price: High to Low",
    "Neighborhood A–Z",
    "Title A–Z",
]

AREAS = ["all", "sf", "south bay", "east bay", "peninsula", "north bay"]

AREA_LABELS = {
    "all": "All Bay Area",
    "sf": "San Francisco",
    "south bay": "South Bay",
    "east bay": "East Bay",
    "peninsula": "Peninsula",
    "north bay": "North Bay",
}

SOURCE_COLORS = {
    "Apartments":   "#c0392b",
    "Rooms/Shared": "#1a6b3c",
    "Sublets":      "#1a4a8a",
}

SOURCE_ICONS = {
    "Apartments":   "",
    "Rooms/Shared": "",
    "Sublets":      "",
}

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Bay Area Housing Finder",
    page_icon="—",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Global CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }

/* ── Header ── */
.app-header {
    padding: 2.5rem 0 1.8rem;
    border-bottom: 1px solid rgba(128,128,128,0.15);
    margin-bottom: 2rem;
}
.app-header h1 {
    font-size: 1.6rem;
    font-weight: 600;
    letter-spacing: -0.5px;
    margin: 0 0 0.3rem;
}
.app-header p {
    font-size: 0.875rem;
    opacity: 0.5;
    margin: 0;
    font-weight: 400;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: transparent;
    padding: 0;
    border-bottom: 1px solid rgba(128,128,128,0.2);
    border-radius: 0;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 0;
    padding: 10px 20px;
    font-weight: 400;
    font-size: 0.875rem;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    font-weight: 600 !important;
    border-bottom: 2px solid currentColor !important;
    box-shadow: none !important;
}

/* ── Listing card ── */
.listing-card {
    border: 1px solid rgba(128,128,128,0.18);
    border-radius: 8px;
    padding: 1.1rem 1.25rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.listing-card:hover {
    border-color: rgba(128,128,128,0.4);
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.listing-title {
    font-size: 0.95rem;
    font-weight: 600;
    margin: 0 0 0.2rem;
    line-height: 1.4;
}
.listing-meta {
    font-size: 0.8rem;
    opacity: 0.55;
    margin-bottom: 0.45rem;
}
.listing-price {
    font-size: 1.1rem;
    font-weight: 700;
    white-space: nowrap;
}
.listing-desc {
    font-size: 0.82rem;
    opacity: 0.65;
    line-height: 1.55;
    margin: 0.35rem 0 0.5rem;
}
.source-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: white;
    margin-right: 8px;
}
.view-btn {
    display: inline-block;
    padding: 4px 12px;
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 4px;
    font-size: 0.78rem;
    font-weight: 500;
    text-decoration: none;
    opacity: 0.8;
    transition: opacity 0.1s, border-color 0.1s;
    color: inherit !important;
}
.view-btn:hover { opacity: 1; border-color: rgba(128,128,128,0.7); }

/* ── Stats bar ── */
.stats-bar {
    font-size: 0.8rem;
    opacity: 0.6;
    padding: 0.5rem 0;
    margin-bottom: 1rem;
    border-bottom: 1px solid rgba(128,128,128,0.12);
    display: flex;
    gap: 1.5rem;
    flex-wrap: wrap;
}

/* ── Empty state ── */
.empty-state {
    text-align: center;
    padding: 4rem 1rem;
    opacity: 0.4;
}
.empty-state p { font-size: 0.9rem; margin: 0; }

/* ── Favorite card ── */
.fav-card {
    border: 1px solid rgba(128,128,128,0.18);
    border-left: 3px solid #555;
    border-radius: 6px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.6rem;
}
.fav-title { font-weight: 600; font-size: 0.9rem; }
.fav-meta  { font-size: 0.78rem; opacity: 0.55; margin-top: 0.2rem; }

/* ── Buttons ── */
.stButton > button {
    border-radius: 5px !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    letter-spacing: 0.01em !important;
}

/* ── Inputs ── */
.stTextInput input, .stNumberInput input, .stTextArea textarea {
    border-radius: 5px !important;
    font-size: 0.875rem !important;
}
.stSelectbox > div > div {
    border-radius: 5px !important;
    font-size: 0.875rem !important;
}

/* ── Section label ── */
.section-label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.45;
    margin-bottom: 0.75rem;
}
</style>
""", unsafe_allow_html=True)

# ── Hero ──────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
  <h1>Bay Area Housing Finder</h1>
  <p>Live rental search across Craigslist apartments, rooms, and sublets</p>
</div>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("messages", []),
    ("agent", None),
    ("qs_listings", []),
    ("br_listings", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Connecting to AWS…")
def get_agent() -> Agent:
    session = boto3.Session(profile_name=PROFILE)
    model = BedrockModel(model_id=MODEL_ID, max_tokens=4096, boto_session=session)
    return Agent(
        model=model,
        tools=[search_listings, get_listing_details, filter_listings,
               save_favorite, view_favorites, remove_favorite,
               estimate_monthly_budget],
        system_prompt=SYSTEM_PROMPT,
    )


def fetch_listings(area, max_price, min_price, bedrooms, keyword, sources=None):
    return fetch_all_sources(
        area=area.lower().strip(),
        max_price=int(max_price),
        min_price=int(min_price),
        bedrooms=bedrooms,
        query=keyword or "",
        sources=sources,
    )


def sort_listings(listings, sort_by):
    if sort_by == "Price: Low to High":
        return sorted(listings, key=lambda l: l["price"] or 999999)
    if sort_by == "Price: High to Low":
        return sorted(listings, key=lambda l: l["price"] or 0, reverse=True)
    if sort_by == "Neighborhood A–Z":
        return sorted(listings, key=lambda l: (l["neighborhood"] or "").lower())
    if sort_by == "Title A–Z":
        return sorted(listings, key=lambda l: l["title"].lower())
    return listings


def render_listing_cards(listings, sort_by):
    listings = sort_listings(listings, sort_by)

    # Stats bar
    by_source = {}
    for l in listings:
        by_source[l["source"]] = by_source.get(l["source"], 0) + 1
    prices = [l["price"] for l in listings if l["price"]]
    avg_price = int(sum(prices) / len(prices)) if prices else 0
    stats_parts = [f"<strong>{len(listings)}</strong> listings"]
    if avg_price:
        stats_parts.append(f"avg <strong>${avg_price:,}/mo</strong>")
    for src, cnt in by_source.items():
        icon = SOURCE_ICONS.get(src, "📌")
        stats_parts.append(f"{icon} {src}: <strong>{cnt}</strong>")
    st.markdown(
        f'<div class="stats-bar">{" &nbsp;·&nbsp; ".join(stats_parts)}</div>',
        unsafe_allow_html=True,
    )

    for l in listings:
        hood  = l["neighborhood"] or "Bay Area"
        price = l["price_raw"] if l["price_raw"] != "N/A" else "—"
        desc  = l["description"][:200] + "…" if l["description"] else ""
        source = l.get("source", "")
        badge_color = SOURCE_COLORS.get(source, "#555")
        icon = SOURCE_ICONS.get(source, "📌")
        link = l.get("link", "")

        price_display = f"{price}/mo" if price != "—" else "Price N/A"

        desc_html = f'<div class="listing-desc">{desc}</div>' if desc else ""
        link_html = f'<a href="{link}" target="_blank" class="view-btn">View listing →</a>' if link else ""
        title_safe = l["title"]
        card_html = (
            '<div class="listing-card">'
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;">'
            '<div style="flex:1;min-width:0;">'
            f'<div class="listing-title">{title_safe}</div>'
            f'<div class="listing-meta">📍 {hood}</div>'
            f'{desc_html}'
            '</div>'
            '<div style="text-align:right;flex-shrink:0;">'
            f'<div class="listing-price">{price_display}</div>'
            '</div></div>'
            '<div style="margin-top:0.6rem;display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">'
            f'<span class="source-badge" style="background:{badge_color};">{icon} {source}</span>'
            f'{link_html}'
            '</div></div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chat, tab_browse, tab_search, tab_favs, tab_budget = st.tabs([
    "Chat",
    "Browse",
    "Search",
    "Saved",
    "Budget",
])

# ── Tab 1: Chat ───────────────────────────────────────────────────────────────

with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if not st.session_state.messages:
        st.markdown(
            '<div class="section-label" style="margin-bottom:0.75rem;">Suggested searches</div>',
            unsafe_allow_html=True,
        )
        examples = [
            "Recent grad, budget $2,500/mo — what's available in SF?",
            "Furnished studios in the South Bay under $2,000",
            "Pet-friendly 1BRs in Oakland or Berkeley under $2,400",
            "Roommate situation in the Peninsula, max $1,500",
        ]
        cols = st.columns(2)
        for i, ex in enumerate(examples):
            if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
                st.session_state._prefill = ex
                st.rerun()

    prefill = st.session_state.pop("_prefill", None)
    prompt = st.chat_input("Describe what you're looking for…") or prefill

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Searching listings…"):
                try:
                    agent = get_agent()
                    raw = str(agent(prompt))
                    response = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
                except Exception as e:
                    response = f"Error: {e}"
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

    if st.session_state.messages:
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.messages = []
            st.rerun()

# ── Tab 2: Browse ─────────────────────────────────────────────────────────────

with tab_browse:
    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 2])
    br_area    = c1.selectbox("Area", AREAS, format_func=lambda x: AREA_LABELS.get(x, x), key="br_area")
    br_min     = c2.number_input("Min $", value=0, step=100, key="br_min")
    br_max     = c3.number_input("Max $", value=3500, step=100, key="br_max")
    br_beds    = c4.selectbox("Beds", ["any", "0", "1", "2", "3", "4"],
                               format_func=lambda x: "Any" if x == "any" else ("Studio" if x == "0" else f"{x} BR"),
                               key="br_beds")
    br_keyword = c5.text_input("Keyword", placeholder="furnished, parking, utilities…", key="br_kw")

    sc1, sc2 = st.columns([3, 1])
    br_sources = sc1.multiselect("Listing type", options=SOURCES, default=SOURCES, key="br_sources")
    br_sort    = sc2.selectbox("Sort", SORT_OPTIONS, index=1, key="br_sort")
    st.markdown("</div>", unsafe_allow_html=True)

    load = st.button("Load listings", type="primary", use_container_width=True, key="br_load")

    if load:
        with st.spinner("Fetching listings from Craigslist…"):
            try:
                st.session_state.br_listings = fetch_listings(
                    br_area, br_max, br_min, br_beds, br_keyword,
                    sources=br_sources if br_sources else None,
                )
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state.br_listings:
        render_listing_cards(st.session_state.br_listings, br_sort)
    else:
        st.markdown('<div class="empty-state"><p>Set your filters and click <strong>Load listings</strong></p></div>', unsafe_allow_html=True)

# ── Tab 3: Search ─────────────────────────────────────────────────────────────

with tab_search:
    st.markdown("<div class='filter-panel'>", unsafe_allow_html=True)
    q1, q2, q3 = st.columns([2, 2, 1])
    qs_area    = q1.selectbox("Area", AREAS, format_func=lambda x: AREA_LABELS.get(x, x), key="qs_area")
    qs_max     = q2.slider("Max rent ($/mo)", 500, 6000, 2500, 100, key="qs_max")
    qs_beds    = q3.selectbox("Beds", ["any", "0", "1", "2", "3", "4"],
                               format_func=lambda x: "Any" if x == "any" else ("Studio" if x == "0" else f"{x} BR"),
                               key="qs_beds")
    sq1, sq2, sq3 = st.columns([2, 2, 1])
    qs_keyword = sq1.text_input("Keyword", placeholder="furnished, parking, utilities…", key="qs_kw")
    qs_sources = sq2.multiselect("Listing type", options=SOURCES, default=SOURCES, key="qs_sources")
    qs_sort    = sq3.selectbox("Sort", SORT_OPTIONS, key="qs_sort")
    st.markdown("</div>", unsafe_allow_html=True)

    qs_go = st.button("Search", type="primary", use_container_width=True, key="qs_go")

    if qs_go:
        with st.spinner("Fetching listings from Craigslist…"):
            try:
                st.session_state.qs_listings = fetch_listings(
                    qs_area, qs_max, 0, qs_beds, qs_keyword,
                    sources=qs_sources if qs_sources else None,
                )
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state.qs_listings:
        render_listing_cards(st.session_state.qs_listings, qs_sort)
    else:
        st.markdown('<div class="empty-state"><p>Set your filters and click <strong>Search</strong></p></div>', unsafe_allow_html=True)

# ── Tab 4: Favorites ──────────────────────────────────────────────────────────

with tab_favs:
    favs = _load_favorites()

    if not favs:
        st.markdown('<div class="empty-state"><p>No saved listings yet. Ask the agent to save one for you.</p></div>', unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="section-label">{len(favs)} saved listing{"s" if len(favs) != 1 else ""}</div>',
            unsafe_allow_html=True,
        )
        for f in favs:
            col_a, col_b = st.columns([6, 1])
            with col_a:
                st.markdown(f"""
<div class="fav-card">
  <div class="fav-title">{f['title']}</div>
  <div class="fav-meta">💰 {f['price']} &nbsp;·&nbsp; 📍 {f['neighborhood']} &nbsp;·&nbsp; 🗓 {f['saved_at']}</div>
  {"<div style='font-size:0.82rem;color:#555;margin-top:0.4rem;'>📝 " + f['notes'] + "</div>" if f.get('notes') else ""}
  <div style="margin-top:0.6rem;">
    <a href="{f['url']}" target="_blank" class="view-btn">View listing →</a>
  </div>
</div>""", unsafe_allow_html=True)
            with col_b:
                st.markdown("<div style='padding-top:0.6rem;'>", unsafe_allow_html=True)
                if st.button("Remove", key=f"rm_{f['url']}", help="Remove from favorites"):
                    remove_favorite(f["url"])
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Refresh", key="refresh_favs"):
        st.rerun()


# ── Tab 5: Budget Estimator ───────────────────────────────────────────────────

with tab_budget:
    st.markdown('<div class="section-label">Budget estimator</div>', unsafe_allow_html=True)
    st.caption("See your true monthly cost beyond rent — utilities, commute, parking, and move-in.")

    # ── Inputs ──
    with st.container(border=True):
        b1, b2, b3 = st.columns(3)
        bgt_rent      = b1.number_input("Monthly rent ($)", value=2500, step=50, min_value=500, max_value=15000, key="bgt_rent")
        bgt_area      = b2.selectbox("Area", AREAS, format_func=lambda x: AREA_LABELS.get(x, x), key="bgt_area")
        bgt_roommates = b3.number_input("Roommates splitting costs", value=0, min_value=0, max_value=5, step=1, key="bgt_roommates",
                                         help="Enter the number of additional people splitting costs with you. 0 = living alone.")

        b4, b5, b6 = st.columns(3)
        bgt_commute = b4.selectbox(
            "Commute mode",
            options=list(COMMUTE_COSTS.keys()),
            format_func=lambda x: {
                "bart": "BART", "caltrain": "Caltrain", "muni": "Muni / Bus",
                "driving": "Driving", "bike": "Bike", "remote": "Work from home", "walk": "Walk",
            }.get(x, x),
            key="bgt_commute",
        )
        bgt_movein = b5.selectbox(
            "Move-in terms",
            options=list(MOVE_IN_MULTIPLIERS.keys()),
            format_func=lambda x: {
                "standard":     "1st + last + 1× deposit",
                "deposit_only": "1st month + 1× deposit",
                "first_only":   "1st month only",
                "high":         "1st + last + 2× deposit (SF common)",
            }.get(x, x),
            key="bgt_movein",
            help="Most SF landlords require first + last + deposit. Check your lease.",
        )
        bgt_parking = b6.checkbox("Parking not included — I need a spot", key="bgt_parking")
        bgt_utils   = b6.checkbox("Utilities included in rent", key="bgt_utils")

    # ── Optional context expander ──
    with st.expander("Add more context"):
        ctx1, ctx2 = st.columns(2)
        bgt_income    = ctx1.number_input("Annual gross income ($)", value=0, step=1000, min_value=0, key="bgt_income",
                                           help="Used to calculate how much of your income goes to housing.")
        bgt_savings   = ctx2.number_input("Current savings ($)", value=0, step=500, min_value=0, key="bgt_savings",
                                           help="We'll show whether you can cover move-in costs.")
        bgt_job_loc   = ctx1.text_input("Job / school location", placeholder="e.g. SoMa, Stanford, downtown SJ", key="bgt_job_loc")
        bgt_car       = ctx2.checkbox("I own a car", key="bgt_car",
                                       help="Affects whether you need paid parking.")
        bgt_notes     = st.text_area("Anything else? (pet, storage, gym, etc.)", placeholder="e.g. I have a dog, need in-unit laundry, want a gym nearby", key="bgt_notes", height=80)

    st.button("Calculate budget", type="primary", use_container_width=True, key="bgt_go")

    if st.session_state.get("bgt_go"):
        area_key = bgt_area.lower().strip() if bgt_area in UTILITY_ESTIMATES else "all"
        divisor  = int(bgt_roommates) + 1

        # ── Compute costs ──
        if bgt_utils:
            util_rows  = [("Utilities", 0, "Included in rent")]
            util_total = 0
        else:
            u = UTILITY_ESTIMATES.get(area_key, UTILITY_ESTIMATES["all"])
            util_rows = [
                ("Electricity", round(u["electricity"] / divisor), "avg Bay Area rate"),
                ("Gas",         round(u["gas"] / divisor),         "avg Bay Area rate"),
                ("Internet",    round(u["internet"] / divisor),    "gigabit plan"),
                ("Water",       round(u["water"] / divisor),       "included in some leases"),
            ]
            util_total = sum(r[1] for r in util_rows)

        parking_needed = bgt_parking or (st.session_state.get("bgt_car") and area_key == "sf")
        if parking_needed:
            p            = PARKING_COSTS.get(area_key, PARKING_COSTS["all"])
            parking_cost = round(p["garage"] / divisor)
            parking_note = p["notes"]
        else:
            parking_cost = 0
            parking_note = "Included or not needed"

        c            = COMMUTE_COSTS.get(bgt_commute, COMMUTE_COSTS["bart"])
        commute_cost = round(c["monthly_pass"] / divisor)
        insurance    = round(RENTERS_INSURANCE / divisor)
        monthly_total = bgt_rent + util_total + parking_cost + commute_cost + insurance

        mi           = MOVE_IN_MULTIPLIERS.get(bgt_movein, MOVE_IN_MULTIPLIERS["standard"])
        move_in_cost = bgt_rent * (mi["first"] + mi["last"] + mi["deposit"])
        three_month  = move_in_cost + (monthly_total * 2)

        # ── Top metrics ──
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Total per month",   f"${monthly_total:,}",  delta=f"+${monthly_total - bgt_rent:,} on top of rent", delta_color="off")
        m2.metric("Move-in cash needed", f"${move_in_cost:,}", delta=mi["notes"],                                       delta_color="off")
        m3.metric("Recommended savings", f"${three_month:,}",  delta="move-in + 2 months buffer",                      delta_color="off")

        st.divider()
        col_l, col_r = st.columns([3, 2])

        # ── Monthly breakdown using native dataframe ──
        with col_l:
            st.markdown("#### Monthly breakdown")

            import pandas as pd

            commute_label = {
                "bart": "BART pass", "caltrain": "Caltrain pass", "muni": "Muni pass",
                "driving": "Driving (gas + wear)", "bike": "Bike maintenance",
                "remote": "Commute (WFH)", "walk": "Commute (walk)",
            }.get(bgt_commute, "Commute")

            breakdown_rows = []
            breakdown_rows.append({"Category": "Rent", "Amount": f"${bgt_rent:,}", "Note": ""})

            if bgt_utils:
                breakdown_rows.append({"Category": "Utilities", "Amount": "Included", "Note": "Covered by landlord"})
            else:
                for name, cost, note in util_rows:
                    breakdown_rows.append({"Category": f"   · {name}", "Amount": f"${cost:,}", "Note": note})

            breakdown_rows.append({
                "Category": "Parking",
                "Amount": f"${parking_cost:,}" if parking_cost else "Included",
                "Note": parking_note,
            })
            breakdown_rows.append({
                "Category": f"{commute_label}",
                "Amount": f"${commute_cost:,}" if commute_cost else "Free",
                "Note": c["notes"],
            })
            breakdown_rows.append({"Category": "Renter's insurance", "Amount": f"${insurance:,}", "Note": "CA average, highly recommended"})
            breakdown_rows.append({"Category": "Total", "Amount": f"**${monthly_total:,}**", "Note": f"per month{' · split ' + str(divisor) + ' ways' if bgt_roommates else ''}"})

            df = pd.DataFrame(breakdown_rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         column_config={
                             "Category": st.column_config.TextColumn("Category", width="medium"),
                             "Amount":   st.column_config.TextColumn("Cost / mo", width="small"),
                             "Note":     st.column_config.TextColumn("Details",   width="large"),
                         })

        # ── Right column ──
        with col_r:
            st.markdown("#### Move-in costs")
            mi_rows = []
            if mi["first"]:   mi_rows.append({"Item": "First month's rent",  "Amount": f"${bgt_rent:,}"})
            if mi["last"]:    mi_rows.append({"Item": "Last month's rent",   "Amount": f"${bgt_rent:,}"})
            if mi["deposit"]: mi_rows.append({"Item": f"Security deposit ({mi['deposit']}×)", "Amount": f"${bgt_rent * mi['deposit']:,}"})
            mi_rows.append({"Item": "**Total due at signing**", "Amount": f"**${move_in_cost:,}**"})
            st.dataframe(pd.DataFrame(mi_rows), use_container_width=True, hide_index=True,
                         column_config={
                             "Item":   st.column_config.TextColumn("Item",   width="medium"),
                             "Amount": st.column_config.TextColumn("Amount", width="small"),
                         })

            st.markdown("#### Affordability")
            recommended_income = monthly_total * 3
            pct_of_income = None
            if st.session_state.get("bgt_income", 0) > 0:
                monthly_income = st.session_state["bgt_income"] / 12
                pct_of_income  = round((monthly_total / monthly_income) * 100)

            if pct_of_income is not None:
                color = "+" if pct_of_income <= 30 else ("~" if pct_of_income <= 40 else "!")
                st.info(f"**{pct_of_income}% of your gross income** goes to total housing costs.\n\n"
                        f"{'Under the 30% guideline — looks affordable.' if pct_of_income <= 30 else ('Above 30% — tight but common in the Bay Area.' if pct_of_income <= 40 else 'Above 40% — consider a lower rent or more roommates.')}")
            else:
                st.info(f"At the **30% rule**, you'd need **${recommended_income:,}/mo** gross income "
                        f"(~**${recommended_income * 12:,}/yr**) to comfortably afford this.\n\n"
                        f"Add your income above for a personalised check.")

            # Savings check
            savings = st.session_state.get("bgt_savings", 0)
            if savings > 0:
                st.markdown("#### Savings check")
                if savings >= three_month:
                    st.success(f"Your savings (${savings:,}) cover move-in + 2 months buffer (${three_month:,}).")
                elif savings >= move_in_cost:
                    shortfall = three_month - savings
                    st.warning(f"You can cover move-in (${move_in_cost:,}) but are ${shortfall:,} short of a 2-month buffer.")
                else:
                    shortfall = move_in_cost - savings
                    st.error(f"You're ${shortfall:,} short of the move-in cost alone (${move_in_cost:,}).")

            # Extra context notes
            notes = st.session_state.get("bgt_notes", "")
            job   = st.session_state.get("bgt_job_loc", "")
            if notes or job:
                st.markdown("#### Your notes")
                if job:
                    st.markdown(f"**Job / school:** {job}")
                if notes:
                    st.markdown(f"{notes}")
