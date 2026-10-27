"""Evidence matching with EmbeddingGemma 2.

- Text PDFs: transaction facets x document chunks cosine-similarity matrix, blended with deterministic field
  checks (amount, date, merchant, reference).
- JPEGs: the image itself is embedded in the same vector space and compared with each transaction facet.
"""

import math
import re
from datetime import date, timedelta

from app.services.extraction import chunk_text
from app.services.ollama_client import embed_image, embed_texts

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
    auth = date.fromisoformat(txn["auth_date"])
    window = [(auth - timedelta(days=n)).isoformat() for n in range(0, 8)]
    date_hit = next((d for d in window if any(v.lower() in norm for v in _date_variants(d))), None)

    name_tokens = [t for t in re.findall(r"[a-z]{4,}", txn["merchant_legal_name"].lower())
                   if t not in {"ltd", "limited", "inc", "llc", "corp"}]
    merchant_hits = sum(1 for t in name_tokens if t in lowered)
    merchant_hit = bool(name_tokens) and merchant_hits / len(name_tokens) >= 0.5

    ref = (txn.get("invoice_reference") or "").lower()
    ref_hit = bool(ref) and ref in lowered

    return [
        {"field": "Amount", "expected": f"{txn['currency']} {txn['amount']:,.2f}", "matched": amount_hit},
        {"field": "Date (within 7d of auth)", "expected": txn["auth_date"], "matched": bool(date_hit),
         "found": date_hit},
        {"field": "Merchant", "expected": txn["merchant_legal_name"], "matched": merchant_hit},
        # Only scored when the issuer feed carries a merchant reference.
        {"field": "Invoice ref", "expected": txn.get("invoice_reference") or "—", "matched": ref_hit,
         "applicable": bool(ref)},
    ]


# EmbeddingGemma retrieval prompts: facets act as queries, evidence chunks as documents.
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "

# Map raw cosine into 0..1. Text-to-text cosines for related passages rarely drop below ~0.2; text-to-image
# cosines run lower. Both ranges are starting points to re-tune against embeddinggemma-2 output.
TEXT_RANGE = (0.2, 0.6)
IMAGE_RANGE = (0.1, 0.4)


def _verdict(score: float) -> str:
    return "STRONG_MATCH" if score >= 0.7 else "PARTIAL_MATCH" if score >= 0.45 else "WEAK_MATCH"


def _semantic(best_per_facet: list[float], floor: float, span: float) -> float:
    return sum(max(0.0, min(1.0, (s - floor) / span)) for s in best_per_facet) / len(best_per_facet)


async def match_evidence(txn: dict, kind: str, document_text: str, data: bytes) -> dict:
    """Score evidence against a transaction. Text-layer PDFs are matched passage by passage; JPEGs are
    embedded directly as images by the same multimodal model."""
    if kind == "jpeg":
        return await _match_image(txn, data)
    return await _match_text(txn, document_text)


async def _match_text(txn: dict, document_text: str) -> dict:
    has_text = bool(document_text.strip())
    chunks = chunk_text(document_text) or ["(no text layer in evidence; nothing to match)"]
    facets = transaction_facets(txn)
    facet_names = list(facets)

    vectors, model_used = await embed_texts([QUERY_PREFIX + f for f in facets.values()] +
                                            [DOC_PREFIX + c for c in chunks])
    facet_vecs, chunk_vecs = vectors[: len(facets)], vectors[len(facets):]

    matrix = [[round(cosine(f, c), 4) for c in chunk_vecs] for f in facet_vecs]
    semantic = _semantic([max(row) for row in matrix], *TEXT_RANGE)

    checks = field_checks(txn, document_text)
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
        "verdict": _verdict(score),
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


async def _match_image(txn: dict, data: bytes) -> dict:
    facets = transaction_facets(txn)
    facet_names = list(facets)

    facet_vecs, model_used = await embed_texts([QUERY_PREFIX + f for f in facets.values()])
    image_vec = await embed_image(data)

    matrix = [[round(cosine(f, image_vec), 4)] for f in facet_vecs]
    semantic = _semantic([row[0] for row in matrix], *IMAGE_RANGE)
    # Exact field checks need text, so an image is scored on the embedding alone.
    checks = [{**c, "matched": False, "applicable": False} for c in field_checks(txn, "")]
    strongest = max(row[0] for row in matrix)
    image_label = "(image evidence: compared visually by the embedding model; see Exhibit A)"

    return {
        "mode": "image",
        "score": round(semantic, 4),
        "semantic_score": round(semantic, 4),
        "field_score": 0.0,
        "semantic_weight": 1.0,
        "field_weight": 0.0,
        "verdict": _verdict(semantic),
        "embedding_model": model_used,
        "facets": facet_names,
        "chunks": ["image"],
        "matrix": matrix,
        "field_checks": checks,
        "top_evidence": [{"chunk_index": 0, "similarity": round(strongest, 4), "text": image_label}],
        "note": "Image evidence is embedded directly by the multimodal model and compared with each transaction "
        "detail. Exact amount/date/merchant checks need text, so they are not applied.",
        "purpose_evidence": {"chunk_index": 0, "similarity": matrix[facet_names.index("purpose")][0],
                             "text": image_label},
    }
