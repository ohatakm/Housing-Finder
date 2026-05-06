import re
import ssl
import urllib.request
import urllib.parse
import concurrent.futures

from strands import tool


AREA_CODES = {
    "sf": "sfc",
    "south bay": "sby",
    "east bay": "eby",
    "peninsula": "pen",
    "north bay": "nby",
    "all": None,
}

AREA_ZIPS = {
    "sf":         ("94102", 15),
    "south bay":  ("95101", 20),
    "east bay":   ("94612", 20),
    "peninsula":  ("94401", 15),
    "north bay":  ("94901", 20),
    "all":        (None, None),
}

# Sources the user can filter by
SOURCES = ["apartments", "rooms", "sublets"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _get(url: str, timeout: int = 15) -> str:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _scrape_cl(category: str, source_label: str,
               area: str, max_price: int, min_price: int,
               bedrooms: str, query: str) -> list:
    zip_code, distance = AREA_ZIPS.get(area, (None, None))
    params = {"max_price": max_price, "min_price": min_price}
    if zip_code:
        params["postal"] = zip_code
        params["search_distance"] = distance
    if bedrooms != "any" and category == "apa":
        params["min_bedrooms"] = bedrooms
        params["max_bedrooms"] = bedrooms
    if query:
        params["query"] = query
    url = f"https://sfbay.craigslist.org/search/{category}?{urllib.parse.urlencode(params)}"
    html = _get(url)
    items = []
    pat = re.compile(
        r'<li[^>]*cl-static-search-result[^>]*title="([^"]*)"[^>]*>(.*?)</li>',
        re.DOTALL,
    )
    for block in pat.finditer(html):
        title = block.group(1).strip()
        body  = block.group(2)
        link_m = re.search(r'href="(https://sfbay\.craigslist\.org[^"]+)"', body)
        link = link_m.group(1) if link_m else ""
        price_m = re.search(r'<div[^>]*class="price"[^>]*>\s*(\$[\d,]+)\s*</div>', body)
        price_raw = price_m.group(1) if price_m else "N/A"
        price = int(re.sub(r"[^\d]", "", price_raw)) if price_raw != "N/A" else None
        hood_m = re.search(r'<div[^>]*class="location"[^>]*>\s*(.*?)\s*</div>', body, re.DOTALL)
        neighborhood = re.sub(r"<[^>]+>", "", hood_m.group(1)).strip() if hood_m else ""
        if title and link:
            items.append({
                "source": source_label,
                "title": title,
                "link": link,
                "description": "",
                "pub_date": "",
                "price": price,
                "price_raw": price_raw,
                "neighborhood": neighborhood,
            })
    return items


_SOURCE_FETCHERS = {
    "apartments": lambda *a: _scrape_cl("apa", "Apartments", *a),
    "rooms":      lambda *a: _scrape_cl("roo", "Rooms/Shared", *a),
    "sublets":    lambda *a: _scrape_cl("sub", "Sublets", *a),
}


def fetch_all_sources(area="all", max_price=3500, min_price=0,
                      bedrooms="any", query="", sources=None):
    if sources is None:
        sources = list(_SOURCE_FETCHERS.keys())
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_SOURCE_FETCHERS[src], area, max_price, min_price, bedrooms, query): src
            for src in sources if src in _SOURCE_FETCHERS
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                results.extend(future.result())
            except Exception:
                pass
    return results


def _fetch_rss(url: str) -> list:
    """Legacy shim for the browse/search tabs in streamlit_app.py."""
    html = _get(url)
    items = []
    pat = re.compile(
        r'<li[^>]*cl-static-search-result[^>]*title="([^"]*)"[^>]*>(.*?)</li>',
        re.DOTALL,
    )
    for block in pat.finditer(html):
        title = block.group(1).strip()
        body  = block.group(2)
        link_m = re.search(r'href="(https://sfbay\.craigslist\.org[^"]+)"', body)
        link = link_m.group(1) if link_m else ""
        price_m = re.search(r'<div[^>]*class="price"[^>]*>\s*(\$[\d,]+)\s*</div>', body)
        price_raw = price_m.group(1) if price_m else "N/A"
        price = int(re.sub(r"[^\d]", "", price_raw)) if price_raw != "N/A" else None
        hood_m = re.search(r'<div[^>]*class="location"[^>]*>\s*(.*?)\s*</div>', body, re.DOTALL)
        neighborhood = re.sub(r"<[^>]+>", "", hood_m.group(1)).strip() if hood_m else ""
        if title and link:
            items.append({
                "source": "Craigslist",
                "title": title,
                "link": link,
                "description": "",
                "pub_date": "",
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
    sources: str = "all",
) -> str:
    """Search Bay Area Craigslist rentals across apartments, rooms/shared housing, and sublets.

    Args:
        area: sf, south bay, east bay, peninsula, north bay, or all
        max_price: Max monthly rent in USD
        min_price: Min monthly rent in USD
        bedrooms: 0 (studio), 1, 2, 3, 4, or any
        query: Keyword filter e.g. furnished, parking, utilities included
        sources: Comma-separated or all. Options: apartments, rooms, sublets
    """
    area_key = area.lower().strip()
    src_list = None if sources.lower() == "all" else [s.strip().lower() for s in sources.split(",")]

    listings = fetch_all_sources(
        area=area_key, max_price=max_price, min_price=min_price,
        bedrooms=bedrooms, query=query, sources=src_list,
    )

    if not listings:
        return (
            f"No listings found for area='{area}', max_price=${max_price}, "
            f"bedrooms='{bedrooms}'. Try broadening your search."
        )

    by_source = {}
    for l in listings:
        by_source[l["source"]] = by_source.get(l["source"], 0) + 1
    source_summary = ", ".join(f"{s}: {c}" for s, c in by_source.items())

    lines = [
        f"Found {len(listings)} listings in {area.upper()} "
        f"(${min_price}-${max_price}/mo, bedrooms: {bedrooms})\n"
        f"Sources: {source_summary}\n"
    ]
    for i, l in enumerate(listings, 1):
        hood = f" [{l['neighborhood']}]" if l.get("neighborhood") else ""
        desc_snippet = (l["description"][:120] + "...") if l.get("description") else ""
        lines.append(
            f"{i}. [{l['source']}] {l['title']}{hood}\n"
            f"   Price: {l['price_raw']}\n"
            f"   {desc_snippet}\n"
            f"   URL (MUST include in response): {l['link']}\n"
        )
    return "\n".join(lines)


@tool
def get_listing_details(url: str) -> str:
    """Fetch full details of a Craigslist listing by URL.

    Args:
        url: Full Craigslist listing URL from search_listings results
    """
    if "craigslist.org" not in url:
        return f"Error: Only Craigslist URLs are supported. Got: {url}"

    html = _get(url)
    if not html:
        return f"Error: Could not fetch listing at {url}"

    body_match = re.search(
        r'<section[^>]*id="postingbody"[^>]*>(.*?)</section>', html, re.DOTALL
    )
    body = ""
    if body_match:
        body = re.sub(r"<[^>]+>", " ", body_match.group(1))
        body = re.sub(r"\s+", " ", body).strip()
        body = body.replace("QR Code Link to This Post", "").strip()

    attrs = re.findall(r'<span class="attrunit"[^>]*>(.*?)</span>', html)
    attr_text = ", ".join(re.sub(r"<[^>]+>", "", a).strip() for a in attrs if a.strip())

    price_m = re.search(r'<span class="price">(.*?)</span>', html)
    price = price_m.group(1).strip() if price_m else "N/A"
    title_m = re.search(r'<span id="titletextonly">(.*?)</span>', html)
    title = title_m.group(1).strip() if title_m else "N/A"
    hood_m = re.search(r'<small>\s*\((.*?)\)\s*</small>', html)
    neighborhood = hood_m.group(1).strip() if hood_m else "N/A"
    date_m = re.search(r'<time[^>]*datetime="([^"]+)"', html)
    posted = date_m.group(1)[:10] if date_m else "N/A"

    return (
        f"Title: {title}\n"
        f"Price: {price}\n"
        f"Neighborhood: {neighborhood}\n"
        f"Posted: {posted}\n"
        f"Attributes: {attr_text or 'N/A'}\n\n"
        f"Description:\n{body[:2000]}\n\n"
        f"URL: {url}"
    )
