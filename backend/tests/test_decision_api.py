"""ollama_client.decide: the HTTP contract with Ollama's decision API (POST /v1/systemone)."""

import asyncio
import json

import httpx
import pytest

from app.services import ollama_client
from app.services.ollama_client import OllamaUnavailable, decide

QUESTIONS = {"card": {"type": "choice", "instructions": "Which card?", "criteria": {"a": "card a", "b": "card b"}}}


def _fake_ollama(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(ollama_client, "_client", lambda: httpx.AsyncClient(
        base_url="http://ollama.test", transport=httpx.MockTransport(wrapped)))
    return seen


def test_sends_model_state_and_questions_and_returns_answers(monkeypatch):
    answers = {"card": {"type": "choice", "choice": "b", "probabilities": {"a": 0.1, "b": 0.9}, "confidence": 0.8}}
    seen = _fake_ollama(monkeypatch, lambda r: httpx.Response(200, json={"model": "nimble", "answers": answers}))
    assert asyncio.run(decide({"payment": {"amount": 1}}, QUESTIONS)) == answers
    assert seen[0].method == "POST" and seen[0].url.path == "/v1/systemone"
    assert json.loads(seen[0].content) == {"model": "nimble", "state": {"payment": {"amount": 1}},
                                           "questions": QUESTIONS}


@pytest.mark.parametrize("body, message", [
    ({"error": "model 'nimble' not found"}, "ollama pull nimble"),
    ({"error": "404 page not found"}, "needs Ollama 0.35 or newer"),
])
def test_404_says_what_to_install(monkeypatch, body, message):
    _fake_ollama(monkeypatch, lambda r: httpx.Response(404, json=body))
    with pytest.raises(OllamaUnavailable, match=message):
        asyncio.run(decide({}, QUESTIONS))


def test_missing_answer_is_an_error(monkeypatch):
    _fake_ollama(monkeypatch, lambda r: httpx.Response(200, json={"answers": {}}))
    with pytest.raises(OllamaUnavailable, match="no answers"):
        asyncio.run(decide({}, QUESTIONS))


def test_unreachable_ollama(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    _fake_ollama(monkeypatch, refuse)
    with pytest.raises(OllamaUnavailable, match="unreachable"):
        asyncio.run(decide({}, QUESTIONS))
