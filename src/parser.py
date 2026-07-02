"""Turn raw OCR lines (from Vision.ocr_lines) into structured shop items.

Cards are anchored on the item name (tallest token); every other token attaches
to the nearest name above it. Status labels ("Out of Stock!", "Stock xN",
"Locked") are not names — they become the item's stock status. Names are
normalized so OCR variants of the same item merge.
"""
from __future__ import annotations

import re

# Rarity ladder, lowest -> highest.
RARITIES = [
    "Common", "Uncommon", "Rare", "Epic",
    "Legendary", "Mythic", "Secret", "Divine",
]
RARITY_RANK = {
    "common": 1, "uncommon": 2, "rare": 3, "epic": 4,
    "legendary": 5, "mythic": 6, "secret": 8, "divine": 9,
}

# UI / chrome words that must never be treated as an item name.
NAME_STOPLIST = {
    "factory", "houses", "house", "military", "special", "shop", "restock",
    "buy", "sell", "country", "talk", "premium", "stock", "owned", "max",
    "min", "sec", "x",
}

# Common OCR digit confusions.
_DIGIT_HOMO = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "i": "1"})

_DIGITS_ONLY = re.compile(r"^[\d\s.,xX]+$")
# Status/label fragments, never names. These must not collide with item names:
# "researching" rather than bare "research", or "Research Labs" gets dropped.
_BAD_NAME_SUBSTR = ("outofstock", "stockx", "instock", "researching", "locked", "unlock")


def _norm_letters(s: str) -> str:
    """Lowercase, keep only ascii letters (for status/rarity keyword tests)."""
    return re.sub(r"[^a-z]", "", s.lower())


def normalize_name(name: str) -> str:
    """Dedup key: lowercase, keep letters and digits only (names like 'Area 51')."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def clean_display(name: str) -> str:
    """Tidy a name for display: collapse spaces, trim stray punctuation."""
    return re.sub(r"\s+", " ", name).strip(" .,-_!")


def match_whitelist(name, whitelist):
    """Return the canonical whitelist entry this name matches, else None.
    Exact, prefix, containment within ~1.35x length, or fuzzy ratio >= 86."""
    key = normalize_name(name)
    if not key:
        return None
    name_words = set(re.findall(r"[a-z0-9]+", name.lower()))
    for e in whitelist:
        ne = normalize_name(e)
        if not ne:
            continue
        if key == ne:
            return e
        # OCR can append the card's description to the name; the name comes first,
        # so an entry that is a prefix of the read name is a confident match.
        if len(ne) >= 5 and key.startswith(ne):
            return e
        if ne in key and len(key) <= len(ne) * 1.35:
            return e
        if key in ne and len(ne) <= len(key) * 1.35:
            return e
        # Token subset: catches a description merged into the name. Entries must
        # be >=2 words so a lone common word ("Farm") can't false-match.
        ew = re.findall(r"[a-z0-9]+", e.lower())
        if len(ew) >= 2 and all(w in name_words for w in ew):
            return e
        try:
            from rapidfuzz import fuzz
            if fuzz.ratio(key, ne) >= 86:
                return e
        except Exception:
            pass
    return None


def parse_stock(text: str):
    """'Stock x3' / 'Stockx3' / 'Stock 3' -> 3."""
    m = re.search(r"(?i)stock\s*[xX]?\s*([0-9OolIi]+)", text)
    if m:
        digits = re.sub(r"\D", "", m.group(1).translate(_DIGIT_HOMO))
        if digits:
            return int(digits)
    return None


def parse_status(text: str, stock):
    """-> 'in' | 'out' | 'locked' | None for a card's joined text."""
    n = _norm_letters(text)
    if "outofstock" in n:
        return "out"
    if "researching" in n or "locked" in n or "unlock" in n:
        return "locked"
    if stock is not None:
        return "in"
    return None


def match_rarity(text: str):
    n = _norm_letters(text)
    if "secret" in n or "ecret" in n:   # rainbow 'Secret' text often defeats OCR
        return "Secret"
    t = text.lower()
    for r in sorted(RARITIES, key=len, reverse=True):   # 'uncommon' before 'common'
        if r.lower() in t:
            return r
    try:
        from rapidfuzz import process, fuzz
        # match against single rarity tokens so long names don't false-positive
        res = process.extractOne(_norm_letters(text), [r.lower() for r in RARITIES],
                                 scorer=fuzz.ratio)
        if res and res[1] >= 88:
            return RARITIES[res[2]]
    except Exception:
        pass
    return None


def _looks_like_name(text: str) -> bool:
    t = text.strip()
    if not t or _DIGITS_ONLY.match(t):
        return False
    if t.lower() in NAME_STOPLIST:
        return False
    n = _norm_letters(t)
    if any(bad in n for bad in _BAD_NAME_SUBSTR):
        return False  # status/label fragment, not a name
    if match_rarity(t) is not None and len(t.split()) <= 1:
        return False  # a lone rarity word
    # item names are Title Case ("Wheat Farm"); descriptions are lowercase
    # phrases ("grows wheat for the people") — reject those.
    if len(t.split()) >= 2 and t == t.lower() and not any(c.isdigit() for c in t):
        return False
    return len(n) >= 3


def _make_item(name: str, joined: str, y=None) -> dict:
    stock = parse_stock(joined)
    return {
        "name": name,
        "rarity": match_rarity(joined),
        "stock": stock,
        "status": parse_status(joined, stock),
        "raw": joined,
        "y": y,  # name-anchor y in the crop (for locating the buy button)
    }


def _gap_cluster(lines, crop_h):
    lines = sorted(lines, key=lambda l: l["y"])
    heights = sorted(l["h"] for l in lines)
    med_h = heights[len(heights) // 2] or 10.0
    gap_thr = max(med_h * 1.9, crop_h * 0.05)
    clusters = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        if cur["y"] - prev["y"] > gap_thr:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    items = []
    for cl in clusters:
        joined = " ".join(l["text"] for l in cl)
        names = [l for l in cl if _looks_like_name(l["text"])]
        if not names:
            continue
        name = " ".join(n["text"].strip() for n in sorted(names, key=lambda l: l["x0"]))
        items.append(_make_item(name.strip(), joined, min(n["y"] for n in names)))
    return items


def group_items(lines, crop_h: float):
    lines = [l for l in lines if l["text"].strip()]
    if not lines:
        return []

    namelike = [l for l in lines if _looks_like_name(l["text"])]
    if not namelike:
        return _gap_cluster(lines, crop_h)

    max_h = max(l["h"] for l in namelike)
    anchors = sorted([l for l in namelike if l["h"] >= 0.62 * max_h], key=lambda l: l["y"])
    if not anchors:
        return _gap_cluster(lines, crop_h)

    pad = 0.4 * max_h
    items = []
    for i, a in enumerate(anchors):
        y_lo = a["y"] - pad
        y_hi = (anchors[i + 1]["y"] - pad) if i + 1 < len(anchors) else float("inf")
        members = [l for l in lines if y_lo <= l["y"] < y_hi]
        joined = " ".join(l["text"] for l in members)

        name_tokens = [
            l for l in members
            if _looks_like_name(l["text"]) and l["h"] >= 0.62 * max_h
            and abs(l["y"] - a["y"]) <= 0.7 * max_h
        ]
        if a not in name_tokens:
            name_tokens.append(a)
        name = " ".join(
            t["text"].strip()
            for t in sorted(name_tokens, key=lambda l: (round(l["y"] / 8), l["x0"]))
        ).strip()
        if not name:
            continue
        items.append(_make_item(name, joined, a["y"]))
    return items


def dedupe(items):
    """Merge OCR variants of the same item (normalized name key)."""
    seen = {}
    for it in items:
        key = normalize_name(it["name"])
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(it)
            continue
        cur = seen[key]
        if cur.get("rarity") is None and it.get("rarity"):
            cur["rarity"] = it["rarity"]
        if cur.get("stock") is None and it.get("stock") is not None:
            cur["stock"] = it["stock"]
        if cur.get("status") is None and it.get("status"):
            cur["status"] = it["status"]
        # prefer the display variant with better word segmentation (more spaces)
        if it["name"].count(" ") > cur["name"].count(" "):
            cur["name"] = it["name"]
    for it in seen.values():
        if it.get("stock") is not None and it.get("status") is None:
            it["status"] = "in"
    return list(seen.values())
