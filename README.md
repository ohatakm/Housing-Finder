# Bay Area Housing Finder Agent

An AI-powered housing search assistant built with [Strands Agents SDK](https://strandsagents.com/) that searches live Craigslist Bay Area listings and helps post-grads and young professionals find rentals that match their needs.

## What It Does

The agent takes your requirements in plain English and handles the full search workflow:

1. **Searches live listings** from Craigslist Bay Area RSS feeds — no account or API key needed
2. **Filters by your criteria** — price, bedrooms, furnished, pets, neighborhood, keywords
3. **Reads full listing details** for promising results to surface what's actually included
4. **Flags red flags** — suspiciously low prices, vague descriptions, scam patterns
5. **Saves favorites** to a local `favorites.json` file for later review

Results are grouped into **Top Picks**, **Worth Considering**, and **Heads Up** so you know where to focus.

## Architecture

```
housing_agent.py          -- Entry point, CLI arg parsing, agent configuration
    |
    |-- Agent (Strands SDK)
    |     |-- Model: Claude via Amazon Bedrock
    |     |-- System Prompt: search + filter + post-grad context instructions
    |     |-- Tools:
    |           |-- search_listings       (listing_tools.py)
    |           |-- get_listing_details   (listing_tools.py)
    |           |-- filter_listings       (filter_tools.py)
    |           |-- save_favorite         (favorites_tools.py)
    |           |-- view_favorites        (favorites_tools.py)
    |           |-- remove_favorite       (favorites_tools.py)
```

## Tools

### Listing Tools (`listing_tools.py`)

| Tool | Description |
|------|-------------|
| `search_listings` | Fetches live listings from Craigslist Bay Area RSS feeds filtered by area, price range, bedrooms, and keyword. Returns up to 25 listings with title, price, neighborhood, and snippet. |
| `get_listing_details` | Fetches the full description of a specific listing by URL. Used when the agent needs more context to evaluate a listing. |

### Filter Tools (`filter_tools.py`)

| Tool | Description |
|------|-------------|
| `filter_listings` | Narrows down a set of listings by required/excluded keywords, price cap, or neighborhood. Operates on the text output of `search_listings`. |

### Favorites Tools (`favorites_tools.py`)

| Tool | Description |
|------|-------------|
| `save_favorite` | Saves a listing to `favorites.json` with title, URL, price, neighborhood, and optional notes. |
| `view_favorites` | Displays all saved favorites from `favorites.json`. |
| `remove_favorite` | Removes a listing from favorites by URL. |

## Usage

```bash
# Default: general search at $2,500/mo
python housing_agent.py

# Specific requirements
python housing_agent.py "Looking for a furnished 1BR in the South Bay near Caltrain, max $2,800/mo, cats ok"

# Roommate search
python housing_agent.py "I need a room in a shared house in Berkeley or Oakland, budget $1,400/mo"

# View saved favorites
python housing_agent.py "Show me my saved favorites"

# Broader search
python housing_agent.py "What's available in SF under $3,000 that allows pets?"
```

## Prerequisites

- **Python 3.10+**
- **AWS credentials** configured with access to Amazon Bedrock (Claude model)

No Google credentials, no API keys, no OAuth. Craigslist RSS feeds are public.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure AWS credentials (if not already done)
aws configure

# Run
python housing_agent.py
```

## Project Structure

```
.
├── housing_agent.py      # Main entry point and agent configuration
├── listing_tools.py      # @tool functions for Craigslist search and detail fetching
├── filter_tools.py       # @tool function for filtering listing results
├── favorites_tools.py    # @tool functions for saving/viewing/removing favorites
├── requirements.txt      # Python dependencies
├── README.md             # This file
└── favorites.json        # Auto-generated when you save a favorite (gitignored)
```

## Security & Privacy

- **No authentication required** — only reads public Craigslist RSS feeds and listing pages
- **No data sent externally** — all processing happens locally via Bedrock
- **Favorites stored locally** — `favorites.json` stays on your machine
- **No accounts touched** — the agent cannot post, contact landlords, or submit any forms
