"""Card Optimizer: recommend how to route a cross-border payment, with a programmatic reason code.

corridor.py computes the facts (corridor, friction, each card's fees and eligibility). The decision is made by
Ollama's decision API (/v1/systemone, decision model nimble): two choice questions, one for the reason code and
one for the card, each answered with a probability per option. A decision model writes no text, so the action and
rationale are filled in from the facts. If the decision API is unavailable, gemma3 structured outputs make the
same choice; if neither is available, the rule engine's answer is used. The answer is always checked against the
deterministic rule, and savings always come from corridor.py, never from a model.
"""

import json

from app.config import settings
from app.data.transactions.cross_border import CARD_PORTFOLIO
from app.services.corridor import CARDS, NO_CHANGE, REASON_CODES, savings
from app.services.ollama_client import OllamaUnavailable, decide, structured_chat

# The decision model gets the payment and the card portfolio as plain facts (decline code and text, corridor, what
# each card holds, its region, exemption and fees) and makes the judgement itself, in two steps: first it picks the
# card, then it classifies what moving to that card fixes. Nothing tells it which answer is right; the rule
# engine's answer is only shown next to it for comparison.
#
# Why two steps: asked "what's wrong with this payment?" on its own, nimble read every settled payment as fine
# (NO_CHANGE) even when it picked a card that saved over 200 USD. Classifying a concrete switch, with that card's
# fees in view, is the kind of question a decision model answers well.
REASON_CRITERIA = {
    "SCA_BYPASS_CORRIDOR": "The payment was declined or is held for 3-D Secure / SCA authentication (for example "
                           "code 1A or 65, or a pending 3DS challenge), and the switch moves it to a card with the "
                           "corporate SCA exemption in the merchant's region, so no challenge is raised.",
    "FX_INTERBANK_MATCH": "The payment went through, the current card charged an FX fee above 0%, and the proposed "
                          "card holds the payment currency, so the switch removes the FX markup and saves 10 USD or "
                          "more (it may remove a cross-border fee too).",
    "INTER-REGIONAL_ROUTING": "The payment was blocked as a cross-region payment (for example code 05), or it went "
                              "through with a 0% FX fee and the switch only removes a cross-border fee by using a "
                              "card from the merchant's region, saving 10 USD or more.",
    NO_CHANGE: "The payment went through and the switch saves less than 10 USD, so it isn't worth changing cards.",
}

REASON_QUESTION = "This payment is being moved to the proposed card. Which reason code describes what the switch fixes?"
CARD_QUESTION = ("Which company card should this payment be retried or paid on? Choose the card that fixes the "
                 "problem at the lowest fee. A card that already failed on this payment won't work.")

SYSTEM_PROMPT = ("You are a corporate treasury payments engineer optimising card routing for cross-border payments. "
                 "Choose one reason code and one card.\n\nReason codes:\n"
                 + "\n".join(f"- {k}: {v}" for k, v in REASON_CRITERIA.items())
                 + "\n\nNever invent fees or cards.")

SCHEMA = {
    "type": "object",
    "properties": {
        "reason_code": {"type": "string", "enum": [*REASON_CODES, NO_CHANGE]},
        "recommended_card_id": {"type": "string", "enum": [c["id"] for c in CARD_PORTFOLIO]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["reason_code", "recommended_card_id", "confidence"],
}

ACTIONS = {
    "SCA_BYPASS_CORRIDOR": "Retry on {card} under the secure corporate payment exemption.",
    "FX_INTERBANK_MATCH": "Pay {merchant} from {card}, which holds {currency}.",
    "INTER-REGIONAL_ROUTING": "Route {merchant} through {card}, issued in the merchant's region.",
    NO_CHANGE: "Keep the current card.",
}


def _state(analysis: dict) -> dict:
    t, c = analysis["transaction"], analysis["corridor"]
    current = next(o for o in analysis["options"] if o["current"])
    payment = {k: t.get(k) for k in ("merchant", "mcc", "amount", "currency", "amount_usd", "status",
                                     "decline_code", "decline_text", "memo")}
    return {"payment": payment,
            "corridor": f"card issued in {c['issuer_country']} ({c['issuer_region']}), merchant in "
                        f"{c['merchant_country']} ({c['merchant_region']})",
            "current_card": current["name"],
            "current_card_fees": f"{current['fx_bps'] / 100:.2f}% FX + {current['cross_border_bps'] / 100:.2f}% "
                                 f"cross-border = {current['fee_usd']:.2f} USD"}


def _card_line(o: dict, analysis: dict) -> str:
    """Facts about one card on this payment. No verdict: the model decides whether it fits."""
    card, t, c = CARDS[o["card_id"]], analysis["transaction"], analysis["corridor"]
    current = next(x for x in analysis["options"] if x["current"])
    line = (f"{o['name']}{' (current card)' if o['current'] else ''}: issued in {o['issuer_country']} ({o['region']}"
            f"{', same region as the merchant' if o['region'] == c['merchant_region'] else ''}), holds "
            f"{'/'.join(card['currencies'])}, corporate SCA exemption: {'yes' if card['sca_exemption'] else 'no'}, "
            f"fees on this payment {o['fx_bps'] / 100:.2f}% FX + {o['cross_border_bps'] / 100:.2f}% cross-border = "
            f"{o['fee_usd']:.2f} USD")
    if not o["current"]:
        line += f", {current['fee_usd'] - o['fee_usd']:.2f} USD less than the current card"
    if o["current"] and analysis["signals"]["failed"]:
        line += f", already {t['status'].lower().replace('_', ' ')} on this payment"
    return line


def _card_question(analysis: dict) -> dict:
    return {"card": {"type": "choice", "instructions": CARD_QUESTION,
                     "criteria": {o["card_id"]: _card_line(o, analysis) for o in analysis["options"]}}}


def _reason_question() -> dict:
    return {"reason_code": {"type": "choice", "instructions": REASON_QUESTION, "criteria": REASON_CRITERIA}}


def _prompt(analysis: dict) -> str:
    cards = "\n".join(f"- {o['card_id']}: {_card_line(o, analysis)}" for o in analysis["options"])
    return f"Payment:\n{json.dumps(_state(analysis), indent=1)}\n\nCards:\n{cards}"


def _explain(analysis: dict, reason_code: str, card_id: str | None) -> tuple[str, str]:
    """Action and rationale written from the facts, so every number shown comes from corridor.py."""
    t = analysis["transaction"]
    current = next(o for o in analysis["options"] if o["current"])
    card = next((o for o in analysis["options"] if o["card_id"] == card_id), None) or current
    if analysis["signals"]["failed"]:
        what = t["status"].replace("_", " ").capitalize() + (f" with code {t['decline_code']}" if t["decline_code"] else "")
        what += f" ({t['decline_text']})" if t["decline_text"] else ""
    else:
        fees = [f"{bps / 100:.2f}% {label}" for bps, label in ((current["fx_bps"], "FX"),
                                                                (current["cross_border_bps"], "cross-border")) if bps]
        what = f"Settled with {' and '.join(fees) or 'no'} fees ({current['fee_usd']:.2f} USD)"
    action = ACTIONS[reason_code].format(card=card["name"], merchant=t["merchant"], currency=t["currency"])
    if reason_code == NO_CHANGE:
        return action, f"{what}. Judged not worth switching cards."
    return action, (f"{what} on {current['name']}. {card['name']} is issued in {card['issuer_country']} "
                    f"({card['region']}) and costs {card['fee_usd']:.2f} USD here.")


async def _decide(analysis: dict) -> dict:
    """Step 1: nimble picks the card. Step 2: nimble classifies the switch to that card."""
    state = _state(analysis)
    card = (await decide(state, _card_question(analysis)))["card"]
    card_id = card.get("choice")
    option = next((o for o in analysis["options"] if o["card_id"] == card_id), None)
    out = {"recommended_card_id": card_id, "card_probabilities": card.get("probabilities") or {}}
    if option is None or option["current"]:
        # nimble kept the current card, which is what NO_CHANGE means; there is no switch to classify.
        return {**out, "reason_code": NO_CHANGE, "confidence": card.get("confidence"), "probabilities": {}}
    current = next(o for o in analysis["options"] if o["current"])
    switch = {**state, "proposed_switch": {"from": _card_line(current, analysis), "to": _card_line(option, analysis)}}
    reason = (await decide(switch, _reason_question()))["reason_code"]
    return {**out, "reason_code": reason.get("choice"), "confidence": reason.get("confidence"),
            "probabilities": reason.get("probabilities") or {}}


async def recommend(analysis: dict) -> dict:
    rule = analysis["rule"]
    notes = []
    try:
        out = await _decide(analysis)
        source, model, route = "decision model", settings.decision_model, settings.nimble_path
    except OllamaUnavailable as exc:
        notes.append(f"Decision API unavailable: {exc}")
        try:
            out = await structured_chat(SYSTEM_PROMPT, _prompt(analysis), SCHEMA)
            source, model, route = "language model", settings.llm_model, "/api/chat"
        except OllamaUnavailable as exc2:
            notes.append(f"gemma3 unavailable: {exc2}")
            out = {"reason_code": rule["reason_code"], "recommended_card_id": rule["card_id"], "confidence": None}
            source, model, route = "rules (models unavailable)", "rules", None

    # The model's answer is shown as given. The rule engine is a second opinion: disagreements and a card it
    # thinks can't clear the friction are flagged, never overwritten.
    agrees = out["reason_code"] == rule["reason_code"] and (rule["reason_code"] == NO_CHANGE
                                                             or out.get("recommended_card_id") == rule["card_id"])
    option = next((o for o in analysis["options"] if o["card_id"] == out.get("recommended_card_id")), None)
    warnings = []
    if out["reason_code"] != NO_CHANGE and option and not option["eligible"]:
        warnings.append(f"Rule engine: {option['name']} {'; '.join(option['issues'])}, so no payment is counted "
                        "as recovered")
    card_id = out.get("recommended_card_id") if out["reason_code"] != NO_CHANGE else None
    action, rationale = _explain(analysis, out["reason_code"], card_id)
    return {
        "transaction_id": analysis["transaction"]["id"],
        "reason_code": out["reason_code"],
        "recommended_card_id": out.get("recommended_card_id"),
        "recommended_card": option["name"] if option else None,
        "action": action,
        "rationale": rationale,
        "confidence": out.get("confidence"),
        "probabilities": out.get("probabilities") or {},
        "card_probabilities": out.get("card_probabilities") or {},
        "source": source, "model": model, "route": route, "notes": notes,
        "rule": rule,
        "agrees_with_rules": agrees,
        "warnings": warnings,
        **savings(analysis, card_id),
    }
