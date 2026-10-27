"""Async Ollama client for the Auto-Dispute Concierge dual-model pipeline.

- Embeddings: POST {base}/api/embed {"model": ..., "input": [...]} (text strings, or {"text", "image"} objects)
- Text:       POST {base}/api/generate   {"model": ..., "system": ..., "prompt": ..., "stream": false}
- Fields:     POST {base}/api/generate   {"model": ..., "format": <JSON schema>, "images": [...]}

Embeddings use exactly one model (embeddinggemma-2, multimodal) and fail loudly if it is unavailable.
One language model (gemma3:4b, vision-capable) reads evidence fields and writes letters; the template-letter
fallback lives in letter.py.
"""

import base64
import json
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
        "llm_model": resolve([settings.llm_model]),
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


# ---------------------------------------------------------------- structured extraction

async def generate_json(prompt: str, schema: dict, image_b64: str | None = None) -> dict:
    """Ask the vision model for JSON matching `schema` (Ollama structured outputs). Raises OllamaUnavailable."""
    payload = {"model": settings.llm_model, "prompt": prompt, "format": schema, "stream": False,
               "options": {"temperature": 0}}
    if image_b64:
        payload["images"] = [image_b64]
    try:
        async with _client() as client:
            r = await client.post("/api/generate", json=payload)
    except (httpx.HTTPError, OSError) as exc:
        raise OllamaUnavailable(f"Ollama is unreachable at {settings.ollama_base_url}: {exc}") from exc
    if r.status_code == 404:
        raise OllamaUnavailable(f"Language model '{settings.llm_model}' is not installed in Ollama. "
                                f"Run: ollama pull {settings.llm_model}")
    if r.status_code != 200:
        raise OllamaUnavailable(f"Ollama /api/generate returned {r.status_code} for '{settings.llm_model}': "
                                f"{r.text[:300].strip()}")
    try:
        return json.loads(r.json().get("response") or "{}")
    except ValueError as exc:
        raise OllamaUnavailable(f"'{settings.llm_model}' did not return valid JSON") from exc


async def structured_chat(system: str, prompt: str, schema: dict) -> tuple[dict, str, str]:
    """Structured-JSON chat for the Card Optimizer and Liquidity Guard. Returns (json, model, route).

    Tries the configured structured-primitive endpoint (OLLAMA_NIMBLE_PATH, default /v1/systemone) first. Stock
    Ollama doesn't serve that path, so on 404/405 it falls back to Ollama's native structured outputs
    (POST /api/chat with a JSON-schema `format`). The route actually used is returned so the UI can show it."""
    payload = {"model": settings.llm_model, "stream": False, "format": schema, "options": {"temperature": 0},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    routes = [p for p in (settings.nimble_path, "/api/chat") if p]
    last_error = ""
    try:
        async with _client() as client:
            for route in routes:
                r = await client.post(route, json=payload)
                if r.status_code in (404, 405) and route != "/api/chat":
                    last_error = f"{route} returned {r.status_code}"
                    continue
                if r.status_code == 404:
                    raise OllamaUnavailable(f"Language model '{settings.llm_model}' is not installed in Ollama. "
                                            f"Run: ollama pull {settings.llm_model}")
                if r.status_code != 200:
                    raise OllamaUnavailable(f"Ollama {route} returned {r.status_code}: {r.text[:300].strip()}")
                body = r.json()
                content = ((body.get("message") or {}).get("content") or body.get("response")
                           or ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                try:
                    return json.loads(content), settings.llm_model, route
                except ValueError as exc:
                    raise OllamaUnavailable(f"'{settings.llm_model}' did not return valid JSON") from exc
    except (httpx.HTTPError, OSError) as exc:
        raise OllamaUnavailable(f"Ollama is unreachable at {settings.ollama_base_url}: {exc}") from exc
    raise OllamaUnavailable(last_error or "no structured-output route available")


def image_b64(data: bytes) -> str:
    return _jpeg_b64(data)


# ---------------------------------------------------------------- generation

async def generate(system: str, prompt: str, temperature: float = 0.25) -> tuple[str, str]:
    """Generate text with the language model. Returns (text, model used). Raises OllamaUnavailable."""
    model = settings.llm_model
    payload = {"model": model, "system": system, "prompt": prompt, "stream": False,
               "options": {"temperature": temperature, "num_ctx": 8192}}
    try:
        async with _client() as client:
            r = await client.post("/api/generate", json=payload)
    except (httpx.HTTPError, OSError) as exc:
        raise OllamaUnavailable(f"Ollama is unreachable at {settings.ollama_base_url}: {exc}") from exc
    if r.status_code == 404:
        raise OllamaUnavailable(f"{model}: not installed (run: ollama pull {model})")
    if r.status_code != 200:
        raise OllamaUnavailable(f"{model}: Ollama returned {r.status_code}: {r.text[:200].strip()}")
    text = (r.json().get("response") or "").strip()
    if not text:
        raise OllamaUnavailable(f"{model}: empty response")
    return text, model
