"""Liquidity Guard: classify each bill line as a variable usage-based consumption line, or not.

The classification is made by Ollama's decision API (/v1/systemone, decision model nimble) with one `noul`
question per line: nimble returns the probability that the line is variable usage-based consumption. A
probability of 0.5 or more counts as variable. Each question carries only the invoice line text and its charge
history; nothing tells nimble the answer. If the decision API is unavailable, gemma3 structured outputs give a
true/false per line; if neither is available, the keyword rule in liquidity.py is used. The rule's answer is
always shown next to the model's as a second opinion, never in its place.
"""

import json

from app.config import settings
from app.data.transactions.recurring import CYCLE
from app.services.ollama_client import OllamaUnavailable, decide, structured_chat

DEFINITION = ("A variable usage-based consumption line is charged by metered usage (compute hours, data "
              "transferred or stored, queries, requests, tokens, credits, messages, impressions or clicks), so "
              "the amount moves with consumption. A fixed seat, licence, membership, subscription or committed "
              "fee is not, even when it appears on a cloud bill.")


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _line_text(line: dict) -> str:
    hist = ", ".join(_money(h) for h in line["history"])
    return (f"Invoice line: \"{line['description']}\". Last 3 cycles: {hist}. This cycle so far: "
            f"{_money(line['mtd'])} after {CYCLE['days_elapsed']} of {CYCLE['days']} days.")


def _state(bill: dict) -> dict:
    return {"vendor": bill["vendor"], "descriptor": bill["descriptor"], "auto_debit_date": bill["debit_date"],
            "definition": DEFINITION}


def _questions(bill: dict) -> dict:
    return {line["id"]: {"type": "noul",
                         "instructions": f"{_line_text(line)} Is this a variable usage-based consumption line?"}
            for line in bill["lines"]}


SYSTEM_PROMPT = ("You are a treasury analyst reviewing vendor bills before they auto-debit. For each invoice line, "
                 "answer true if it is a variable usage-based consumption line, false otherwise.\n\n" + DEFINITION)


def _schema(bill: dict) -> dict:
    ids = [line["id"] for line in bill["lines"]]
    return {"type": "object", "properties": {i: {"type": "boolean"} for i in ids}, "required": ids}


def _prompt(bill: dict) -> str:
    lines = "\n".join(f"- {line['id']}: {_line_text(line)}" for line in bill["lines"])
    return f"Vendor: {bill['vendor']} ({bill['descriptor']}), auto-debit {bill['debit_date']}\n\n{lines}"


async def classify(bill: dict) -> dict:
    notes = []
    probabilities: dict[str, float | None] = {}
    try:
        answers = await decide(_state(bill), _questions(bill))
        probabilities = {i: float(a.get("noul")) for i, a in answers.items() if a.get("noul") is not None}
        if set(probabilities) != {line["id"] for line in bill["lines"]}:
            raise OllamaUnavailable(f"{settings.nimble_path} returned no probability for some lines")
        variable = {i: p >= 0.5 for i, p in probabilities.items()}
        source, model, route = "decision model", settings.decision_model, settings.nimble_path
    except OllamaUnavailable as exc:
        notes.append(f"Decision API unavailable: {exc}")
        probabilities = {}
        try:
            out = await structured_chat(SYSTEM_PROMPT, _prompt(bill), _schema(bill))
            variable = {line["id"]: bool(out.get(line["id"])) for line in bill["lines"]}
            source, model, route = "language model", settings.llm_model, "/api/chat"
        except OllamaUnavailable as exc2:
            notes.append(f"gemma3 unavailable: {exc2}")
            variable = {line["id"]: line["rule"]["variable"] for line in bill["lines"]}
            source, model, route = "rules (models unavailable)", "rules", None

    lines = {line["id"]: {"variable": variable[line["id"]], "probability": probabilities.get(line["id"]),
                          "rule": line["rule"], "agrees_with_rules": variable[line["id"]] == line["rule"]["variable"]}
             for line in bill["lines"]}
    return {"bill_id": bill["id"], "lines": lines, "source": source, "model": model, "route": route,
            "notes": notes, "agreements": sum(1 for l in lines.values() if l["agrees_with_rules"])}


def flat(classifications: dict[str, dict]) -> dict[str, bool]:
    """line id -> variable, across every classified bill."""
    return {line_id: l["variable"] for c in classifications.values() for line_id, l in c["lines"].items()}
