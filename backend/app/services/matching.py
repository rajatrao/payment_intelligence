"""Evidence matching with EmbeddingGemma 2.

- Text PDFs: transaction facets x document chunks cosine-similarity matrix, blended with deterministic field
  checks (amount, date, merchant, reference).
- JPEGs: the image itself is embedded in the same vector space and compared with each transaction facet.
  Image-to-text cosines run high for every text (0.5-0.7 is common), so an image's semantic score is how far its
  similarity to a transaction stands above its similarity to the rest of the dispute queue, not raw cosine.
  Its field checks use the values gemma3 read from the photo (fields.py).
"""

import math
import re
import statistics
from datetime import date, timedelta

from app.config import settings
from app.data.transactions import DISPUTE_TRANSACTIONS
from app.services.ollama_client import embed_texts
from app.services.vector_store import IMAGE_LABEL

SEMANTIC_WEIGHT = 0.6
FIELD_WEIGHT = 0.4


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def transaction_facets(txn: dict) -> dict[str, str]:
    return {
        "merchant": f"Merchant {txn['merchant_legal_name']} (card descriptor {txn['merchant_descriptor']}), "
        f"{txn['mcc_description']}, country {txn['merchant_country']}",
        "amount": f"Total amount due {txn['currency']} {txn['amount']:,.2f}",
        "date": f"Transaction date {txn['auth_date']}, posted {txn['post_date']}",
        "reference": f"Invoice reference {txn.get('invoice_reference') or 'unknown'}",
        "purpose": f"Purpose of payment: {txn.get('memo') or txn['dispute_reason']}",
    }


def _amount_variants(amount: float) -> list[str]:
    return [f"{amount:,.2f}", f"{amount:.2f}", f"{amount:,.2f}".replace(",", " "),
            f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]


def _date_variants(iso: str) -> list[str]:
    d = date.fromisoformat(iso)
    return [d.isoformat(), d.strftime("%d/%m/%Y"), d.strftime("%m/%d/%Y"),
            d.strftime("%d %B %Y"), d.strftime("%B %d, %Y"), d.strftime("%d %b %Y")]


def field_checks(txn: dict, text: str) -> list[dict]:
    lowered = text.lower()
    norm = re.sub(r"\s+", " ", lowered)

    amount_hit = any(v.lower() in norm for v in _amount_variants(txn["amount"]))

    # Invoices are typically dated a few days before the card authorisation.
    window = _date_window(txn)
    date_hit = next((d for d in window if any(v.lower() in norm for v in _date_variants(d))), None)

    name_tokens = _merchant_tokens(txn)
    merchant_hits = sum(1 for t in name_tokens if t in lowered)
    merchant_hit = bool(name_tokens) and merchant_hits / len(name_tokens) >= 0.5

    ref = (txn.get("invoice_reference") or "").lower()
    ref_hit = bool(ref) and ref in lowered

    return _checks(txn, amount_hit, date_hit, merchant_hit, ref_hit)


def _checks(txn: dict, amount_hit: bool, date_hit: str | None, merchant_hit: bool, ref_hit: bool) -> list[dict]:
    ref = txn.get("invoice_reference") or ""
    return [
        {"field": "Amount", "expected": f"{txn['currency']} {txn['amount']:,.2f}", "matched": amount_hit},
        {"field": "Date (within 7d of auth)", "expected": txn["auth_date"], "matched": bool(date_hit),
         "found": date_hit},
        {"field": "Merchant", "expected": txn["merchant_legal_name"], "matched": merchant_hit},
        # Only scored when the issuer feed carries a merchant reference.
        {"field": "Invoice ref", "expected": ref or "—", "matched": ref_hit, "applicable": bool(ref)},
    ]


def _date_window(txn: dict) -> list[str]:
    auth = date.fromisoformat(txn["auth_date"])
    return [(auth - timedelta(days=n)).isoformat() for n in range(0, 8)]


def _merchant_tokens(txn: dict) -> list[str]:
    return [t for t in re.findall(r"[a-z]{4,}", txn["merchant_legal_name"].lower())
            if t not in {"ltd", "limited", "inc", "llc", "corp"}]


def extracted_checks(txn: dict, fields: dict) -> list[dict]:
    """Field checks against the values gemma3 read from the evidence (used for photos)."""
    amount = fields.get("total_amount")
    amount_hit = amount is not None and abs(float(amount) - txn["amount"]) < 0.01
    date_hit = fields.get("document_date") if fields.get("document_date") in _date_window(txn) else None
    tokens = _merchant_tokens(txn)
    seen = f"{fields.get('merchant') or ''} {fields.get('description') or ''}".lower()
    merchant_hit = bool(tokens) and sum(t in seen for t in tokens) / len(tokens) >= 0.5
    ref, read_ref = (txn.get("invoice_reference") or "").lower(), (fields.get("reference") or "").lower()
    ref_hit = bool(ref) and bool(read_ref) and (ref in read_ref or read_ref in ref)
    checks = _checks(txn, amount_hit, date_hit, merchant_hit, ref_hit)
    read = [f"{fields.get('currency') or ''} {amount:,.2f}".strip() if amount is not None else None,
            fields.get("document_date"), fields.get("merchant"), fields.get("reference")]
    return [{**c, "read": v} for c, v in zip(checks, read)]


# EmbeddingGemma retrieval prompt for queries: the transaction facets. Evidence is embedded with the document
# prompt and stored in Chroma by vector_store.py.
QUERY_PREFIX = "task: search result | query: "

# Map raw cosine into 0..1. Text-to-text cosines for related passages rarely drop below ~0.2.
TEXT_RANGE = (0.2, 0.6)
# Images: a facet scores 1.0 when its cosine with the image is IMAGE_MARGIN above the median cosine of the same
# facet across the dispute queue, and 0 at or below that median. Re-tune with scripts/check_image_embeddings.py.
IMAGE_MARGIN = 0.06
IMAGE_TOP_FACETS = 3

# Facet vectors are deterministic for a given text and model, so they are cached for the process.
_FACET_CACHE: dict[tuple[str, str], list[float]] = {}


def _verdict(score: float, checks: list[dict] | None = None) -> str:
    # A chargeback stands on the amount: evidence for a different amount never counts as a match.
    if checks and checks[0].get("applicable", True) and checks[0]["field"] == "Amount" and not checks[0]["matched"] \
            and any(c.get("applicable", True) for c in checks):
        return "WEAK_MATCH"
    return "STRONG_MATCH" if score >= 0.7 else "PARTIAL_MATCH" if score >= 0.45 else "WEAK_MATCH"


def _semantic(best_per_facet: list[float], floor: float, span: float) -> float:
    return sum(max(0.0, min(1.0, (s - floor) / span)) for s in best_per_facet) / len(best_per_facet)


async def facet_vectors(txn: dict) -> tuple[dict, list[list[float]], str]:
    facets = transaction_facets(txn)
    texts = [QUERY_PREFIX + f for f in facets.values()]
    missing = [t for t in texts if (settings.embed_model, t) not in _FACET_CACHE]
    if missing:
        vecs, _ = await embed_texts(missing)
        _FACET_CACHE.update({(settings.embed_model, t): v for t, v in zip(missing, vecs)})
    return facets, [_FACET_CACHE[(settings.embed_model, t)] for t in texts], settings.embed_model


async def match_evidence(txn: dict, doc: dict, document_text: str, fields: dict | None = None,
                         queue: list[dict] | None = None) -> dict:
    """Score stored evidence (see vector_store.index_document) against a transaction. Only the transaction
    facets are embedded here; the evidence vectors come from Chroma. Images are scored relative to `queue`
    (default: every disputed transaction)."""
    facets, facet_vecs, model_used = await facet_vectors(txn)
    if doc["kind"] == "jpeg":
        image_vec = doc["vectors"][0]
        baseline = [[] for _ in facet_vecs]
        for other in queue or DISPUTE_TRANSACTIONS:
            _, other_vecs, _ = await facet_vectors(other)
            for i, v in enumerate(other_vecs):
                baseline[i].append(cosine(v, image_vec))
        medians = [statistics.median(b) for b in baseline]
        result = _match_image(txn, facets, facet_vecs, image_vec, medians, model_used, fields)
    else:
        result = _match_text(txn, facets, facet_vecs, doc["chunks"], doc["vectors"], document_text, model_used,
                             fields)
    return {**result, "doc_id": doc["doc_id"], "vectors_cached": doc["cached"], "extracted": fields}


def _match_text(txn: dict, facets: dict, facet_vecs: list, chunks: list[str], chunk_vecs: list,
                document_text: str, model_used: str, fields: dict | None) -> dict:
    has_text = bool(document_text.strip())
    facet_names = list(facets)

    matrix = [[round(cosine(f, c), 4) for c in chunk_vecs] for f in facet_vecs]
    semantic = _semantic([max(row) for row in matrix], *TEXT_RANGE)

    checks = field_checks(txn, document_text)
    if fields:
        # Exact text checks decide for PDFs, with two refinements from gemma3's reading: the amount must be the
        # document's total (and appear in the text), not just any line item; and a date written in a format the
        # text check doesn't know can still match.
        verified = fields.get("verified") or {}
        for check, read in zip(checks, extracted_checks(txn, fields)):
            check["read"] = read["read"]
            if check["field"] == "Amount" and fields.get("total_amount") is not None:
                check["matched"] = read["matched"] and bool(verified.get("total_amount"))
            if check["field"].startswith("Date") and not check["matched"] and read["matched"]:
                check.update(matched=True, found=read["read"])
    scored = [c for c in checks if c.get("applicable", True)]
    field_score = sum(c["matched"] for c in scored) / len(scored)
    score = SEMANTIC_WEIGHT * semantic + FIELD_WEIGHT * field_score

    chunk_strength = [max(matrix[i][j] for i in range(len(facet_vecs))) for j in range(len(chunks))]
    ranked = sorted(range(len(chunks)), key=lambda j: chunk_strength[j], reverse=True)
    evidence = [{"chunk_index": j, "similarity": round(chunk_strength[j], 4), "text": chunks[j]}
                for j in ranked[:4]]

    purpose_row = matrix[facet_names.index("purpose")]
    purpose_idx = max(range(len(chunks)), key=lambda j: purpose_row[j])

    return {
        "mode": "text",
        "score": round(score, 4),
        "semantic_score": round(semantic, 4),
        "field_score": round(field_score, 4),
        "semantic_weight": SEMANTIC_WEIGHT,
        "field_weight": FIELD_WEIGHT,
        "verdict": _verdict(score, checks),
        "embedding_model": model_used,
        "facets": facet_names,
        "chunks": [c[:160] for c in chunks],
        "matrix": matrix,
        "field_checks": checks,
        "top_evidence": evidence,
        "note": None if has_text else "This PDF has no text layer (it looks scanned). Upload it as a JPEG to match "
        "it as an image, or use a text-based PDF.",
        "purpose_evidence": {"chunk_index": purpose_idx, "similarity": round(purpose_row[purpose_idx], 4),
                             "text": chunks[purpose_idx]},
    }


def _match_image(txn: dict, facets: dict, facet_vecs: list, image_vec: list, medians: list[float],
                 model_used: str, fields: dict | None) -> dict:
    facet_names = list(facets)

    matrix = [[round(cosine(f, image_vec), 4)] for f in facet_vecs]
    # Lift of each facet over the queue median: only what sets this transaction apart from the others counts.
    # A photo rarely shows every detail legibly, so the score uses the IMAGE_TOP_FACETS facets that lift most.
    raw_lifts = [row[0] - m for row, m in zip(matrix, medians)]
    lifts = sorted(raw_lifts, reverse=True)
    semantic = _semantic(lifts[:IMAGE_TOP_FACETS], 0.0, IMAGE_MARGIN)
    used = set(sorted(range(len(raw_lifts)), key=lambda i: raw_lifts[i], reverse=True)[:IMAGE_TOP_FACETS])
    image_lifts = [{"facet": name, "cosine": matrix[i][0], "queue_median": round(medians[i], 4),
                    "lift": round(raw_lifts[i], 4), "scaled": round(max(0.0, min(1.0, raw_lifts[i] / IMAGE_MARGIN)), 4),
                    "used": i in used} for i, name in enumerate(facet_names)]
    strongest = max(row[0] for row in matrix)
    if fields:
        checks = extracted_checks(txn, fields)
        scored = [c for c in checks if c.get("applicable", True)]
        field_score = sum(c["matched"] for c in scored) / len(scored)
        sem_w, field_w = SEMANTIC_WEIGHT, FIELD_WEIGHT
    else:
        # Without gemma3's reading there is nothing exact to check, so the embedding decides alone.
        checks = [{**c, "matched": False, "applicable": False} for c in field_checks(txn, "")]
        field_score, sem_w, field_w = 0.0, 1.0, 0.0
    score = sem_w * semantic + field_w * field_score

    return {
        "mode": "image",
        "score": round(score, 4),
        "semantic_score": round(semantic, 4),
        "field_score": round(field_score, 4),
        "semantic_weight": sem_w,
        "field_weight": field_w,
        "verdict": _verdict(score, checks if fields else None),
        "embedding_model": model_used,
        "facets": facet_names,
        "chunks": ["image"],
        "matrix": matrix,
        "field_checks": checks,
        "top_evidence": [{"chunk_index": 0, "similarity": round(strongest, 4), "text": IMAGE_LABEL}],
        "image_baseline": [round(m, 4) for m in medians],
        "image_lifts": image_lifts,
        "image_margin": IMAGE_MARGIN,
        "note": f"Photo evidence: {fields['model']} read the amount, date and merchant from the photo for the "
        "checks below; EmbeddingGemma 2 adds a visual-similarity score." if fields else
        "Photo evidence matched by EmbeddingGemma 2 only: the field-extraction model was not available, so "
        "amount, date and merchant could not be checked.",
        "purpose_evidence": {"chunk_index": 0, "similarity": matrix[facet_names.index("purpose")][0],
                             "text": IMAGE_LABEL},
    }
