"""
Bay Area Housing Finder — Gradio Web UI
Run with: python app.py
"""

import json
import os
import re
import threading
import boto3
import gradio as gr

from strands import Agent
from strands.models.bedrock import BedrockModel

from listing_tools import search_listings, get_listing_details, _fetch_rss, AREA_CODES
from filter_tools import filter_listings
from favorites_tools import (
    save_favorite,
    view_favorites,
    remove_favorite,
    _load_favorites,
    FAVORITES_FILE,
)

# ---------------------------------------------------------------------------
# AWS / Agent — initialized once at startup, not per-request
# ---------------------------------------------------------------------------

PROFILE = "GSB570-BedrockOnly-490332585640"
MODEL_ID = "us.amazon.nova-pro-v1:0"

_agent: Agent | None = None
_agent_lock = threading.Lock()


def _get_agent() -> Agent:
    global _agent
    with _agent_lock:
        if _agent is None:
            session = boto3.Session(profile_name=PROFILE)
            model = BedrockModel(
                model_id=MODEL_ID,
                max_tokens=4096,
                boto_session=session,
            )
            _agent = Agent(
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
    return _agent


# ---------------------------------------------------------------------------
# URL cache — populated on first search so links are always injected
# ---------------------------------------------------------------------------

_url_cache: dict[str, str] = {}  # lowercase title[:40] -> full URL
_cache_lock = threading.Lock()


def _refresh_cache(area: str = "all", max_price: int = 6000) -> None:
    import urllib.parse
    area_code = AREA_CODES.get(area.lower().strip())
    base = "https://sfbay.craigslist.org"
    params = {"format": "rss", "max_price": max_price, "min_price": 0}
    path = f"/{area_code}/apa" if area_code else "/search/apa"
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    listings = _fetch_rss(url)
    with _cache_lock:
        for l in listings:
            if l["title"] and l["link"]:
                _url_cache[l["title"].lower()[:40]] = l["link"]


def _inject_links(text: str) -> str:
    """Append any missing Craigslist URLs next to matching listing titles."""
    lines = text.split("\n")
    out = []
    for line in lines:
        out.append(line)
        if "craigslist.org" in line:
            continue
        line_lower = line.lower()
        with _cache_lock:
            for key, url in _url_cache.items():
                if key and key in line_lower:
                    out.append(f"🔗 {url}")
                    break
    return "\n".join(out)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Bay Area housing assistant helping post-grads and young professionals
find rental housing that fits their needs. You search Craigslist Bay Area listings and help
users find the best options based on their requirements.

## Finding Listings

When a user describes what they're looking for:

1. Use search_listings to fetch live listings. Choose the right area:
   - "sf" for San Francisco
   - "south bay" for San Jose, Sunnyvale, Mountain View, Palo Alto, Santa Clara
   - "east bay" for Oakland, Berkeley, Fremont, Hayward
   - "peninsula" for Daly City, Redwood City, San Mateo, Burlingame
   - "north bay" for Marin, Sonoma, Napa
   - "all" if the user is flexible on location

2. Use filter_listings to narrow results if the user has specific requirements.

3. For promising listings, use get_listing_details before recommending them.

## Presenting Results

Group results as: **Top Picks**, **Worth Considering**, **Heads Up**.

For EVERY listing include this exact block — never skip the Link line:

**[Title]**
- Price: $X,XXX/mo
- Area: [neighborhood]
- Features: [bedrooms, furnished, pets, etc.]
- Notes: [why it matches]
- Link: [full https://sfbay.craigslist.org/... URL]

## Saving Favorites

Use save_favorite / view_favorites / remove_favorite when asked.

## Red Flags
- Price far below market
- No photos / vague description
- Wire transfer requests
- Heavy pressure tactics
"""

# ---------------------------------------------------------------------------
# Chat handler — runs in its own thread, never blocks other tabs
# ---------------------------------------------------------------------------

def _chat(message: str, history: list) -> tuple:
    """Send a message to the agent and return updated history."""
    try:
        agent = _get_agent()
        raw = str(agent(message))
        response = _inject_links(raw)
    except Exception as e:
        response = f"❌ Error: {e}"

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response},
    ]
    return history, ""


# ---------------------------------------------------------------------------
# Favorites helpers
# ---------------------------------------------------------------------------

def _get_favorites_html() -> str:
    favs = _load_favorites()
    if not favs:
        return "<p style='color:#888'>No saved favorites yet. Ask the agent to save a listing!</p>"
    rows = ""
    for f in favs:
        rows += f"""
        <div style='border:1px solid #e0e0e0; border-radius:8px; padding:12px; margin-bottom:10px;'>
            <strong>{f['title']}</strong><br>
            💰 {f['price']} &nbsp;|&nbsp; 📍 {f['neighborhood']}<br>
            🗓 Saved: {f['saved_at']}<br>
            {f'📝 {f["notes"]}<br>' if f.get("notes") else ""}
            <a href='{f['url']}' target='_blank'>🔗 View listing</a>
        </div>"""
    return rows


def _remove_fav(url: str) -> tuple:
    if not url.strip():
        return "Please enter a URL to remove.", _get_favorites_html()
    msg = remove_favorite(url.strip())
    return msg, _get_favorites_html()


# ---------------------------------------------------------------------------
# Shared listing fetcher + renderer
# ---------------------------------------------------------------------------

def _fetch_listings(
    area: str,
    max_price: int,
    min_price: int,
    bedrooms: str,
    keyword: str,
) -> list[dict]:
    import urllib.parse
    area_code = AREA_CODES.get(area.lower().strip())
    base = "https://sfbay.craigslist.org"
    params = {"format": "rss", "max_price": max_price, "min_price": min_price}
    if bedrooms != "any":
        params["min_bedrooms"] = bedrooms
        params["max_bedrooms"] = bedrooms
    if keyword:
        params["query"] = keyword
    path = f"/{area_code}/apa" if area_code else "/search/apa"
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    listings = _fetch_rss(url)
    with _cache_lock:
        for l in listings:
            if l["title"] and l["link"]:
                _url_cache[l["title"].lower()[:40]] = l["link"]
    return listings


def _sort_listings(listings: list[dict], sort_by: str) -> list[dict]:
    if sort_by == "Price: Low to High":
        return sorted(listings, key=lambda l: l["price"] or 999999)
    elif sort_by == "Price: High to Low":
        return sorted(listings, key=lambda l: l["price"] or 0, reverse=True)
    elif sort_by == "Newest First":
        return sorted(listings, key=lambda l: l["pub_date"], reverse=True)
    elif sort_by == "Oldest First":
        return sorted(listings, key=lambda l: l["pub_date"])
    elif sort_by == "Neighborhood A–Z":
        return sorted(listings, key=lambda l: l["neighborhood"].lower())
    elif sort_by == "Title A–Z":
        return sorted(listings, key=lambda l: l["title"].lower())
    return listings  # "Default" — RSS order


def _render_listings_html(listings: list[dict], sort_by: str) -> str:
    if not listings:
        return "<p style='color:#888; padding:20px;'>No listings found. Try broadening your filters.</p>"

    listings = _sort_listings(listings, sort_by)

    cards = ""
    for l in listings:
        hood = l["neighborhood"] or "Bay Area"
        price = l["price_raw"] if l["price_raw"] != "N/A" else "Price N/A"
        price_color = "#2d7a2d"
        desc = l["description"][:200] + "…" if l["description"] else "No description available."
        date_str = l["pub_date"][:16] if l["pub_date"] else ""

        cards += f"""
        <div style='
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 12px;
            background: #ffffff;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            transition: box-shadow 0.2s;
        '>
            <div style='display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:6px;'>
                <strong style='font-size:1em; color:#1a1a1a;'>{l['title']}</strong>
                <span style='color:{price_color}; font-weight:700; font-size:1em; white-space:nowrap;'>{price}/mo</span>
            </div>
            <div style='margin:4px 0 8px; font-size:0.85em; color:#666;'>
                📍 {hood} &nbsp;·&nbsp; 🗓 {date_str}
            </div>
            <p style='margin:0 0 10px; font-size:0.88em; color:#444; line-height:1.5;'>{desc}</p>
            <a href='{l['link']}' target='_blank'
               style='display:inline-block; padding:5px 14px; background:#1a73e8; color:#fff;
                      border-radius:6px; text-decoration:none; font-size:0.85em; font-weight:500;'>
                🔗 View on Craigslist
            </a>
        </div>"""

    header = f"""
    <div style='padding:8px 0 14px; font-size:0.95em; color:#555;'>
        <strong>{len(listings)}</strong> listings found · sorted by <em>{sort_by}</em>
    </div>"""
    return header + cards


# ---------------------------------------------------------------------------
# Quick-search handler (used by Quick Search tab)
# ---------------------------------------------------------------------------

def _quick_search(area: str, max_price: int, bedrooms: str, keyword: str, sort_by: str) -> tuple:
    listings = _fetch_listings(area, max_price, 0, bedrooms, keyword)
    return _render_listings_html(listings, sort_by), listings


def _quick_sort(sort_by: str, listings: list) -> str:
    if not listings:
        return "<p style='color:#888; padding:20px;'>Run a search first.</p>"
    return _render_listings_html(listings, sort_by)


# ---------------------------------------------------------------------------
# Browse All handler
# ---------------------------------------------------------------------------

def _browse_all(area: str, max_price: int, min_price: int, bedrooms: str, keyword: str, sort_by: str) -> tuple:
    listings = _fetch_listings(area, max_price, min_price, bedrooms, keyword)
    return _render_listings_html(listings, sort_by), listings


def _browse_sort(sort_by: str, listings: list) -> str:
    if not listings:
        return "<p style='color:#888; padding:20px;'>Load listings first.</p>"
    return _render_listings_html(listings, sort_by)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

with gr.Blocks(
    title="Bay Area Housing Finder",
) as demo:

    agent_state = gr.State({"agent": None})  # kept for compat, unused
    qs_listings_state = gr.State([])
    br_listings_state = gr.State([])

    gr.Markdown(
        """
        # 🏠 Bay Area Housing Finder
        AI-powered rental search for post-grads and young professionals.
        Chat with the agent or use Quick Search to browse live Craigslist listings.
        """
    )

    with gr.Tabs():

        # ── Tab 1: Chat ──────────────────────────────────────────────────────
        with gr.Tab("💬 Chat with Agent"):
            chatbot = gr.Chatbot(
                elem_id="chatbot",
                label="Housing Agent",
                buttons=["copy_all"],
                render_markdown=True,
                height=520,
                resizable=True,
            )
            with gr.Row():
                msg_box = gr.Textbox(
                    placeholder="e.g. I need a 1BR in the East Bay under $2,200, pet-friendly...",
                    label="Your message",
                    scale=5,
                    lines=2,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1, min_width=80)

            with gr.Row():
                gr.Examples(
                    examples=[
                        ["I'm a recent grad, budget $2,500/mo. What's available in SF?"],
                        ["Show me furnished studios in the South Bay under $2,000"],
                        ["Find pet-friendly 1BRs in Oakland or Berkeley under $2,400"],
                        ["I need a roommate situation in the Peninsula, max $1,500"],
                        ["Show my saved favorites"],
                    ],
                    inputs=msg_box,
                    label="Example prompts",
                )

            send_btn.click(
                _chat,
                inputs=[msg_box, chatbot],
                outputs=[chatbot, msg_box],
                concurrency_limit=1,
            )
            msg_box.submit(
                _chat,
                inputs=[msg_box, chatbot],
                outputs=[chatbot, msg_box],
                concurrency_limit=1,
            )

        # ── Tab 2: Quick Search ──────────────────────────────────────────────
        with gr.Tab("🔍 Quick Search"):
            gr.Markdown("Browse raw listings directly — no AI, just live Craigslist results.")
            with gr.Row():
                qs_area = gr.Dropdown(
                    choices=["all", "sf", "south bay", "east bay", "peninsula", "north bay"],
                    value="all",
                    label="Area",
                )
                qs_price = gr.Slider(
                    minimum=500, maximum=6000, value=2500, step=100,
                    label="Max price ($/mo)",
                )
                qs_beds = gr.Dropdown(
                    choices=["any", "0", "1", "2", "3", "4"],
                    value="any",
                    label="Bedrooms",
                )
                qs_keyword = gr.Textbox(label="Keyword (optional)", placeholder="furnished, roommate…")

            with gr.Row():
                qs_sort = gr.Dropdown(
                    choices=["Default", "Price: Low to High", "Price: High to Low",
                             "Newest First", "Oldest First", "Neighborhood A–Z", "Title A–Z"],
                    value="Default",
                    label="Sort by",
                    scale=2,
                )
                qs_btn = gr.Button("Search Listings", variant="primary", scale=1)

            qs_results = gr.HTML(label="Results")

            qs_btn.click(
                _quick_search,
                inputs=[qs_area, qs_price, qs_beds, qs_keyword, qs_sort],
                outputs=[qs_results, qs_listings_state],
                concurrency_limit=None,
            )
            # Re-sort from cached state — no network call
            qs_sort.change(
                _quick_sort,
                inputs=[qs_sort, qs_listings_state],
                outputs=qs_results,
                concurrency_limit=None,
            )

        # ── Tab 3: Browse All ────────────────────────────────────────────────
        with gr.Tab("📋 Browse All Listings"):
            gr.Markdown("Load a large set of live listings across the Bay Area with full filtering and sorting.")
            with gr.Row():
                br_area = gr.Dropdown(
                    choices=["all", "sf", "south bay", "east bay", "peninsula", "north bay"],
                    value="all",
                    label="Area",
                    scale=1,
                )
                br_min_price = gr.Number(value=0, label="Min price ($)", precision=0, scale=1)
                br_max_price = gr.Number(value=3500, label="Max price ($)", precision=0, scale=1)
                br_beds = gr.Dropdown(
                    choices=["any", "0", "1", "2", "3", "4"],
                    value="any",
                    label="Bedrooms",
                    scale=1,
                )
                br_keyword = gr.Textbox(
                    label="Keyword",
                    placeholder="furnished, utilities, roommate…",
                    scale=2,
                )

            with gr.Row():
                br_sort = gr.Dropdown(
                    choices=["Default", "Price: Low to High", "Price: High to Low",
                             "Newest First", "Oldest First", "Neighborhood A–Z", "Title A–Z"],
                    value="Price: Low to High",
                    label="Sort by",
                    scale=2,
                )
                br_btn = gr.Button("Load Listings", variant="primary", scale=1)

            br_results = gr.HTML(
                value="<p style='color:#888; padding:20px;'>Set your filters and click Load Listings.</p>"
            )

            br_btn.click(
                _browse_all,
                inputs=[br_area, br_max_price, br_min_price, br_beds, br_keyword, br_sort],
                outputs=[br_results, br_listings_state],
                concurrency_limit=None,
            )
            # Re-sort from cached state — no network call
            br_sort.change(
                _browse_sort,
                inputs=[br_sort, br_listings_state],
                outputs=br_results,
                concurrency_limit=None,
            )

        # ── Tab 4: Favorites ─────────────────────────────────────────────────
        with gr.Tab("❤️ Favorites"):
            gr.Markdown("Listings saved by the agent. Ask the agent to *save* any listing you like.")
            refresh_btn = gr.Button("Refresh", variant="secondary")
            favs_html = gr.HTML(value="<p style='color:#888'>Click Refresh to load your saved favorites.</p>")

            with gr.Row():
                remove_url = gr.Textbox(
                    label="Remove by URL",
                    placeholder="https://sfbay.craigslist.org/...",
                    scale=4,
                )
                remove_btn = gr.Button("Remove", variant="stop", scale=1)

            remove_msg = gr.Textbox(label="", interactive=False, visible=True)

            refresh_btn.click(lambda: _get_favorites_html(), outputs=favs_html, concurrency_limit=None)
            remove_btn.click(
                _remove_fav,
                inputs=remove_url,
                outputs=[remove_msg, favs_html],
                concurrency_limit=None,
            )

    gr.Markdown(
        "<p style='text-align:center; color:#aaa; font-size:0.8em;'>"
        "Live data from Craigslist Bay Area · Prices and availability change frequently"
        "</p>"
    )

if __name__ == "__main__":
    # Warm up the agent in the background so first chat is instant
    threading.Thread(target=_get_agent, daemon=True).start()

    demo.queue(default_concurrency_limit=None)
    demo.launch(
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="blue"),
        css="""
        .tab-nav button { font-size: 15px; }
        footer { display: none !important; }
        """,
        max_threads=20,
    )
