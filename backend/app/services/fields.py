"""Field extraction with gemma3:4b: merchant, amount, date, reference and description from evidence.

Embeddings find and rank evidence; exact checks need the actual values. The vision model reads them from the
PDF text layer (pypdf) or straight from a photo. Results are cached in Chroma next to the document's vectors,
so each file is read once.

For PDFs a value only counts if it also appears in the pypdf text (`verified`), which guards against the model
inventing a number. Photos can't be cross-checked that way, so their values are marked as read from the image.
"""

import re

from app.config import settings
from app.services.ollama_client import generate_json, image_b64

SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "total_amount": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
        "document_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "reference": {"type": ["string", "null"], "description": "invoice, receipt, order or contract number"},
        "description": {"type": "string", "description": "what was bought or contracted, one sentence"},
    },
    "required": ["merchant", "total_amount", "currency", "document_date", "reference", "description"],
}

PROMPT = """You read payment evidence (invoices, receipts, contracts) for a card-dispute team.
Return the issuing merchant's legal name, the total amount charged (number only, no thousands separators),
its currency code, the document date as YYYY-MM-DD, the invoice/receipt/order/contract reference, and a
one-sentence description of what was bought. Use null for anything not shown. Do not guess.
"""


def _amount_forms(amount: float) -> list[str]:
    return [f"{amount:,.2f}", f"{amount:.2f}", f"{amount:,.2f}".replace(",", " "),
            f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]


def _verify(fields: dict, text: str) -> dict:
    norm = re.sub(r"\s+", " ", text.lower())
    amount, ref = fields.get("total_amount"), (fields.get("reference") or "").lower()
    return {
        "merchant": bool(fields.get("merchant")) and fields["merchant"].lower().split()[0] in norm,
        "total_amount": amount is not None and any(f.lower() in norm for f in _amount_forms(float(amount))),
        "reference": bool(ref) and ref in norm,
    }


async def extract_fields(kind: str, data: bytes, text: str) -> dict:
    if kind == "jpeg":
        raw = await generate_json(PROMPT + "\nThe evidence is the attached photo.", SCHEMA, image_b64(data))
        source = "image"
    else:
        raw = await generate_json(PROMPT + "\nEvidence text:\n" + text[:6000], SCHEMA)
        source = "pdf text"
    fields = {k: raw.get(k) for k in SCHEMA["properties"]}
    try:
        fields["total_amount"] = (None if fields["total_amount"] in (None, "")
                                  else round(float(str(fields["total_amount"]).replace(",", "")), 2))
    except ValueError:
        fields["total_amount"] = None
    return {**fields, "model": settings.llm_model, "source": source,
            "verified": _verify(fields, text) if kind != "jpeg" else None}
