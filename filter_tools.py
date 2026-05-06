import re

from strands import tool


@tool
def filter_listings(
    listings_text: str,
    keywords_required: list[str] = None,
    keywords_excluded: list[str] = None,
    max_price: int = None,
    neighborhoods: list[str] = None,
) -> str:
    """Filter listings by keywords, price, or neighborhood.

    Args:
        listings_text: Raw text output from search_listings
        keywords_required: Words that MUST appear e.g. ["furnished"]
        keywords_excluded: Words that must NOT appear e.g. ["no pets"]
        max_price: Hard price cap
        neighborhoods: Keep only these neighborhoods (partial match)
    """
    if keywords_required is None:
        keywords_required = []
    if keywords_excluded is None:
        keywords_excluded = []
    if neighborhoods is None:
        neighborhoods = []

    # Split listings by numbered entries
    entries = re.split(r"\n(?=\d+\.)", listings_text.strip())
    header = entries[0] if not entries[0][0].isdigit() else ""
    listing_entries = [e for e in entries if e and e[0].isdigit()]

    kept = []
    removed_count = 0

    for entry in listing_entries:
        entry_lower = entry.lower()

        # Price filter
        if max_price:
            price_match = re.search(r"Price:\s*\$?([\d,]+)", entry)
            if price_match:
                price = int(price_match.group(1).replace(",", ""))
                if price > max_price:
                    removed_count += 1
                    continue

        # Required keywords
        if keywords_required:
            if not all(kw.lower() in entry_lower for kw in keywords_required):
                removed_count += 1
                continue

        # Excluded keywords
        if keywords_excluded:
            if any(kw.lower() in entry_lower for kw in keywords_excluded):
                removed_count += 1
                continue

        # Neighborhood filter
        if neighborhoods:
            if not any(n.lower() in entry_lower for n in neighborhoods):
                removed_count += 1
                continue

        kept.append(entry)

    if not kept:
        return (
            f"No listings matched your filters. "
            f"({removed_count} listings were filtered out.) "
            f"Try relaxing your requirements."
        )

    # Re-number
    renumbered = []
    for i, entry in enumerate(kept, 1):
        entry = re.sub(r"^\d+\.", f"{i}.", entry)
        renumbered.append(entry)

    summary = (
        f"Filtered results: {len(kept)} listings kept, {removed_count} removed.\n\n"
    )
    return summary + "\n".join(renumbered)
