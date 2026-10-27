"""Cross-border transactions (Card Optimizer, LOCKED): payments hitting SCA walls and FX friction.

Provisioned now so the data layer is complete; the Card Optimizer pipeline that consumes it
stays locked until it is built.
"""

CROSS_BORDER_TRANSACTIONS: list[dict] = [
    {"id": "txn_xb_01", "merchant": "OVH SAS", "merchant_country": "FR", "issuer_country": "US",
     "amount": 2310.40, "currency": "EUR", "decline_code": "1A", "decline_text": "SCA_REQUIRED / soft decline",
     "fx_fee_bps": 300},
    {"id": "txn_xb_02", "merchant": "Hetzner Online GmbH", "merchant_country": "DE", "issuer_country": "US",
     "amount": 489.00, "currency": "EUR", "decline_code": "65", "decline_text": "exceeds withdrawal frequency (3DS challenge abandoned)",
     "fx_fee_bps": 275},
    {"id": "txn_xb_03", "merchant": "Atlassian Pty Ltd", "merchant_country": "AU", "issuer_country": "US",
     "amount": 12900.00, "currency": "USD", "decline_code": None, "decline_text": None,
     "fx_fee_bps": 150},
    {"id": "txn_xb_04", "merchant": "Zoho Corporation", "merchant_country": "IN", "issuer_country": "GB",
     "amount": 76500.00, "currency": "INR", "decline_code": "05", "decline_text": "do not honor - cross-region MCC block",
     "fx_fee_bps": 350},
]
