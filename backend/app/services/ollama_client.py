"""Async Ollama client for the Auto-Dispute Concierge dual-model pipeline.

- Embeddings: POST {base}/api/embed {"model": ..., "input": [...]} (text strings, or {"text", "image"} objects)
- Text:       POST {base}/api/generate   {"model": ..., "system": ..., "prompt": ..., "stream": false}

Embeddings use exactly one model (embeddinggemma-2, multimodal) and fail loudly if it is unavailable.
Text generation tries the configured gemma2 tag, then its fallback tags; the template-letter fallback
lives in letter.py.
"""

import base64
import io
import logging

import httpx
from PIL import Image, ImageOps

from app.config import settings

log = logging.getLogger("ollama")

EMBED_BATCH = 16


class OllamaUnavailable(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=settings.request_timeout_s)


async def ollama_status() -> dict:
    """Report reachability and which configured models are actually installed."""
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=3) as client:
            r = await client.get("/api/tags")
            r.raise_for_status()
            installed = {m["name"] for m in r.json().get("models", [])}
    except Exception as exc:  # noqa: BLE001 - any failure means "offline" for the health card
        return {"reachable": False, "base_url": settings.ollama_base_url, "error": str(exc)}

    def resolve(candidates: list[str]) -> str | None:
        for name in candidates:
            if name in installed or f"{name}:latest" in installed:
                return name
        return None

    return {
        "reachable": True,
        "base_url": settings.ollama_base_url,
        "text_model": resolve([settings.text_model, *settings.text_model_fallbacks]),
        "embed_model": resolve([settings.embed_model]),
        "installed": sorted(installed),
    }


# ---------------------------------------------------------------- embeddings

def _embed_error(r: httpx.Response) -> OllamaUnavailable:
    if r.status_code == 404:
        return OllamaUnavailable(f"Embedding model '{settings.embed_model}' is not installed in Ollama. "
                                 f"Run: ollama pull {settings.embed_model}")
    detail = r.text[:300].strip()
    return OllamaUnavailable(f"Ollama /api/embed returned {r.status_code} for '{settings.embed_model}': {detail}")


async def _embed(inputs: list) -> list[list[float]]:
    """POST /api/embed. Inputs are strings, or {"text", "image"} objects for image embeddings."""
    vectors: list[list[float]] = []
    try:
        async with _client() as client:
            for i in range(0, len(inputs), EMBED_BATCH):
                r = await client.post("/api/embed", json={"model": settings.embed_model, "input": inputs[i:i + EMBED_BATCH]})
                if r.status_code != 200:
                    raise _embed_error(r)
                batch = r.json().get("embeddings") or []
                if len(batch) != len(inputs[i:i + EMBED_BATCH]) or not all(batch):
                    raise OllamaUnavailable(f"Embedding model '{settings.embed_model}' returned no vectors.")
                vectors.extend(batch)
    except (httpx.HTTPError, OSError) as exc:
        raise OllamaUnavailable(f"Ollama is unreachable at {settings.ollama_base_url}: {exc}") from exc
    return vectors


async def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    """Embed texts with the configured model (embeddinggemma-2). No substitutes: if the model or Ollama is
    unavailable this raises, and the case fails with that reason."""
    return await _embed(texts), settings.embed_model


def _jpeg_b64(data: bytes, max_side: int = 1024) -> str:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


async def embed_image(data: bytes) -> list[float]:
    """Embed an image into the same space as the text facets. Requires an image-capable tag
    (embeddinggemma-2, :740m or :440m; the :270m and :570m tags are text-only)."""
    vectors = await _embed([{"text": "", "image": _jpeg_b64(data)}])
    return vectors[0]


# ---------------------------------------------------------------- generation

async def generate(system: str, prompt: str, temperature: float = 0.25) -> tuple[str, str]:
    """Generate text. Returns (text, model used). Raises OllamaUnavailable if nothing works."""
    errors: list[str] = []
    payload = {"system": system, "prompt": prompt, "stream": False,
               "options": {"temperature": temperature, "num_ctx": 8192}}
    try:
        async with _client() as client:
            for model in [settings.text_model, *settings.text_model_fallbacks]:
                r = await client.post("/api/generate", json={**payload, "model": model})
                if r.status_code == 404:
                    errors.append(f"{model}: not installed")
                    continue
                r.raise_for_status()
                text = (r.json().get("response") or "").strip()
                if text:
                    return text, model
                errors.append(f"{model}: empty response")
    except (httpx.HTTPError, OSError) as exc:
        errors.append(f"unreachable: {exc}")
    raise OllamaUnavailable("; ".join(errors))
