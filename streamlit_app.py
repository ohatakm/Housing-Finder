"""
Bay Area Housing Finder — Streamlit UI
Run with: streamlit run streamlit_app.py
"""

import re
import threading
import urllib.parse

import boto3
import streamlit as st

from listing_tools import _fetch_rss, AREA_CODES, AREA_ZIPS, search_listings, get_listing_details
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
find rental housing. You search Craigslist Bay Area listings and help users find the best options.

When a user describes what they're looking for use search_listings, then filter_listings if needed,
then get_listing_details for promising ones.

For EVERY listing always include:
- Title, Price, Neighborhood, Key features, Why it matches
- The full Craigslist URL (never omit it)

Use save_favorite / view_favorites / remove_favorite when asked.
"""

SORT_OPTIONS = [
    "Default (RSS order)",
    "Price: Low to High",
    "Price: High to Low",
    "Newest First",
    "Oldest First",
    "Neighborhood A–Z",
    "Title A–Z",
]

AREAS = ["all", "sf", "south bay", "east bay", "peninsula", "north bay"]

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Bay Area Housing Finder",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 Bay Area Housing Finder")
st.caption("AI-powered rental search for post-grads and young professionals.")

# ── Session state init ───────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent" not in st.session_state:
    st.session_state.agent = None

if "qs_listings" not in st.session_state:
    st.session_state.qs_listings = []

if "br_listings" not in st.session_state:
    st.session_state.br_listings = []

# ── Helpers ──────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Connecting to AWS…")
def get_agent() -> Agent:
    session = boto3.Session(profile_name=PROFILE)
    model = BedrockModel(
        model_id=MODEL_ID,
        max_tokens=4096,
        boto_session=session,
    )
    return Agent(
        model=model,
        tools=[
            search_listings,
            get_listing_details,
            filter_listings,
            save_favorite,
            view_favorites,
            remove_favorite,
        ],
        system_prompt=SYSTEM_PROMPT,
    )


def fetch_listings(area, max_price, min_price, bedrooms, keyword) -> list[dict]:
    zip_code, distance = AREA_ZIPS.get(area.lower().strip(), (None, None))
    base = "https://sfbay.craigslist.org"
    params = {"max_price": int(max_price), "min_price": int(min_price)}
    if zip_code:
        params["postal"] = zip_code
        params["search_distance"] = distance
    if bedrooms != "any":
        params["min_bedrooms"] = bedrooms
        params["max_bedrooms"] = bedrooms
    if keyword:
        params["query"] = keyword
    url = f"{base}/search/apa?{urllib.parse.urlencode(params)}"
    return _fetch_rss(url)


def sort_listings(listings: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "Price: Low to High":
        return sorted(listings, key=lambda l: l["price"] or 999999)
    if sort_by == "Price: High to Low":
        return sorted(listings, key=lambda l: l["price"] or 0, reverse=True)
    if sort_by == "Newest First":
        return sorted(listings, key=lambda l: l["pub_date"], reverse=True)
    if sort_by == "Oldest First":
        return sorted(listings, key=lambda l: l["pub_date"])
    if sort_by == "Neighborhood A–Z":
        return sorted(listings, key=lambda l: (l["neighborhood"] or "").lower())
    if sort_by == "Title A–Z":
        return sorted(listings, key=lambda l: l["title"].lower())
    return listings


def render_listing_cards(listings: list[dict], sort_by: str):
    listings = sort_listings(listings, sort_by)
    st.caption(f"**{len(listings)}** listings · sorted by *{sort_by}*")
    for l in listings:
        hood  = l["neighborhood"] or "Bay Area"
        price = l["price_raw"] if l["price_raw"] != "N/A" else "Price N/A"
        desc  = l["description"][:220] + "…" if l["description"] else ""
        date  = l["pub_date"][:16] if l["pub_date"] else ""

        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{l['title']}**")
                st.caption(f"📍 {hood} · 🗓 {date}")
            with col2:
                st.markdown(
                    f"<div style='text-align:right; color:#2d7a2d; font-weight:700; font-size:1.1em;'>"
                    f"{price}/mo</div>",
                    unsafe_allow_html=True,
                )
            if desc:
                st.write(desc)
            st.link_button("🔗 View on Craigslist", l["link"], use_container_width=False)


# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_chat, tab_browse, tab_search, tab_favs = st.tabs([
    "💬 Chat with Agent",
    "📋 Browse All Listings",
    "🔍 Quick Search",
    "❤️ Favorites",
])

# ── Tab 1: Chat ───────────────────────────────────────────────────────────────

with tab_chat:
    # Render history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Example prompts (only shown when chat is empty)
    if not st.session_state.messages:
        st.markdown("**Try asking:**")
        examples = [
            "I'm a recent grad, budget $2,500/mo. What's available in SF?",
            "Show me furnished studios in the South Bay under $2,000",
            "Find pet-friendly 1BRs in Oakland or Berkeley under $2,400",
            "I need a roommate situation in the Peninsula, max $1,500",
        ]
        cols = st.columns(2)
        for i, ex in enumerate(examples):
            if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
                st.session_state._prefill = ex
                st.rerun()

    # Handle prefilled example
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
                    # Strip Nova Pro <thinking>...</thinking> blocks
                    response = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
                except Exception as e:
                    response = f"❌ Error: {e}"
            st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})

    if st.session_state.messages:
        if st.button("🗑 Clear chat", key="clear_chat"):
            st.session_state.messages = []
            st.rerun()

# ── Tab 2: Browse All Listings ────────────────────────────────────────────────

with tab_browse:
    st.subheader("Browse Live Listings")

    c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 2])
    br_area    = c1.selectbox("Area", AREAS, key="br_area")
    br_min     = c2.number_input("Min $", value=0, step=100, key="br_min")
    br_max     = c3.number_input("Max $", value=3500, step=100, key="br_max")
    br_beds    = c4.selectbox("Beds", ["any", "0", "1", "2", "3", "4"], key="br_beds")
    br_keyword = c5.text_input("Keyword", placeholder="furnished, roommate…", key="br_kw")

    col_sort, col_btn = st.columns([3, 1])
    br_sort = col_sort.selectbox("Sort by", SORT_OPTIONS, index=1, key="br_sort")
    load    = col_btn.button("Load Listings", type="primary", use_container_width=True, key="br_load")

    if load:
        with st.spinner("Fetching listings…"):
            try:
                st.session_state.br_listings = fetch_listings(
                    br_area, br_max, br_min, br_beds, br_keyword
                )
            except Exception as e:
                st.error(f"Error fetching listings: {e}")

    if st.session_state.br_listings:
        try:
            render_listing_cards(st.session_state.br_listings, br_sort)
        except Exception as e:
            st.error(f"Error rendering listings: {e}")
            st.write(st.session_state.br_listings[:2])  # show raw data for debugging
    else:
        st.info("Set your filters and click **Load Listings**.")

# ── Tab 3: Quick Search ───────────────────────────────────────────────────────

with tab_search:
    st.subheader("Quick Search")

    q1, q2, q3, q4 = st.columns([2, 2, 1, 2])
    qs_area    = q1.selectbox("Area", AREAS, key="qs_area")
    qs_max     = q2.slider("Max price ($/mo)", 500, 6000, 2500, 100, key="qs_max")
    qs_beds    = q3.selectbox("Beds", ["any", "0", "1", "2", "3", "4"], key="qs_beds")
    qs_keyword = q4.text_input("Keyword", placeholder="furnished, roommate…", key="qs_kw")

    col_sort2, col_btn2 = st.columns([3, 1])
    qs_sort  = col_sort2.selectbox("Sort by", SORT_OPTIONS, key="qs_sort")
    qs_go    = col_btn2.button("Search", type="primary", use_container_width=True, key="qs_go")

    if qs_go:
        with st.spinner("Fetching listings…"):
            try:
                st.session_state.qs_listings = fetch_listings(
                    qs_area, qs_max, 0, qs_beds, qs_keyword
                )
            except Exception as e:
                st.error(f"Error fetching listings: {e}")

    if st.session_state.qs_listings:
        try:
            render_listing_cards(st.session_state.qs_listings, qs_sort)
        except Exception as e:
            st.error(f"Error rendering: {e}")
            st.write(st.session_state.qs_listings[:2])
    else:
        st.info("Set your filters and click **Search**.")

# ── Tab 4: Favorites ──────────────────────────────────────────────────────────

with tab_favs:
    st.subheader("Saved Favorites")

    favs = _load_favorites()
    if not favs:
        st.info("No saved favorites yet. Ask the agent to save a listing!")
    else:
        st.caption(f"{len(favs)} saved listing(s)")
        for f in favs:
            with st.container(border=True):
                col_a, col_b = st.columns([5, 1])
                with col_a:
                    st.markdown(f"**{f['title']}**")
                    st.caption(
                        f"💰 {f['price']} · 📍 {f['neighborhood']} · 🗓 {f['saved_at']}"
                    )
                    if f.get("notes"):
                        st.write(f"📝 {f['notes']}")
                    st.link_button("🔗 View listing", f["url"])
                with col_b:
                    if st.button("Remove", key=f"rm_{f['url']}", type="secondary"):
                        remove_favorite(f["url"])
                        st.rerun()

    if st.button("🔄 Refresh", key="refresh_favs"):
        st.rerun()
