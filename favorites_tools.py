import json
import os
import re
from datetime import datetime

from strands import tool

FAVORITES_FILE = "favorites.json"


def _load_favorites() -> list[dict]:
    if os.path.exists(FAVORITES_FILE):
        with open(FAVORITES_FILE, "r") as f:
            return json.load(f)
    return []


def _save_favorites(favorites: list[dict]):
    with open(FAVORITES_FILE, "w") as f:
        json.dump(favorites, f, indent=2)


@tool
def save_favorite(
    title: str,
    url: str,
    price: str,
    neighborhood: str,
    notes: str = "",
) -> str:
    """Save a listing to favorites.

    Args:
        title: Listing title
        url: Full listing URL
        price: Listed price e.g. $2,400/mo
        neighborhood: Neighborhood or area
        notes: Optional notes
    """
    favorites = _load_favorites()

    # Avoid duplicates
    for fav in favorites:
        if fav.get("url") == url:
            return f"This listing is already in your favorites:\n  {title}\n  {url}"

    entry = {
        "title": title,
        "url": url,
        "price": price,
        "neighborhood": neighborhood,
        "notes": notes,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    favorites.append(entry)
    _save_favorites(favorites)

    return (
        f"Saved to favorites!\n"
        f"  Title: {title}\n"
        f"  Price: {price}\n"
        f"  Neighborhood: {neighborhood}\n"
        f"  URL: {url}\n"
        f"  Notes: {notes or '(none)'}\n"
        f"  Total favorites saved: {len(favorites)}"
    )


@tool
def view_favorites() -> str:
    """Return all saved favorite listings."""
    favorites = _load_favorites()

    if not favorites:
        return "You have no saved favorites yet. Use save_favorite to bookmark listings."

    lines = [f"Your saved favorites ({len(favorites)} total):\n"]
    for i, fav in enumerate(favorites, 1):
        lines.append(
            f"{i}. {fav['title']}\n"
            f"   Price: {fav['price']}  |  Area: {fav['neighborhood']}\n"
            f"   Saved: {fav['saved_at']}\n"
            f"   Notes: {fav.get('notes') or '(none)'}\n"
            f"   Link: {fav['url']}\n"
        )

    return "\n".join(lines)


@tool
def remove_favorite(url: str) -> str:
    """Remove a saved favorite by URL.

    Args:
        url: URL of the listing to remove
    """
    favorites = _load_favorites()
    original_count = len(favorites)
    favorites = [f for f in favorites if f.get("url") != url]

    if len(favorites) == original_count:
        return f"No favorite found with URL: {url}"

    _save_favorites(favorites)
    return f"Removed listing from favorites. ({len(favorites)} remaining)"
