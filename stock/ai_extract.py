"""Delivery-note scanning via the Anthropic API.

extract_lines() is the only function that talks to the network. It is
deliberately resilient: it raises a single ExtractError with a friendly
message for any failure mode (missing key, network, malformed JSON,
unsupported file type) so the caller can fall back to manual entry.
"""

import base64
import json
import os
import re

from .models import SupplierPrice

MODEL = "claude-sonnet-4-6"

PROMPT = (
    "Extract every line item from this delivery note. "
    "Reply with a single JSON array and nothing else (no prose, no markdown fences). "
    'Each element must be {"description": "<product as written>", "qty": <number of packs or units>}. '
    "Ignore subtotal/total/tax rows and any header/footer text. "
    "If you cannot read the document, reply with []."
)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class ExtractError(Exception):
    """A friendly, user-facing error from the scan pipeline."""


def parse_lines_json(text):
    """Best-effort JSON parse. Returns a list of {description, qty} dicts; [] on failure."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                data = None
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        desc = item.get("description") or item.get("name") or ""
        qty_raw = item.get("qty", item.get("quantity"))
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            continue
        desc = str(desc).strip()
        if not desc or qty <= 0:
            continue
        out.append({"description": desc, "qty": qty})
    return out


def extract_lines(file_bytes, mime_type):
    """Send the bytes to the Anthropic API and return parsed line items."""
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise ExtractError("scanning is disabled (no ANTHROPIC_API_KEY)")
    try:
        import anthropic
    except ImportError as e:
        raise ExtractError("scanning is disabled (anthropic package not installed)") from e

    if mime_type == "application/pdf":
        doc_block = {"type": "document",
                     "source": {"type": "base64", "media_type": "application/pdf",
                                "data": base64.standard_b64encode(file_bytes).decode("ascii")}}
    elif mime_type in SUPPORTED_IMAGE_TYPES:
        doc_block = {"type": "image",
                     "source": {"type": "base64", "media_type": mime_type,
                                "data": base64.standard_b64encode(file_bytes).decode("ascii")}}
    else:
        raise ExtractError(f"unsupported file type ({mime_type or 'unknown'})")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [doc_block, {"type": "text", "text": PROMPT}]}],
        )
    except Exception as e:
        raise ExtractError(f"could not reach scanning service ({type(e).__name__})") from e

    text = "".join(getattr(b, "text", "") for b in resp.content)
    return parse_lines_json(text)


def auto_match(description, supplier, dept):
    """Return (product, confident) for a free-text description.

    Confident = product name (lowercased, trimmed) appears as a substring of
    the description. Products with a SupplierPrice for this supplier are
    tried first. Longer product names win when ambiguous.
    """
    desc = " " + (description or "").lower().strip() + " "
    priced_ids = set(SupplierPrice.objects
                     .filter(supplier=supplier).values_list("product_id", flat=True))
    products = list(dept.products.all())
    preferred = sorted([p for p in products if p.id in priced_ids],
                       key=lambda p: -len(p.name))
    others = sorted([p for p in products if p.id not in priced_ids],
                    key=lambda p: -len(p.name))
    for p in preferred + others:
        n = p.name.lower().strip()
        if n and n in desc:
            return p, True
    return None, False
