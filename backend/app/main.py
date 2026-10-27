"""Payment Intelligence API.

Modules:
- Auto-Dispute Concierge (/api/disputes): live.
- Card Optimizer (/api/card-optimizer) and Liquidity Guard (/api/liquidity-guard): not yet available; respond 423.
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
from app.services.letter import generate_letter
from app.services.matching import match_evidence
from app.services.ollama_client import OllamaUnavailable, ollama_status
from app.services.pdf_builder import build_chargeback_package
from app.services.samples import DEFAULT_SAMPLE_ID, get_sample, sample_bytes, sample_metadata
from app.services import vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="Payment Intelligence", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PIPELINE_STAGES = ["extract", "embed_match", "generate_letter", "render_pdf"]
LOCKS = {
    "card-optimizer": "The Card Optimizer module is not available yet.",
    "liquidity-guard": "The Liquidity Guard module is not available yet.",
}

# In-memory case store; fine for a single-process local demo.
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
            "config": {"text_model": settings.text_model, "embed_model": settings.embed_model,
                       "nimble_path": settings.nimble_path, "offline_fallback": settings.allow_offline_fallback}}


@app.get("/api/modules")
async def modules():
    return [
        {"id": "disputes", "name": "Auto-Dispute Concierge", "locked": False},
        *({"id": module, "name": name, "locked": True, "lock_message": LOCKS[module]}
          for module, name in (("card-optimizer", "Card Optimizer"), ("liquidity-guard", "Liquidity Guard"))),
    ]


# ---------------------------------------------------------------- disputes: transactions

@app.get("/api/disputes/transactions")
async def list_transactions():
    return {"sample_transaction_id": SAMPLE_TRANSACTION_ID, "transactions": DISPUTE_TRANSACTIONS}


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


@app.get("/api/disputes/samples/scores")
async def score_samples(transaction_id: str):
    """Match one transaction against every sample with EmbeddingGemma 2 (no letter, no PDF)."""
    txn = get_transaction(transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")

    async def score(sample: dict) -> dict:
        data = sample_bytes(sample["id"])
        text, _ = await asyncio.to_thread(extract_text, sample["kind"], data)
        doc = await vector_store.index_document(data, sample["filename"], sample["kind"], text, "sample")
        m = await match_evidence(txn, doc, text)
        return {"sample_id": sample["id"], "score": m["score"], "semantic_score": m["semantic_score"],
                "field_score": m["field_score"], "verdict": m["verdict"]}

    try:
        results = [await score(s) for s in sample_metadata()]
    except OllamaUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"transaction_id": transaction_id, "embedding_model": settings.embed_model, "scores": results}


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


# ---------------------------------------------------------------- disputes: case pipeline

def _stage(case: dict, name: str, state: str, **detail):
    case["stages"][name] = {"state": state, "at": datetime.now(timezone.utc).isoformat(), **detail}


async def run_pipeline(case_id: str, txn: dict, filename: str, kind: str, data: bytes, source: str):
    case = DISPUTES[case_id]
    try:
        _stage(case, "extract", "running")
        text, method = await asyncio.to_thread(extract_text, kind, data)
        _stage(case, "extract", "done", method=method, characters=len(text))
        case["evidence"] = {"filename": filename, "kind": kind, "method": method, "text_preview": text[:1500]}

        _stage(case, "embed_match", "running")
        doc = await vector_store.index_document(data, filename, kind, text, source)
        match = await match_evidence(txn, doc, text)
        _stage(case, "embed_match", "done", model=match["embedding_model"], doc_id=doc["doc_id"],
               vectors="reused from Chroma" if doc["cached"] else "embedded and stored in Chroma")
        case["match"] = match

        _stage(case, "generate_letter", "running")
        letter = await generate_letter(txn, match)
        _stage(case, "generate_letter", "done", model=letter["model"], fallback=letter["fallback"])
        case["letter"] = letter

        _stage(case, "render_pdf", "running")
        evidence = {"filename": filename, "kind": kind, "method": method, "data": data}
        PACKAGES[case_id] = await asyncio.to_thread(build_chargeback_package, case_id, txn, match, letter, evidence)
        _stage(case, "render_pdf", "done", bytes=len(PACKAGES[case_id]))

        case["status"] = "complete"
        case["package_url"] = f"/api/disputes/cases/{case_id}/package.pdf"
    except Exception as exc:  # noqa: BLE001 - surface any stage failure to the UI
        log.exception("Dispute pipeline failed for %s", case_id)
        running = next((s for s, v in case["stages"].items() if v["state"] == "running"), None)
        if running:
            _stage(case, running, "failed", error=str(exc))
        case["status"] = "failed"
        case["error"] = str(exc)


@app.post("/api/disputes/cases", status_code=202)
async def create_dispute(transaction_id: str = Form(...), file: UploadFile | None = File(None),
                         sample_id: str | None = Form(None), use_sample: bool = Form(False)):
    """Start the async pipeline: extract -> embed & match -> gemma2 letter -> ReportLab package."""
    txn = get_transaction(transaction_id)
    if not txn:
        raise HTTPException(404, "Transaction not found")

    if file is not None and file.filename:
        data = await file.read()
        filename, source = file.filename, "upload"
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Evidence file exceeds 15 MB")
        try:
            kind = detect_kind(filename, file.content_type, data)
        except ValueError as exc:
            raise HTTPException(415, str(exc)) from exc
    elif sample_id or use_sample:
        sample = _sample_or_404(sample_id or DEFAULT_SAMPLE_ID)
        data, filename, kind = sample_bytes(sample["id"]), sample["filename"], sample["kind"]
        source = "sample"
    else:
        raise HTTPException(400, "Upload a PDF/JPEG evidence file, or pass sample_id")

    case_id = f"CB-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
    DISPUTES[case_id] = {"case_id": case_id, "transaction_id": transaction_id, "status": "processing",
                         "created_at": datetime.now(timezone.utc).isoformat(),
                         "stages": {s: {"state": "pending"} for s in PIPELINE_STAGES}}
    task = asyncio.create_task(run_pipeline(case_id, txn, filename, kind, data, source))
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


# ---------------------------------------------------------------- locked modules

@app.api_route("/api/{module}/{rest:path}", methods=["GET", "POST"])
async def locked_module(module: str, rest: str):
    if module in LOCKS:
        return JSONResponse(status_code=423, content={"locked": True, "module": module, "detail": LOCKS[module]})
    raise HTTPException(404, "Not found")
