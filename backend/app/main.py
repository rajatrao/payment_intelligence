"""Payment Intelligence API.

Modules:
- Auto-Dispute Concierge (/api/disputes): live.
- Card Optimizer (/api/card-optimizer): live.
- Liquidity Guard (/api/liquidity-guard): not yet available; responds 423.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import settings
from app.data.transactions import DISPUTE_TRANSACTIONS, SAMPLE_TRANSACTION_ID, get_transaction
from app.services.extraction import detect_kind, extract_text
from app.services.fields import extract_fields
from app.services.letter import generate_letter
from app.services.matching import facet_vectors, match_evidence
from app.services.ollama_client import OllamaUnavailable, ollama_status
from app.services.pdf_builder import build_chargeback_package
from app.services.samples import DEFAULT_SAMPLE_ID, get_sample, sample_bytes, sample_metadata
from app.services import vector_store
from app.services.card_optimizer import recommend
from app.services.corridor import all_analyses, get_analysis
from app.data.transactions.cross_border import CARD_PORTFOLIO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="Payment Intelligence", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# Matching runs on its own (POST /api/disputes/evidence); a case only writes the letter and renders the package.
PIPELINE_STAGES = ["generate_letter", "render_pdf"]
MAX_EVIDENCE = 50
BUILDABLE_VERDICTS = {"STRONG_MATCH", "PARTIAL_MATCH"}
LOCKS = {
    "liquidity-guard": "The Liquidity Guard module is not available yet.",
}

# In-memory stores; fine for a single-process local demo. Evidence vectors live in Chroma.
EVIDENCE: dict[str, dict] = {}
DISPUTES: dict[str, dict] = {}
PACKAGES: dict[str, bytes] = {}
_TASKS: set[asyncio.Task] = set()


def _pdf_response(data: bytes, filename: str, download: bool) -> Response:
    disposition = "attachment" if download else "inline"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"',
                             "Cache-Control": "no-store"})


# ---------------------------------------------------------------- system

@app.get("/api/health")
async def health():
    return {"status": "ok", "ollama": await ollama_status(), "vector_store": vector_store.stats(),
            "config": {"llm_model": settings.llm_model, "embed_model": settings.embed_model,
                       "decision_model": settings.decision_model,
                       "nimble_path": settings.nimble_path, "offline_fallback": settings.allow_offline_fallback}}


@app.get("/api/modules")
async def modules():
    return [
        {"id": "disputes", "name": "Auto-Dispute Concierge", "locked": False},
        {"id": "card-optimizer", "name": "Card Optimizer", "locked": False},
        {"id": "liquidity-guard", "name": "Liquidity Guard", "locked": True, "lock_message": LOCKS["liquidity-guard"]},
    ]


# ---------------------------------------------------------------- disputes: transactions

@app.get("/api/disputes/transactions")
async def list_transactions():
    return {"sample_transaction_id": SAMPLE_TRANSACTION_ID, "transactions": DISPUTE_TRANSACTIONS}


async def _fields(doc: dict, kind: str, data: bytes | None, text: str) -> tuple[dict | None, str | None]:
    """gemma3's reading of a document, from the Chroma cache or freshly extracted. Never fatal: without it PDFs
    still have exact text checks and photos fall back to the embedding alone."""
    if (cached := vector_store.get_fields(doc["doc_id"])) is not None:
        return cached, None
    if data is None:
        return None, "file bytes not available to read"
    try:
        fields = await extract_fields(kind, data, text)
    except OllamaUnavailable as exc:
        log.warning("Field extraction skipped for %s: %s", doc["filename"], exc)
        return None, str(exc)
    vector_store.set_fields(doc["doc_id"], fields)
    return fields, None


async def _index_sample(sample: dict) -> tuple[dict, str, bytes]:
    data = sample_bytes(sample["id"])
    text, _ = await asyncio.to_thread(extract_text, sample["kind"], data)
    return await vector_store.index_document(data, sample["filename"], sample["kind"], text, "sample"), text, data


@app.get("/api/disputes/transactions/{transaction_id}/evidence-search")
async def search_evidence(transaction_id: str, limit: int = 5):
    """Find evidence for a transaction across every stored file: Chroma nearest-neighbour search on the
    transaction's facet vectors gives a shortlist, then each candidate is read by gemma3 and fully matched.
    The sample library stands in for a document store such as Google Drive."""
    txn = get_transaction(transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    try:
        samples_by_name = {}
        for sample in sample_metadata():
            await _index_sample(sample)
            samples_by_name[sample["filename"]] = sample
        _, facet_vecs, _ = await facet_vectors(txn)
        candidates = vector_store.search(facet_vecs)
        results = []
        # Photos and text sit in different regions of the embedding space (the "modality gap"), so photo distances
        # are larger than PDF distances for the same transaction. Shortlist each kind separately so photos aren't
        # crowded out by PDFs.
        limit = max(1, min(limit, 20))
        shortlist = ([h for h in candidates if h["kind"] != "jpeg"][:limit]
                     + [h for h in candidates if h["kind"] == "jpeg"][:max(1, limit // 2)])
        for hit in shortlist:
            doc = vector_store.load(hit["doc_id"])
            if doc is None:
                continue
            sample, held = samples_by_name.get(hit["filename"]), EVIDENCE.get(hit["doc_id"])
            data = sample_bytes(sample["id"]) if sample else held["data"] if held else None
            text = (await asyncio.to_thread(extract_text, hit["kind"], data))[0] if data else (
                "" if hit["kind"] == "jpeg" else "\n".join(doc["chunks"]))
            fields, _ = await _fields(doc, hit["kind"], data, text)
            m = await match_evidence(txn, doc, text, fields)
            results.append({**hit, "sample_id": sample["id"] if sample else None, "evidence_available": bool(held),
                            "score": m["score"], "semantic_score": m["semantic_score"],
                            "field_score": m["field_score"], "verdict": m["verdict"], "extracted": fields})
    except OllamaUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"transaction_id": transaction_id, "searched_documents": vector_store.stats().get("documents"),
            "candidates": len(candidates), "results": results}


@app.get("/api/disputes/transactions/{transaction_id}")
async def read_transaction(transaction_id: str):
    txn = get_transaction(transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    return txn


# ---------------------------------------------------------------- disputes: sample evidence library

def _sample_or_404(sample_id: str) -> dict:
    sample = get_sample(sample_id)
    if not sample:
        raise HTTPException(404, "Sample not found")
    return sample


@app.get("/api/disputes/samples")
async def list_samples():
    """Sample receipts, invoices and contracts: some back a transaction, some are decoys."""
    return {"default_sample_id": DEFAULT_SAMPLE_ID, "samples": sample_metadata()}


@app.get("/api/disputes/samples/{sample_id}")
async def sample_file(sample_id: str, download: bool = False):
    """Sample document as a PDF or JPEG stream (inline, or attachment with ?download=true)."""
    sample = _sample_or_404(sample_id)
    if sample["kind"] == "pdf":
        return _pdf_response(sample_bytes(sample_id), sample["filename"], download)
    disposition = "attachment" if download else "inline"
    return Response(content=sample_bytes(sample_id), media_type="image/jpeg",
                    headers={"Content-Disposition": f'{disposition}; filename="{sample["filename"]}"'})


@app.get("/api/disputes/samples/{sample_id}/text")
async def sample_text(sample_id: str):
    sample = _sample_or_404(sample_id)
    text, method = extract_text(sample["kind"], sample_bytes(sample_id))
    return {"sample_id": sample_id, "filename": sample["filename"], "method": method, "text": text}


@app.get("/api/disputes/sample-invoice")
async def sample_invoice(download: bool = False):
    """The pre-loaded EUROSITES invoice (kept as a stable alias of the default sample)."""
    return await sample_file(DEFAULT_SAMPLE_ID, download)


# ---------------------------------------------------------------- disputes: match evidence

async def _read_evidence(file: UploadFile | None, sample_id: str | None, use_sample: bool) -> tuple:
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Evidence file exceeds 15 MB")
        try:
            kind = detect_kind(file.filename, file.content_type, data)
        except ValueError as exc:
            raise HTTPException(415, str(exc)) from exc
        return data, file.filename, kind, "upload"
    if sample_id or use_sample:
        sample = _sample_or_404(sample_id or DEFAULT_SAMPLE_ID)
        return sample_bytes(sample["id"]), sample["filename"], sample["kind"], "sample"
    raise HTTPException(400, "Upload a PDF/JPEG evidence file, or pass sample_id")


def _public_evidence(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if k not in ("data", "text")}


@app.post("/api/disputes/evidence")
async def match_evidence_file(file: UploadFile | None = File(None), sample_id: str | None = Form(None),
                              use_sample: bool = Form(False)):
    """Step 1: embed the evidence (or reuse its Chroma vectors) and match it against every disputed transaction.
    Nothing is generated here, so files that back no transaction can be tried freely."""
    data, filename, kind, source = await _read_evidence(file, sample_id, use_sample)
    try:
        text, method = await asyncio.to_thread(extract_text, kind, data)
        doc = await vector_store.index_document(data, filename, kind, text, source)
        fields, fields_error = await _fields(doc, kind, data, text)
        matches = {t["id"]: await match_evidence(t, doc, text, fields) for t in DISPUTE_TRANSACTIONS}
    except OllamaUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

    ranking = sorted(({"transaction_id": tid, "score": m["score"], "semantic_score": m["semantic_score"],
                       "field_score": m["field_score"], "verdict": m["verdict"], "mode": m["mode"]}
                      for tid, m in matches.items()), key=lambda r: r["score"], reverse=True)
    best = ranking[0] if ranking and ranking[0]["verdict"] in BUILDABLE_VERDICTS else None
    evidence_id = doc["doc_id"]
    EVIDENCE.pop(evidence_id, None)
    while len(EVIDENCE) >= MAX_EVIDENCE:
        EVIDENCE.pop(next(iter(EVIDENCE)))
    EVIDENCE[evidence_id] = {
        "evidence_id": evidence_id, "filename": filename, "kind": kind, "source": source, "method": method,
        "text_preview": text[:1500], "embedding_model": settings.embed_model,
        "vectors": "reused from Chroma" if doc["cached"] else "embedded and stored in Chroma",
        "extracted": fields, "extraction_error": fields_error,
        "matched_transaction_id": best["transaction_id"] if best else None,
        "ranking": ranking, "matches": matches, "data": data, "text": text,
    }
    return _public_evidence(EVIDENCE[evidence_id])


@app.get("/api/disputes/evidence/{evidence_id}")
async def read_evidence(evidence_id: str):
    ev = EVIDENCE.get(evidence_id)
    if not ev:
        raise HTTPException(404, "Evidence not found; match it again")
    return _public_evidence(ev)


# ---------------------------------------------------------------- disputes: build package

def _stage(case: dict, name: str, state: str, **detail):
    case["stages"][name] = {"state": state, "at": datetime.now(timezone.utc).isoformat(), **detail}


async def run_pipeline(case_id: str, txn: dict, ev: dict):
    case = DISPUTES[case_id]
    match = case["match"]
    try:
        _stage(case, "generate_letter", "running")
        letter = await generate_letter(txn, match)
        _stage(case, "generate_letter", "done", model=letter["model"], fallback=letter["fallback"])
        case["letter"] = letter

        _stage(case, "render_pdf", "running")
        evidence = {"filename": ev["filename"], "kind": ev["kind"], "method": ev["method"], "data": ev["data"]}
        PACKAGES[case_id] = await asyncio.to_thread(build_chargeback_package, case_id, txn, match, letter, evidence)
        _stage(case, "render_pdf", "done", bytes=len(PACKAGES[case_id]))

        case["status"] = "complete"
        case["package_url"] = f"/api/disputes/cases/{case_id}/package.pdf"
    except Exception as exc:  # noqa: BLE001 - surface any stage failure to the UI
        log.exception("Package build failed for %s", case_id)
        running = next((s for s, v in case["stages"].items() if v["state"] == "running"), None)
        if running:
            _stage(case, running, "failed", error=str(exc))
        case["status"] = "failed"
        case["error"] = str(exc)


@app.post("/api/disputes/cases", status_code=202)
async def create_dispute(transaction_id: str = Form(...), evidence_id: str = Form(...)):
    """Step 2: build the package for matched evidence: gemma3 letter -> ReportLab PDF. The letter is returned in
    the case for review; the PDF is only downloaded when the user asks for it."""
    txn = get_transaction(transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")
    ev = EVIDENCE.get(evidence_id)
    if not ev:
        raise HTTPException(404, "Evidence not found; match it again")
    match = ev["matches"][transaction_id]
    if match["verdict"] not in BUILDABLE_VERDICTS:
        raise HTTPException(409, f"{ev['filename']} does not support this transaction (score {match['score']:.2f}, "
                                 f"{match['verdict']}); a package needs at least a partial match")

    case_id = f"CB-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
    DISPUTES[case_id] = {"case_id": case_id, "transaction_id": transaction_id, "evidence_id": evidence_id,
                         "status": "processing", "created_at": datetime.now(timezone.utc).isoformat(),
                         "stages": {s: {"state": "pending"} for s in PIPELINE_STAGES},
                         "evidence": {k: ev[k] for k in ("filename", "kind", "method", "text_preview")},
                         "match": match}
    task = asyncio.create_task(run_pipeline(case_id, txn, ev))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return DISPUTES[case_id]


@app.get("/api/disputes/cases/{case_id}")
async def read_dispute(case_id: str):
    case = DISPUTES.get(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@app.get("/api/disputes/cases/{case_id}/package.pdf")
async def dispute_package(case_id: str, download: bool = False):
    """Stream the generated chargeback package (inline for the iframe, attachment with ?download=true)."""
    if case_id not in PACKAGES:
        raise HTTPException(404, "Package not ready")
    return _pdf_response(PACKAGES[case_id], f"Legal_Chargeback_Package_{case_id}.pdf", download)


# ---------------------------------------------------------------- card optimizer

RECOMMENDATIONS: dict[str, dict] = {}


@app.get("/api/card-optimizer/payments")
async def card_optimizer_payments():
    """Cross-border payments with their corridor, friction and per-card costs, plus any recommendations made."""
    return {"cards": CARD_PORTFOLIO, "payments": all_analyses(), "recommendations": RECOMMENDATIONS}


@app.delete("/api/card-optimizer/recommendations")
async def card_optimizer_reset():
    """Clear every recommendation so the demo can be run again."""
    cleared = len(RECOMMENDATIONS)
    RECOMMENDATIONS.clear()
    return {"cleared": cleared}


@app.post("/api/card-optimizer/payments/{payment_id}/recommend")
async def card_optimizer_recommend(payment_id: str):
    """Ask the decision model (nimble) for the card and reason code; falls back to gemma3, then the rule engine."""
    analysis = get_analysis(payment_id)
    if not analysis:
        raise HTTPException(404, "Payment not found")
    RECOMMENDATIONS[payment_id] = await recommend(analysis)
    return RECOMMENDATIONS[payment_id]


# ---------------------------------------------------------------- locked modules

@app.api_route("/api/{module}/{rest:path}", methods=["GET", "POST"])
async def locked_module(module: str, rest: str):
    if module in LOCKS:
        return JSONResponse(status_code=423, content={"locked": True, "module": module, "detail": LOCKS[module]})
    raise HTTPException(404, "Not found")
