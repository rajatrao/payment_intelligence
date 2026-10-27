"""Test setup: run from backend/ with `python -m pytest`. No Ollama needed; every model call is faked."""

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="pi-tests-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("CHROMA_DIR", str(Path(_tmp) / "chroma"))
os.environ.setdefault("OLLAMA_BASE_URL", "http://ollama.test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
