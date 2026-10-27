"""Chargeback argument letter orchestration targeting the local gemma3 model."""

import logging
import re
from datetime import date

from app.config import settings
from app.services.ollama_client import OllamaUnavailable, generate

log = logging.getLogger("letter")

SYSTEM_PROMPT = """You are a Senior Corporate Treasury Compliance Officer with 20 years of experience \
prosecuting card-network chargebacks for a US corporation. You write formal, aggressive, legally precise \
dispute correspondence addressed to the card network's dispute resolution unit.

Hard rules:
- Output ONLY the letter body. No preamble, no commentary, no "Here is", no closing remarks after the signature.
- No markdown: no asterisks, no pound signs, no bullet symbols other than numbered paragraphs like "1.".
- Never invent facts, amounts, dates, names or reference numbers. Use only the facts supplied.
- Never use placeholders such as [Name] or <date>.
- Tone: firm, uncompromising, factual. Assert the cardholder's rights under the network's dispute rules, \
state that the merchant has failed its obligations, and demand a full and immediate reversal of the charge.
- Cite the dispute reason code and the Acquirer Reference Number.
- Refer to the attached evidence as "Exhibit A" and quote the matched evidence where it helps.
- Length: 300 to 450 words."""

FILLER_PATTERNS = [
    r"^(sure|certainly|of course|okay|ok)[,!.].*?\n",
    r"^here(?:'s| is) (?:the|a|your) .*?:\s*\n",
    r"\n+(?:let me know|i hope this|feel free|please note that this letter).*$",
]


def build_prompt(txn: dict, match: dict, today: str) -> str:
    evidence = "\n".join(f'- "{e["text"].replace(chr(10), " ")[:400]}"' for e in match["top_evidence"][:3])
    checks = "; ".join(f'{c["field"]}: {"MATCHED" if c["matched"] else "not found"}' for c in match["field_checks"])
    return f"""Write the chargeback argument letter dated {today}.

Addressee: {txn['card_network']} Dispute Resolution, Chargeback Arbitration Unit

Disputed transaction:
- Merchant (legal): {txn['merchant_legal_name']}, country {txn['merchant_country']}, MCC {txn['mcc']} ({txn['mcc_description']})
- Card statement descriptor: {txn['merchant_descriptor']}
- Amount: {txn['currency']} {txn['amount']:,.2f} (settled USD {txn['settled_amount_usd']:,.2f})
- Authorisation date: {txn['auth_date']}; posting date: {txn['post_date']}
- Card: {txn['card_network']} ending {txn['card_last4']}; authorisation code {txn['auth_code']}
- Acquirer Reference Number (ARN): {txn['arn']}
- Merchant invoice reference: {txn.get('invoice_reference') or 'not provided by merchant'}
- Dispute reason code: {txn['dispute_reason_code']} ({txn['dispute_reason']})
- Internal cardholder statement: {txn.get('memo') or 'none recorded'}

Evidence match (Exhibit A): composite score {match['score']:.0%} ({match['verdict']}); {checks}
Merchant's contractual commitments (strongest excerpt for the dispute reason):
"{match['purpose_evidence']['text'].replace(chr(10), ' ')[:500]}"
Other matched evidence excerpts:
{evidence}

Sign the letter as:
Senior Corporate Treasury Compliance Officer
Treasury Compliance Office"""


def clean_letter(text: str) -> str:
    text = text.strip()
    for pattern in FILLER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r"[*#`]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    return text.strip()


def template_letter(txn: dict, match: dict, today: str) -> str:
    """Deterministic fallback used only when Ollama/gemma3 is unavailable."""
    quoted = match["purpose_evidence"]["text"].replace("\n", " ")[:300]
    statement = (txn.get("memo") or txn["dispute_reason"]).rstrip(". ")
    matched = ", ".join(c["field"].split(" ")[0].lower() for c in match["field_checks"] if c["matched"]) or "none"
    if match.get("mode") == "image":
        exhibit = (f"Exhibit A, an image of the merchant's documentation, has been matched to this transaction by "
                   f"multimodal embedding analysis with a score of {match['score']:.0%}. It is attached in its "
                   f"original form for the network's review.")
    elif match.get("note"):
        exhibit = "Exhibit A, the merchant's documentation, is attached in its original form for the network's review."
    else:
        exhibit = (f"Exhibit A, the merchant's own documentation, has been matched to this transaction with a composite "
                   f"evidence score of {match['score']:.0%} (fields corroborated: {matched}). "
                   f'It reads in relevant part: "{quoted}".')
    return f"""{today}

{txn['card_network']} Dispute Resolution
Chargeback Arbitration Unit

Re: Formal Chargeback Demand, Reason Code {txn['dispute_reason_code']} ({txn['dispute_reason']})
ARN {txn['arn']} | Card ending {txn['card_last4']} | Authorisation {txn['auth_code']}

To the Dispute Resolution Unit:

1. We hereby submit a formal chargeback against {txn['merchant_legal_name']} (descriptor "{txn['merchant_descriptor']}") \
for {txn['currency']} {txn['amount']:,.2f}, authorised on {txn['auth_date']} and settled at USD {txn['settled_amount_usd']:,.2f}.

2. The merchant accepted payment and has failed to perform. Our records state: {statement}. \
No cure, refund, or substantive response has been received.

3. {exhibit}

4. Under the network's dispute rules for reason code {txn['dispute_reason_code']}, the cardholder is entitled to a full \
reversal where contracted services were not provided as agreed. The merchant's documentation establishes both the \
obligation and the amount; its non-performance is uncontested.

5. We demand the immediate and full reversal of {txn['currency']} {txn['amount']:,.2f} to the card account, together \
with any associated foreign transaction fees. Any representment by the acquirer must be accompanied by verifiable proof \
of delivery; absent such proof, we will escalate to pre-arbitration without further notice.

Senior Corporate Treasury Compliance Officer
Treasury Compliance Office"""


async def generate_letter(txn: dict, match: dict) -> dict:
    today = date.today().strftime("%B %d, %Y")
    try:
        raw, model = await generate(SYSTEM_PROMPT, build_prompt(txn, match, today))
        return {"text": clean_letter(raw), "model": model, "fallback": False}
    except OllamaUnavailable as exc:
        if not settings.allow_offline_fallback:
            raise
        log.warning("Letter generation fallback to template: %s", exc)
        return {"text": template_letter(txn, match, today), "model": "template (offline fallback)",
                "fallback": True, "fallback_reason": str(exc)}
