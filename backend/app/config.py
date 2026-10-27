"""Runtime configuration, read once from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _csv(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Ollama runs on the host machine; containers reach it via host.docker.internal.
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")


    # Auto-Dispute Concierge: evidence matching via /api/embed with EmbeddingGemma 2 (multimodal: text and images share one
    # vector space). Use an image-capable tag: embeddinggemma-2 (= :740m) or :440m. Only this model is used for
    # matching; there is no substitute embedder.
    embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma-2")

    # Auto-Dispute Concierge: one vision-capable language model reads merchant, amount, date and reference from
    # PDF text and photos (exact checks then compare them with the transaction) and writes the dispute letter.
    llm_model: str = os.getenv("OLLAMA_LLM_MODEL", "gemma3:4b")

    # Card Optimizer & Liquidity Guard (not yet available): structured-primitive endpoint. Declared here so the wiring is visible.
    nimble_path: str = os.getenv("OLLAMA_NIMBLE_PATH", "/v1/systemone")

    request_timeout_s: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
    # Letter generation only: "false" fails the case instead of using the template letter.
    allow_offline_fallback: bool = os.getenv("ALLOW_OFFLINE_FALLBACK", "true").lower() != "false"

    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "/tmp/payment_intelligence"))
    # Embedded Chroma database for evidence embeddings (a Docker volume in docker-compose.yml).
    chroma_dir: Path = Path(os.getenv("CHROMA_DIR", "/tmp/payment_intelligence/chroma"))
    cors_origins: list[str] = field(default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"))


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
