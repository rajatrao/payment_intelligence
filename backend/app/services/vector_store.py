"""Chroma vector store for evidence embeddings.

EmbeddingGemma 2 is stateless: it turns text or an image into a vector and keeps nothing. This module stores
those vectors in an embedded, on-disk Chroma collection so each document is embedded once:

- one record per PDF text section, or one record per JPEG image;
- documents are keyed by the SHA-256 of their bytes, so re-uploading the same file reuses its vectors;
- records carry the embedding model name, and a document embedded with a different model is re-embedded.

Transaction facets (the queries) are embedded on each match; only evidence is stored.
"""

import hashlib
import json
import logging
from functools import lru_cache

import chromadb

from app.config import settings
from app.services.extraction import chunk_text
from app.services.ollama_client import OllamaUnavailable, embed_image, embed_texts

log = logging.getLogger("vector_store")

COLLECTION = "evidence"
# EmbeddingGemma retrieval prompt for documents; queries use their own prefix in matching.py.
DOC_PREFIX = "title: none | text: "
IMAGE_LABEL = "(image evidence: compared visually by the embedding model; see Exhibit A)"
NO_TEXT_LABEL = "(no text layer in evidence; nothing to match)"


@lru_cache(maxsize=1)
def _collection():
    client = chromadb.PersistentClient(path=str(settings.chroma_dir),
                                       settings=chromadb.Settings(anonymized_telemetry=False))
    # Vectors are supplied by EmbeddingGemma 2, so Chroma's own embedding function is never used.
    return client.get_or_create_collection(COLLECTION, embedding_function=None,
                                           metadata={"hnsw:space": "cosine"})


_BLANK: dict[str, list[float]] = {}


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = sum(x * x for x in a) ** 0.5, sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def _check_image_read(vector: list[float]) -> None:
    """Ollama falls back to embedding the text alone when it can't read an image. Our image items carry empty
    text, so an unread image comes back as the empty-text vector: catch that instead of scoring it."""
    if settings.embed_model not in _BLANK:
        _BLANK[settings.embed_model] = (await embed_texts([""]))[0][0]
    if _cos(vector, _BLANK[settings.embed_model]) > 0.98:
        raise OllamaUnavailable(
            f"Ollama did not read the image: '{settings.embed_model}' returned the same vector as empty text. "
            f"Update Ollama, check that `ollama show {settings.embed_model}` lists the vision capability, and use "
            f"an image-capable tag (latest, :740m or :440m).")


def document_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def _stored(doc_id: str) -> dict | None:
    got = _collection().get(where={"doc_id": doc_id}, include=["embeddings", "documents", "metadatas"])
    if not got["ids"] or any(m.get("model") != settings.embed_model for m in got["metadatas"]):
        return None
    rows = sorted(zip(got["metadatas"], got["documents"], got["embeddings"]), key=lambda r: r[0]["chunk_index"])
    return {"doc_id": doc_id, "kind": rows[0][0]["kind"], "filename": rows[0][0]["filename"],
            "chunks": [d for _, d, _ in rows], "vectors": [list(map(float, e)) for _, _, e in rows],
            "cached": True}


async def index_document(data: bytes, filename: str, kind: str, text: str, source: str) -> dict:
    """Return the document's stored sections and vectors, embedding and storing them first if needed."""
    doc_id = document_id(data)
    if (hit := _stored(doc_id)) is not None:
        if kind != "jpeg":
            return hit
        try:
            await _check_image_read(hit["vectors"][0])
            return hit
        except OllamaUnavailable:
            log.warning("Stored vector for %s looks like an unread image; re-embedding", filename)

    if kind == "jpeg":
        chunks, vectors = [IMAGE_LABEL], [await embed_image(data)]
        await _check_image_read(vectors[0])
    else:
        chunks = chunk_text(text) or [NO_TEXT_LABEL]
        vectors, _ = await embed_texts([DOC_PREFIX + c for c in chunks])

    collection = _collection()
    collection.delete(where={"doc_id": doc_id})  # drop vectors from a previous embedding model
    collection.add(
        ids=[f"{doc_id}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=chunks,
        metadatas=[{"doc_id": doc_id, "chunk_index": i, "kind": kind, "filename": filename, "source": source,
                    "model": settings.embed_model} for i in range(len(chunks))],
    )
    log.info("Indexed %s (%s, %d record(s)) as %s", filename, kind, len(chunks), doc_id)
    return {"doc_id": doc_id, "kind": kind, "filename": filename, "chunks": chunks, "vectors": vectors,
            "cached": False}


def get_fields(doc_id: str) -> dict | None:
    """Fields gemma3 extracted for this document, cached on its first record."""
    got = _collection().get(ids=[f"{doc_id}:0"], include=["metadatas"])
    meta = got["metadatas"][0] if got["ids"] else {}
    if meta.get("fields") and meta.get("fields_model") == settings.llm_model:
        return json.loads(meta["fields"])
    return None


def set_fields(doc_id: str, fields: dict) -> None:
    rid = f"{doc_id}:0"
    got = _collection().get(ids=[rid], include=["metadatas"])
    if got["ids"]:
        meta = {**got["metadatas"][0], "fields": json.dumps(fields), "fields_model": settings.llm_model}
        _collection().update(ids=[rid], metadatas=[meta])


def load(doc_id: str) -> dict | None:
    """A stored document's sections and vectors (None if absent or embedded with another model)."""
    return _stored(doc_id)


def search(query_vectors: list[list[float]], per_query: int = 10) -> list[dict]:
    """Candidate documents for a transaction: nearest records to any facet vector, grouped by document and
    ordered by their best (lowest) cosine distance. Only documents embedded with the current model count."""
    collection = _collection()
    total = collection.count()
    if not total:
        return []
    res = collection.query(query_embeddings=query_vectors, n_results=min(per_query, total),
                           where={"model": settings.embed_model}, include=["metadatas", "distances"])
    best: dict[str, dict] = {}
    for metas, dists in zip(res["metadatas"], res["distances"]):
        for meta, dist in zip(metas, dists):
            hit = best.get(meta["doc_id"])
            if hit is None or dist < hit["distance"]:
                best[meta["doc_id"]] = {"doc_id": meta["doc_id"], "filename": meta["filename"], "kind": meta["kind"],
                                        "source": meta["source"], "distance": round(dist, 4)}
    return sorted(best.values(), key=lambda h: h["distance"])


def stats() -> dict:
    try:
        metas = _collection().get(include=["metadatas"])["metadatas"]
    except Exception as exc:  # noqa: BLE001 - surfaced in /api/health only
        return {"error": str(exc)}
    return {"path": str(settings.chroma_dir), "collection": COLLECTION, "records": len(metas),
            "documents": len({m["doc_id"] for m in metas})}
