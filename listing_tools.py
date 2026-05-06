import re
import json
import urllib.request
import urllib.parse
from datetime import datetime

from strands import tool


AREA_CODES = {
    "sf": "sfc",
    "south bay": "sby",
    "east bay": "eby",
    "peninsula": "pen",
    "north bay": "nby",
    "all": None,
}

# Zip codes for area filtering (replaces broken subregion URLs)
AREA_ZIPS = {
    "sf":         ("94102", 15),   # SF civic center, 15mi radius
    "south bay":  ("95101", 20),   # San Jose, 20mi radius
    "east bay":   ("94612", 20),   # Oakland, 20mi radius
    "peninsula":  ("94401", 15),   # San Mateo, 15mi radius
    "north bay":  ("94901", 20),   # San Rafael, 20mi radius
    "all":        (None, None),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_rss(url: str) -> list[dict]:
    """Scrape Craigslist search results page, returning a list of listing dicts.
    (Named _fetch_rss for backwards compatibility — now scrapes HTML.)
    """
    # Strip format=rss if present — we scrape HTML now
    url = re.sub(r"[&?]format=rss", "", url).rstrip("?&")

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    items = []

    # Each listing is a <li class="cl-static-search-result" title="...">
    for block in re.finditer(
        r'<li[^>]*cl-static-search-result[^>]*title="([^"]*)"[^>]*>(.*?)</li>',
        html, re.DOTALL
    ):
        title = block.group(1).strip()
        body  = block.group(2)

        # Link
        link_m = re.search(r'href="(https://sfbay\.craigslist\.org[^"]+)"', body)
        link = link_m.group(1) if link_m else ""

        # Price
        price_m = re.search(r'<div[^>]*class="price"[^>]*>\s*(\$[\d,]+)\s*</div>', body)
        price_raw = price_m.group(1) if price_m else "N/A"
        price = int(re.sub(r"[^\d]", "", price_raw)) if price_raw != "N/A" else None

        # Neighborhood is in .location div
        hood_m = re.search(r'<div[^>]*class="location"[^>]*>\s*(.*?)\s*</div>', body, re.DOTALL)
        neighborhood = re.sub(r"<[^>]+>", "", hood_m.group(1)).strip() if hood_m else ""

        # Posted date — extract from URL (7-digit post ID encodes nothing useful,
        # but the listing slug gives us the area code at minimum)
        pub_date = ""

        items.append({
            "title": title,
            "link": link,
            "description": "",   # not available on search page; use get_listing_details
            "pub_date": pub_date,
            "price": price,
            "price_raw": price_raw,
            "neighborhood": neighborhood,
        })

    return items


@tool
def search_listings(
    area: str = "all",
    max_price: int = 3000,
    min_price: int = 0,
    bedrooms: str = "any",
    query: str = "",
) -> str:
    """Search Craigslist Bay Area housing listings matching the given criteria.

    Fetches live listings from Craigslist RSS feeds. Use this first to get
    an overview of available housing before filtering or fetching details.

    Args:
        area: Bay Area sub-region. Options: "sf", "south bay", "east bay",
              "peninsula", "north bay", "all" (default "all")
        max_price: Maximum monthly rent in USD (default 3000)
        min_price: Minimum monthly rent in USD (default 0)
        bedrooms: Number of bedrooms: "0" (studio), "1", "2", "3", "4", or "any" (default "any")
        query: Optional keyword to search in listing titles (e.g. "furnished", "roommate")
    """
    area_key = area.lower().strip()
    zip_code, distance = AREA_ZIPS.get(area_key, (None, None))

    base = "https://sfbay.craigslist.org"
    params = {
        "max_price": max_price,
        "min_price": min_price,
    }

    if zip_code:
        params["postal"] = zip_code
        params["search_distance"] = distance

    if bedrooms != "any":
        params["min_bedrooms"] = bedrooms
        params["max_bedrooms"] = bedrooms

    if query:
        params["query"] = query

    search_path = "/search/apa"
    query_string = urllib.parse.urlencode(params)
    url = f"{base}{search_path}?{query_string}"

    listings = _fetch_rss(url)

    if not listings:
        return (
            f"No listings found for area='{area}', max_price=${max_price}, "
            f"bedrooms='{bedrooms}'. Try broadening your search."
        )

    lines = [
        f"Found {len(listings)} listings in {area.upper()} "
        f"(${min_price}–${max_price}/mo, bedrooms: {bedrooms}):\n"
    ]

    for i, l in enumerate(listings, 1):
        hood = f" [{l['neighborhood']}]" if l["neighborhood"] else ""
        lines.append(
            f"{i}. {l['title']}{hood}\n"
            f"   Price: {l['price_raw']}  |  Posted: {l['pub_date'][:16]}\n"
            f"   {l['description'][:120]}...\n"
            f"   🔗 URL (MUST include in response): {l['link']}\n"
        )

    return "\n".join(lines)


@tool
def get_listing_details(url: str) -> str:
    """Fetch the full details of a specific Craigslist housing listing by URL.

    Use this after search_listings to read the complete description of a
    listing that looks promising. Extracts text content from the listing page.

    Args:
        url: The full Craigslist listing URL (from search_listings results)
    """
    if not url.startswith("https://sfbay.craigslist.org"):
        return "Error: Only sfbay.craigslist.org URLs are supported."

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error fetching listing: {e}"

    # Extract posting body
    body_match = re.search(
        r'<section[^>]*id="postingbody"[^>]*>(.*?)</section>',
        html, re.DOTALL
    )
    body = ""
    if body_match:
        body = re.sub(r"<[^>]+>", " ", body_match.group(1))
        body = re.sub(r"\s+", " ", body).strip()
        body = body.replace("QR Code Link to This Post", "").strip()

    # Extract attributes (bedrooms, sqft, etc.)
    attrs = re.findall(r'<span class="attrunit"[^>]*>(.*?)</span>', html)
    attr_text = ", ".join(re.sub(r"<[^>]+>", "", a).strip() for a in attrs if a.strip())

    # Extract price
    price_match = re.search(r'<span class="price">(.*?)</span>', html)
    price = price_match.group(1).strip() if price_match else "N/A"

    # Extract title
    title_match = re.search(r'<span id="titletextonly">(.*?)</span>', html)
    title = title_match.group(1).strip() if title_match else "N/A"

    # Extract neighborhood
    hood_match = re.search(r'<small>\s*\((.*?)\)\s*</small>', html)
    neighborhood = hood_match.group(1).strip() if hood_match else "N/A"

    # Extract posted date
    date_match = re.search(r'<time[^>]*datetime="([^"]+)"', html)
    posted = date_match.group(1)[:10] if date_match else "N/A"

    return (
        f"Title: {title}\n"
        f"Price: {price}\n"
        f"Neighborhood: {neighborhood}\n"
        f"Posted: {posted}\n"
        f"Attributes: {attr_text or 'N/A'}\n\n"
        f"Description:\n{body[:2000]}\n\n"
        f"URL: {url}"
    )
