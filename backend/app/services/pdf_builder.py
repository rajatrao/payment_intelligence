"""ReportLab PDF generation: the sample merchant invoice and the legal chargeback package."""

import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

SLATE_900 = colors.HexColor("#0f172a")
SLATE_600 = colors.HexColor("#475569")
SLATE_200 = colors.HexColor("#e2e8f0")
SLATE_50 = colors.HexColor("#f8fafc")
EMERALD = colors.HexColor("#059669")
AMBER = colors.HexColor("#d97706")
RED = colors.HexColor("#dc2626")

_base = getSampleStyleSheet()
STYLES = {
    "h1": ParagraphStyle("h1", parent=_base["Heading1"], fontName="Helvetica-Bold", fontSize=17,
                         textColor=SLATE_900, spaceAfter=2),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold", fontSize=11,
                         textColor=SLATE_900, spaceBefore=10, spaceAfter=6),
    "body": ParagraphStyle("body", parent=_base["BodyText"], fontName="Helvetica", fontSize=9.5,
                           leading=13.5, textColor=SLATE_900),
    "letter": ParagraphStyle("letter", parent=_base["BodyText"], fontName="Times-Roman", fontSize=11,
                             leading=15.5, textColor=colors.black, spaceAfter=7),
    "small": ParagraphStyle("small", parent=_base["BodyText"], fontName="Helvetica", fontSize=7.5,
                            leading=10, textColor=SLATE_600),
    "mono": ParagraphStyle("mono", parent=_base["BodyText"], fontName="Courier", fontSize=8, leading=10.5,
                           textColor=SLATE_900),
    "right": ParagraphStyle("right", parent=_base["BodyText"], fontName="Helvetica", fontSize=9.5,
                            alignment=TA_RIGHT),
}


def _p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), STYLES[style])


def _grid(rows, col_widths, header=True, zebra=True) -> Table:
    t = Table(rows, colWidths=col_widths, hAlign="LEFT")
    cmds = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), SLATE_900),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, SLATE_200),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        cmds += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (-1, 0), SLATE_600),
                 ("BACKGROUND", (0, 0), (-1, 0), SLATE_50)]
    if zebra:
        for r in range(1 if header else 0, len(rows)):
            if r % 2 == 0:
                cmds.append(("BACKGROUND", (0, r), (-1, r), SLATE_50))
    t.setStyle(TableStyle(cmds))
    return t


# ---------------------------------------------------------------- sample invoice

SAMPLE_INVOICE_LINES = [
    ("Programmatic display, DACH region (CPM, guaranteed delivery)", 8200.00),
    ("Programmatic display, Nordics region (CPM, guaranteed delivery)", 6150.00),
    ("Creative adaptation, 12 IAB formats x 3 languages", 2600.00),
    ("Campaign setup, trafficking & brand-safety configuration", 1500.00),
]


def build_sample_invoice() -> bytes:
    """Mock invoice from EUROSITES ADVERTISING LTD matching transaction txn_9f3a71c2 (USD 18,450.00)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="EUROSITES ADVERTISING - Invoice ESA-INV-2026-0912",
                            author="EUROSITES ADVERTISING LTD",
                            invariant=1)  # byte-stable output, so the file hashes to the same Chroma doc_id
    total = sum(a for _, a in SAMPLE_INVOICE_LINES)
    story = [
        Table([[_p("EUROSITES ADVERTISING LTD", "h1"), _p("INVOICE", "h1")],
               [_p("71 Clerkenwell Road, London EC1R 5BL, United Kingdom\nVAT GB 284 1196 07 | Company No. 10984412"
                   "\nbilling@eurosites-advertising.co.uk", "small"),
                _p("Invoice No: ESA-INV-2026-0912\nInvoice Date: 12/09/2026\nPayment: Corporate card on receipt",
                   "small")]],
              colWidths=[115 * mm, 59 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]),
        Spacer(1, 8 * mm),
        _p("Bill To", "h2"),
        _p("Northstar Robotics, Inc. - Marketing Department\nAttn: Priya Raman, Head of Growth\n"
           "500 Howard Street, Suite 400, San Francisco, CA 94105, USA"),
        Spacer(1, 6 * mm),
        _p("Insertion Order IO-ESA-55821: Q4 Programmatic Display Campaign (DACH + Nordics)", "h2"),
        _grid([["Description", "Amount (USD)"]] +
              [[_p(d), f"{a:,.2f}"] for d, a in SAMPLE_INVOICE_LINES] +
              [["Subtotal", f"{total:,.2f}"], ["VAT (outside scope: services supplied to a US business)", "0.00"],
               ["TOTAL DUE (USD)", f"{total:,.2f}"]],
              [134 * mm, 40 * mm]),
        Spacer(1, 6 * mm),
        _p("Service Commitments", "h2"),
        _p("1. Campaign go-live date: 20 September 2026.\n"
           "2. Guaranteed delivery: 4,500,000 viewable impressions (MRC standard) by 31 October 2026.\n"
           "3. Weekly delivery and viewability reports supplied every Monday from go-live.\n"
           "4. Under-delivery greater than 10% entitles the client to a pro-rata refund within 14 days.\n"
           "5. Insertion order confirmation and trafficking sheet issued within 3 business days of payment."),
        Spacer(1, 6 * mm),
        _p("Amount of USD 18,450.00 will appear on your card statement as EUROSITES ADV*LDN. "
           "Thank you for your business.", "small"),
    ]
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- chargeback package

def _score_color(score: float):
    return EMERALD if score >= 0.7 else AMBER if score >= 0.45 else RED


def _footer(case_id: str, letter_meta: dict):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(SLATE_600)
        canvas.drawString(18 * mm, 10 * mm, f"Legal Chargeback Package | Case {case_id} | CONFIDENTIAL")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm,
                               f"Letter: {letter_meta['model']} | Page {doc.page}")
        canvas.restoreState()
    return draw


def build_chargeback_package(case_id: str, txn: dict, match: dict, letter: dict, evidence: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"Legal Chargeback Package {case_id}",
                            author="Treasury Compliance Office")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    score_color = _score_color(match["score"])

    header = Table(
        [[_p("LEGAL CHARGEBACK PACKAGE", "h1"), _p(f"Case {case_id}\nGenerated {generated}", "right")],
         [_p(f"{txn['card_network']} reason code {txn['dispute_reason_code']}: {txn['dispute_reason']}", "small"), ""]],
        colWidths=[120 * mm, 54 * mm],
        style=[("LINEBELOW", (0, 1), (-1, 1), 1.5, SLATE_900), ("VALIGN", (0, 0), (-1, -1), "TOP"),
               ("BOTTOMPADDING", (0, 1), (-1, 1), 6)])

    txn_rows = [
        ["Merchant (legal)", txn["merchant_legal_name"], "Descriptor", txn["merchant_descriptor"]],
        ["Amount", f"{txn['currency']} {txn['amount']:,.2f}", "Settled (USD)", f"{txn['settled_amount_usd']:,.2f}" + (f" @ {txn['fx_rate']}" if txn["fx_rate"] != 1 else "")],
        ["Auth date", txn["auth_date"], "Post date", txn["post_date"]],
        ["Card", f"{txn['card_network']} ****{txn['card_last4']}", "Auth code", txn["auth_code"]],
        ["ARN", txn["arn"], "Invoice ref", txn.get("invoice_reference") or "—"],
        ["MCC", f"{txn['mcc']} {txn['mcc_description']}", "Country", txn["merchant_country"]],
    ]
    txn_table = _grid([[_p(c) for c in row] for row in txn_rows], [27 * mm, 60 * mm, 27 * mm, 60 * mm], header=False)

    score_markup = f"<font color='#{score_color.hexval()[2:]}' size='22'><b>{match['score']:.0%}</b></font>"
    score_box = Table(
        [[Paragraph(score_markup, STYLES["body"]),
          _p(f"{match['verdict'].replace('_', ' ')}\nSemantic similarity {match['semantic_score']:.0%} x 60% "
             f"+ field corroboration {match['field_score']:.0%} x 40%\n"
             f"Embedding model: {match['embedding_model']}", "small")]],
        colWidths=[32 * mm, 142 * mm],
        style=[("BOX", (0, 0), (-1, -1), 0.8, score_color), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("BACKGROUND", (0, 0), (-1, -1), SLATE_50), ("TOPPADDING", (0, 0), (-1, -1), 8),
               ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])

    check_rows = [["Field", "Expected", "Result"]] + [
        [c["field"], _p(str(c["expected"])), "MATCHED" if c["matched"] else "NOT FOUND" if c.get("applicable", True) else "N/A"] for c in match["field_checks"]]
    checks = _grid(check_rows, [40 * mm, 104 * mm, 30 * mm])
    for i, c in enumerate(match["field_checks"], start=1):
        checks.setStyle(TableStyle([("TEXTCOLOR", (2, i), (2, i), EMERALD if c["matched"] else AMBER if c.get("applicable", True) else SLATE_600),
                                    ("FONT", (2, i), (2, i), "Helvetica-Bold", 8)]))

    story = [header, Spacer(1, 5 * mm), _p("1. Disputed Transaction", "h2"), txn_table,
             _p("2. Evidence Match", "h2"), score_box, Spacer(1, 3 * mm), checks]

    if txn.get("memo"):
        story += [_p("3. Cardholder Statement", "h2"), _p(txn["memo"])]

    story += [PageBreak(), _p("Chargeback Argument Letter", "h2")]
    story += [_p(para, "letter") for para in letter["text"].split("\n\n") if para.strip()]
    if letter.get("fallback"):
        story.append(_p("Note: generated from the offline template because the local gemma2 model was unavailable.",
                        "small"))

    ev_rows = [["#", "Similarity", "Matched evidence text"]] + [
        [str(i), f"{e['similarity']:.3f}", _p(e["text"], "mono")] for i, e in enumerate(match["top_evidence"], 1)]
    story += [PageBreak(), _p("Matched Evidence Excerpts (Exhibit A)", "h2"),
              _p(f"Source file: {evidence['filename']} ({evidence['kind'].upper()}, text via {evidence['method']}). "
                 "Excerpts ranked by maximum cosine similarity against the transaction facets.", "small"),
              Spacer(1, 3 * mm), _grid(ev_rows, [8 * mm, 20 * mm, 146 * mm])]

    if evidence["kind"] == "jpeg":
        img = Image(io.BytesIO(evidence["data"]))
        scale = min((174 * mm) / img.imageWidth, (200 * mm) / img.imageHeight, 1.0)
        img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
        story += [PageBreak(), KeepTogether([_p("Exhibit A: Original Evidence Image", "h2"), img])]
    else:
        story += [Spacer(1, 6 * mm), _p("Exhibit A (original document) is appended on the following pages.", "small")]

    doc.build(story, onFirstPage=_footer(case_id, letter), onLaterPages=_footer(case_id, letter))
    package = buf.getvalue()

    if evidence["kind"] != "pdf":
        return package
    try:
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(package)))
        writer.append(PdfReader(io.BytesIO(evidence["data"])))
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - a malformed evidence PDF shouldn't block the package
        return package
