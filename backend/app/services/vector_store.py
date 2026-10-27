"""Chroma vector store for evidence embeddings.

EmbeddingGemma 2 is stateless: it turns text or an image into a vector and keeps nothing. This module stores
those vectors in an embedded, on-disk Chroma collection so each document is embedded once:

- one record per PDF text section, or one record per JPEG image;
- documents are keyed by the SHA-256 of their bytes, so re-uploading the same file reuses its vectors;
- records carry the embedding model name, and a document embedded with a different model is re-embedded.

Transaction facets (the queries) are embedded on each match; only evidence is stored.
"""

import hashlib
import logging
from functools import lru_cache

import chromadb

from app.config import settings
from app.services.extraction import chunk_text
from app.services.ollama_client import embed_image, embed_texts

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
        return hit

    if kind == "jpeg":
        chunks, vectors = [IMAGE_LABEL], [await embed_image(data)]
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


def stats() -> dict:
    try:
        metas = _collection().get(include=["metadatas"])["metadatas"]
    except Exception as exc:  # noqa: BLE001 - surfaced in /api/health only
        return {"error": str(exc)}
    return {"path": str(settings.chroma_dir), "collection": COLLECTION, "records": len(metas),
            "documents": len({m["doc_id"] for m in metas})}
