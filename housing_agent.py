import argparse
import re
import boto3

from strands import Agent
from strands.models.bedrock import BedrockModel

from listing_tools import search_listings, get_listing_details, _fetch_rss, AREA_CODES
from filter_tools import filter_listings
from favorites_tools import save_favorite, view_favorites, remove_favorite

# Global cache: maps lowercase title fragment -> full URL
_listing_url_cache: dict[str, str] = {}


def _populate_cache(area: str = "all", max_price: int = 5000) -> None:
    """Pre-fetch listings and store title->URL mappings."""
    import urllib.parse
    area_key = area.lower().strip()
    area_code = AREA_CODES.get(area_key)
    base = "https://sfbay.craigslist.org"
    params = {"format": "rss", "max_price": max_price, "min_price": 0}
    search_path = f"/{area_code}/apa" if area_code else "/search/apa"
    url = f"{base}{search_path}?{urllib.parse.urlencode(params)}"
    for listing in _fetch_rss(url):
        if listing["title"] and listing["link"]:
            _listing_url_cache[listing["title"].lower()] = listing["link"]


def _inject_links(text: str) -> str:
    """
    Scan the response for listing titles that are in the cache but have no
    adjacent URL, and append the link inline.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        result.append(line)
        # If this line already contains a craigslist URL, leave it alone
        if "craigslist.org" in line:
            continue
        # Check if any cached title appears in this line
        line_lower = line.lower()
        for title, url in _listing_url_cache.items():
            # Match on a meaningful chunk of the title (first 30 chars)
            key = title[:30]
            if key and key in line_lower:
                result.append(f"   🔗 {url}")
                break
    return "\n".join(result)

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

2. Use filter_listings to narrow results if the user has specific requirements like:
   - Furnished / unfurnished
   - Utilities included
   - Pet-friendly
   - Roommate situations
   - Specific neighborhoods

3. For listings that look promising, use get_listing_details to read the full description
   before recommending them. Look for:
   - Accurate pricing and what's included
   - Lease terms (month-to-month vs. 12-month)
   - Move-in date
   - Any red flags (vague descriptions, no photos mentioned, unusually low price)

## Presenting Results

Group results clearly:
- **Top Picks** — Best matches for the user's stated requirements
- **Worth Considering** — Good options with minor trade-offs
- **Heads Up** — Listings that need more info or have potential issues

For each listing, always use this exact format — do not skip any field:

**[Title]**
- Price: $X,XXX/mo
- Area: [neighborhood]
- Features: [key details]
- Notes: [why it matches or doesn't]
- Link: [full URL from the search results, e.g. https://sfbay.craigslist.org/eby/apa/...]

The link field is mandatory. Copy it exactly from the "URL (MUST include in response)" field
in the tool output. Never omit, shorten, or paraphrase the URL.

## Saving Favorites

When the user wants to save a listing, use save_favorite with the title, URL, price,
neighborhood, and any notes. Use view_favorites to show their saved list.
Use remove_favorite if they want to remove one.

## Post-Grad Context

Keep in mind users are likely:
- Recent grads or grad students at Bay Area universities (Stanford, Berkeley, UCSF, etc.)
- Starting a new job in tech, biotech, or finance
- Looking for roommate situations or smaller units to keep costs down
- Unfamiliar with Bay Area neighborhoods — offer brief context on areas when helpful
- Concerned about commute to major tech corridors (SoMa, FiDi, South Bay tech campuses)

## Red Flags to Call Out

- Price significantly below market (possible scam)
- No photos or very vague description
- Requests for wire transfer or unusual payment methods
- "First come first served" pressure tactics
- Listings reposted many times in a short period
"""

DEFAULT_PROMPT = (
    "I'm a recent grad looking for housing in the Bay Area. "
    "My budget is $2,500/month. Can you show me what's available?"
)


def main():
    parser = argparse.ArgumentParser(description="Bay Area Housing Finder Agent")
    parser.add_argument(
        "prompt",
        nargs="?",
        default=DEFAULT_PROMPT,
        help="Describe what you're looking for (default: general search at $2,500/mo)",
    )
    args = parser.parse_args()

    # Use SSO profile if available, otherwise fall back to default credentials
    profile = "GSB570-BedrockOnly-490332585640"
    session = boto3.Session(profile_name=profile)
    boto3_client = session.client("bedrock-runtime", region_name="us-west-2")

    model = BedrockModel(
        model_id="us.amazon.nova-pro-v1:0",
        max_tokens=4096,
        boto_session=session,
    )

    agent = Agent(
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

    print("Bay Area Housing Finder Agent")
    print("=" * 50)
    print(f"Looking for: {args.prompt}\n")

    # Pre-populate the URL cache so we can inject links into the final response
    _populate_cache(area="all", max_price=5000)

    response = agent(args.prompt)
    final = _inject_links(str(response))
    print(final)


if __name__ == "__main__":
    main()

