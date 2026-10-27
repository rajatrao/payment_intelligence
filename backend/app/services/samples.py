"""Sample evidence library for the Auto-Dispute Concierge demo.

A mix of documents that genuinely back a dispute transaction and decoys that should not match, so the
matching score can be shown working in both directions. PDFs are generated with ReportLab and JPEG
"photos" with Pillow, on first use.
"""

import io
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFont

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, Table

from app.services.pdf_builder import _grid, _p, build_sample_invoice


def _document(*, merchant: str, doc_label: str, address: str, meta: str, bill_to: str, heading: str,
              lines: list[tuple[str, float]], notes_title: str, notes: str, footer: str,
              extra_rows: list[tuple[str, str]] | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{merchant} - {doc_label}", author=merchant)
    total = sum(a for _, a in lines)
    rows = [["Description", "Amount (USD)"]] + [[_p(d), f"{a:,.2f}"] for d, a in lines]
    rows += [[label, value] for label, value in (extra_rows or [])]
    rows.append([f"TOTAL (USD)", f"{total:,.2f}"])
    story = [
        Table([[_p(merchant, "h1"), _p(doc_label, "h1")], [_p(address, "small"), _p(meta, "small")]],
              colWidths=[115 * mm, 59 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]),
        Spacer(1, 8 * mm),
        _p("Bill To", "h2"),
        _p(bill_to),
        Spacer(1, 6 * mm),
        _p(heading, "h2"),
        _grid(rows, [134 * mm, 40 * mm]),
        Spacer(1, 6 * mm),
        _p(notes_title, "h2"),
        _p(notes),
        Spacer(1, 6 * mm),
        _p(footer, "small"),
    ]
    doc.build(story)
    return buf.getvalue()


NORTHSTAR = "Northstar Robotics, Inc.\n500 Howard Street, Suite 400, San Francisco, CA 94105, USA"


def _northwind_receipt() -> bytes:
    return _document(
        merchant="Northwind Events & Hospitality LLC", doc_label="RECEIPT",
        address="2200 Mission College Blvd, Santa Clara, CA 95054, USA\nevents@northwind-hospitality.com",
        meta="Receipt No: NW-8841\nDate: 09/02/2026\nPaid: Mastercard ****0928\nAuth: A71Z09\nProcessed by Square",
        bill_to=f"{NORTHSTAR}\nAttn: Marcus Lee, Sales",
        heading="SaaStr Annual 2026: Exhibitor Booth Package",
        lines=[("Premium corner booth 20x20, dedicated power drop and Wi-Fi", 6500.00),
               ("Lead retrieval app licence (2 devices)", 450.00),
               ("Exhibitor staff passes x4", 250.00)],
        notes_title="Package Terms",
        notes="1. Booth size and location: 20x20 premium corner, Hall B, as shown on the floor plan.\n"
              "2. Dedicated 20A power drop and hard-wired internet included.\n"
              "3. Changes to booth size or location require written client approval.",
        footer="Card statement descriptor: SQ *NORTHWIND EVENTS. Thank you for exhibiting with us.")


def _datadog_invoice() -> bytes:
    return _document(
        merchant="Datadog, Inc.", doc_label="INVOICE",
        address="620 8th Avenue, 45th Floor, New York, NY 10018, USA\nar@datadoghq.com",
        meta="Invoice No: DD-77120-OCT\nInvoice Date: 2026-10-01\nPaid: Mastercard ****7719\nAuth: DD0110",
        bill_to=f"{NORTHSTAR}\nAttn: Platform Engineering",
        heading="Subscription: October 2026",
        lines=[("Infrastructure Monitoring Pro, 40 hosts", 2800.00),
               ("Log Management, 150M indexed events", 1080.00)],
        notes_title="Billing Notes",
        notes="1. Account billing plan: ANNUAL, prepaid under invoice DD-77120-ANNUAL (paid 2026-01-15).\n"
              "2. This monthly invoice was generated automatically for the October 2026 period.\n"
              "3. Contact ar@datadoghq.com for billing corrections.",
        footer="Card statement descriptor: DATADOG INC NEW YORK NY.")


def _lumen_sow() -> bytes:
    return _document(
        merchant="Lumen Studio Creative BV", doc_label="STATEMENT OF WORK",
        address="Herengracht 182, 1016 BR Amsterdam, Netherlands\nhello@lumenstudio.nl",
        meta="SOW / Invoice: LS-2026-118\nDate: 2026-08-24\nPayment: PayPal (card)",
        bill_to=f"{NORTHSTAR}\nAttn: Priya Raman, Head of Growth",
        heading="Brand Film Production",
        lines=[("Hero brand film, 90 seconds, 4K master", 3400.00),
               ("Social cutdowns: 30s, 15s and 6s versions", 900.00),
               ("Colour grade, licensed music and two revision rounds", 300.00)],
        notes_title="Deliverables",
        notes="1. One 90-second hero film and three cutdowns (30s, 15s, 6s).\n"
              "2. Delivery of all files by 2026-09-20 via shared link.\n"
              "3. Deliverables shorter than specified are non-conforming and will be re-cut at no charge.",
        footer="Card statement descriptor: PAYPAL *LUMENSTUDIO.")


def _eurosites_q2_invoice() -> bytes:
    return _document(
        merchant="EUROSITES ADVERTISING LTD", doc_label="INVOICE",
        address="71 Clerkenwell Road, London EC1R 5BL, United Kingdom\nbilling@eurosites-advertising.co.uk",
        meta="Invoice No: ESA-INV-2026-0611\nInvoice Date: 11/06/2026\nPayment: Bank transfer, net 30",
        bill_to=f"{NORTHSTAR}\nAttn: Accounts Payable",
        heading="Insertion Order IO-ESA-51207: Q2 Paid Social Retargeting (UK)",
        lines=[("Paid social retargeting, UK, June flight", 7200.00),
               ("Audience build and pixel QA", 2600.00)],
        notes_title="Delivery Summary",
        notes="1. Campaign ran 1 June to 30 June 2026.\n"
              "2. Delivered 2,140,000 impressions against 2,000,000 contracted.\n"
              "3. Final delivery report issued 2026-07-02.",
        footer="Previous engagement. Paid by bank transfer; this invoice was not charged to a card.")


def _hotel_folio() -> bytes:
    return _document(
        merchant="The Clerkenwell Hotel", doc_label="GUEST FOLIO",
        address="14 St John Street, London EC1M 4AY, United Kingdom\nreservations@clerkenwellhotel.co.uk",
        meta="Folio No: 55-30917\nArrival: 2026-09-14\nDeparture: 2026-09-16\nPaid: Visa ****4471",
        bill_to="Priya Raman\nNorthstar Robotics, Inc.",
        heading="Accommodation and Incidentals",
        lines=[("Deluxe King room, 2 nights", 980.00),
               ("Room service and restaurant", 214.60),
               ("City tax", 91.80)],
        notes_title="Notes",
        notes="1. Corporate rate applied.\n2. Late checkout granted to 14:00.",
        footer="Thank you for staying with us.")


def _photo_receipt(lines: list[tuple[str, int]], tilt: float) -> bytes:
    """Render a receipt as a phone-photo style JPEG: off-white slip on a darker background, slightly rotated."""
    slip = Image.new("RGB", (620, 60 + 44 * len(lines)), (250, 248, 240))
    draw = ImageDraw.Draw(slip)
    y = 30
    for text, size in lines:
        font = ImageFont.load_default(size=size)
        x = (slip.width - draw.textlength(text, font=font)) / 2 if size >= 30 else 40
        draw.text((x, y), text, fill=(30, 30, 35), font=font)
        y += 44
    slip = slip.rotate(tilt, expand=True, fillcolor=(92, 84, 76))
    photo = Image.new("RGB", (slip.width + 120, slip.height + 120), (92, 84, 76))
    photo.paste(slip, (60, 60))
    buf = io.BytesIO()
    photo.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _northwind_photo() -> bytes:
    return _photo_receipt([
        ("NORTHWIND EVENTS", 36), ("& HOSPITALITY LLC", 28), ("Santa Clara, CA", 22), ("", 10),
        ("SaaStr Annual 2026 - Exhibitor", 24), ("Premium corner booth 20x20", 24), ("  power drop + Wi-Fi   6,500.00", 24),
        ("Lead retrieval x2        450.00", 24), ("Staff passes x4          250.00", 24), ("", 10),
        ("TOTAL USD             7,200.00", 28), ("09/02/2026  MC ****0928", 22), ("AUTH A71Z09   Receipt NW-8841", 22),
        ("SQ *NORTHWIND EVENTS", 22),
    ], tilt=-3.5)


def _taxi_photo() -> bytes:
    return _photo_receipt([
        ("LONDON BLACK CAB", 36), ("Licensed Hackney Carriage", 22), ("", 10),
        ("From: Clerkenwell Road EC1", 24), ("To:   Heathrow Terminal 5", 24), ("Distance 19.4 mi", 24), ("", 10),
        ("FARE USD                48.20", 28), ("15/09/2026  21:42", 22), ("VISA ****4471  APPROVED", 22),
    ], tilt=2.5)


SAMPLES: list[dict] = [
    {"id": "eurosites-invoice", "title": "EUROSITES Q4 campaign invoice", "doc_type": "Invoice", "kind": "pdf",
     "filename": "EUROSITES_ADVERTISING_ESA-INV-2026-0912.pdf", "expected_transaction_id": "txn_9f3a71c2",
     "description": "USD 18,450.00 · 12/09/2026 · campaign never went live", "builder": build_sample_invoice},
    {"id": "northwind-receipt", "title": "Northwind SaaStr booth receipt", "doc_type": "Receipt", "kind": "pdf",
     "filename": "Northwind_Receipt_NW-8841.pdf", "expected_transaction_id": "txn_51be08d4",
     "description": "USD 7,200.00 · 09/02/2026 · promised 20x20 booth with power", "builder": _northwind_receipt},
    {"id": "datadog-invoice", "title": "Datadog October invoice", "doc_type": "Invoice", "kind": "pdf",
     "filename": "Datadog_Invoice_DD-77120-OCT.pdf", "expected_transaction_id": "txn_e4492fa0",
     "description": "USD 3,880.00 · 2026-10-01 · annual plan already prepaid", "builder": _datadog_invoice},
    {"id": "lumen-sow", "title": "Lumen Studio statement of work", "doc_type": "Contract", "kind": "pdf",
     "filename": "Lumen_Studio_SOW_LS-2026-118.pdf", "expected_transaction_id": "txn_2a6d93e7",
     "description": "USD 4,600.00 · 2026-08-24 · 90s film + 3 cutdowns", "builder": _lumen_sow},
    {"id": "eurosites-q2-invoice", "title": "EUROSITES Q2 invoice (old job)", "doc_type": "Decoy", "kind": "pdf",
     "filename": "EUROSITES_ADVERTISING_ESA-INV-2026-0611.pdf", "expected_transaction_id": None,
     "description": "Same merchant, different job, amount and date", "builder": _eurosites_q2_invoice},
    {"id": "hotel-folio", "title": "Clerkenwell Hotel folio", "doc_type": "Decoy", "kind": "pdf",
     "filename": "Clerkenwell_Hotel_Folio_55-30917.pdf", "expected_transaction_id": None,
     "description": "London, same card and week, unrelated spend", "builder": _hotel_folio},
    {"id": "northwind-photo", "title": "Northwind booth receipt (photo)", "doc_type": "Receipt", "kind": "jpeg",
     "filename": "Northwind_Receipt_Photo.jpg", "expected_transaction_id": "txn_51be08d4",
     "description": "JPEG photo · USD 7,200.00 · matched as an image", "builder": _northwind_photo},
    {"id": "taxi-photo", "title": "London taxi receipt (photo)", "doc_type": "Decoy", "kind": "jpeg",
     "filename": "London_Taxi_Receipt_Photo.jpg", "expected_transaction_id": None,
     "description": "JPEG photo · USD 48.20 · same card, unrelated spend", "builder": _taxi_photo},
]

DEFAULT_SAMPLE_ID = "eurosites-invoice"
_cache: dict[str, bytes] = {}


def get_sample(sample_id: str) -> dict | None:
    return next((s for s in SAMPLES if s["id"] == sample_id), None)


def sample_bytes(sample_id: str) -> bytes:
    if sample_id not in _cache:
        builder: Callable[[], bytes] = get_sample(sample_id)["builder"]
        _cache[sample_id] = builder()
    return _cache[sample_id]


def sample_metadata() -> list[dict]:
    return [{k: v for k, v in s.items() if k != "builder"} for s in SAMPLES]
