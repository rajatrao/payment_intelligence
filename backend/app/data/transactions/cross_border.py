"""Cross-border card payments and the company's card portfolio (Card Optimizer).

The transaction feed is deliberately messy, the way issuer exports are: alpha-3 country codes next to alpha-2,
lower-case currencies, amounts as strings with thousands separators, free-text decline reasons. The
corridor engine (services/corridor.py) normalises it before anything is scored.
"""

# Regions used for corridor routing. Intra-regional payments avoid most cross-border assessments.
REGIONS: dict[str, str] = {
    "US": "NA", "CA": "NA",
    "FR": "EU", "DE": "EU", "NL": "EU", "IE": "EU", "GB": "EU", "CH": "EU",
    "AU": "APAC", "IN": "APAC", "JP": "APAC", "SG": "APAC",
}

ALPHA3: dict[str, str] = {"USA": "US", "CAN": "CA", "FRA": "FR", "DEU": "DE", "NLD": "NL", "IRL": "IE",
                          "GBR": "GB", "CHE": "CH", "AUS": "AU", "IND": "IN", "JPN": "JP", "SGP": "SG"}

# Mid-market rates to USD on the analysis date (mock).
FX_RATES_USD: dict[str, float] = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.012, "AUD": 0.66,
                                  "JPY": 0.0067, "SGD": 0.74, "CAD": 0.73, "CHF": 1.12}

# Corporate cards the treasury team can route a payment through.
#   fx_fee_bps:         charged when the payment currency is not one the card holds
#   cross_border_bps:   charged when the merchant is in a different region from the issuer
#   sca_exemption:      the card qualifies for the secure corporate payment exemption (PSD2 RTS Art. 17 / UK
#                       equivalent), so a merchant in the same region doesn't trigger a 3DS challenge
CARD_PORTFOLIO: list[dict] = [
    {"id": "card_us_visa", "name": "Visa Corporate ****4471", "network": "Visa", "issuer_country": "US",
     "currencies": ["USD"], "fx_fee_bps": 300, "cross_border_bps": 100, "sca_exemption": False,
     "notes": "Default card for most employees"},
    {"id": "card_us_mc", "name": "Mastercard Corporate ****0928", "network": "Mastercard", "issuer_country": "US",
     "currencies": ["USD"], "fx_fee_bps": 275, "cross_border_bps": 100, "sca_exemption": False,
     "notes": "Engineering and events spend"},
    {"id": "card_eu_lodged", "name": "Mastercard Lodged Virtual (IE) ****3310", "network": "Mastercard",
     "issuer_country": "IE", "currencies": ["EUR"], "fx_fee_bps": 200, "cross_border_bps": 80,
     "sca_exemption": True, "notes": "Lodged with suppliers; secure corporate payment exemption"},
    {"id": "card_uk_visa", "name": "Visa Commercial (UK) ****5562", "network": "Visa", "issuer_country": "GB",
     "currencies": ["GBP"], "fx_fee_bps": 250, "cross_border_bps": 90, "sca_exemption": True,
     "notes": "London entity; corporate exemption enrolled"},
    {"id": "card_sg_multi", "name": "Visa Multi-Currency (SG) ****7781", "network": "Visa", "issuer_country": "SG",
     "currencies": ["SGD", "USD", "AUD", "JPY", "INR"], "fx_fee_bps": 150, "cross_border_bps": 70,
     "sca_exemption": False, "notes": "APAC entity; holds local currency wallets"},
]

CROSS_BORDER_TRANSACTIONS: list[dict] = [
    {"id": "txn_xb_01", "merchant": "OVH SAS", "descriptor": "OVH*CLOUD ROUBAIX", "merchant_country": "FR",
     "mcc": "4816", "amount": "2,310.40", "currency": "EUR", "card_id": "card_us_visa",
     "attempted_at": "2026-10-21T09:14:00Z", "status": "DECLINED", "decline_code": "1A",
     "decline_text": "SCA_REQUIRED / soft decline - additional customer authentication required",
     "memo": "Q4 bare-metal renewal; vendor suspends servers on 30 Oct"},
    {"id": "txn_xb_02", "merchant": "Hetzner Online GmbH", "descriptor": "HETZNER ONLINE GMBH",
     "merchant_country": "DEU", "mcc": "7372", "amount": "489.00", "currency": "eur", "card_id": "card_us_mc",
     "attempted_at": "2026-10-22T16:40:00Z", "status": "DECLINED", "decline_code": "65",
     "decline_text": "Soft decline (65) - 3DS challenge abandoned by approver", "memo": None},
    {"id": "txn_xb_03", "merchant": "Atlassian Pty Ltd", "descriptor": "ATLASSIAN* SYDNEY",
     "merchant_country": "AU", "mcc": "5734", "amount": 12900.00, "currency": "USD", "card_id": "card_us_visa",
     "attempted_at": "2026-10-03T02:05:00Z", "status": "SETTLED", "decline_code": None, "decline_text": None,
     "memo": "Annual Jira + Confluence; billed in USD but cross-border fee still applied"},
    {"id": "txn_xb_04", "merchant": "Zoho Corporation", "descriptor": "ZOHO CORP CHENNAI", "merchant_country": "IN",
     "mcc": "7372", "amount": "76,500", "currency": "INR", "card_id": "card_uk_visa",
     "attempted_at": "2026-10-19T11:22:00Z", "status": "DECLINED", "decline_code": "05",
     "decline_text": "do not honor - cross-region MCC block", "memo": "Zoho Books for India subsidiary"},
    {"id": "txn_xb_05", "merchant": "Sakura Internet Inc", "descriptor": "SAKURA INTERNET TOKYO",
     "merchant_country": "JPN", "mcc": "4816", "amount": "184,000", "currency": "JPY", "card_id": "card_us_mc",
     "attempted_at": "2026-10-11T05:30:00Z", "status": "SETTLED", "decline_code": None, "decline_text": None,
     "memo": "GPU hosting, Tokyo region"},
    {"id": "txn_xb_06", "merchant": "Bloomberg L.P.", "descriptor": "BLOOMBERG LONDON", "merchant_country": "GB",
     "mcc": "7375", "amount": 4850.00, "currency": "GBP", "card_id": "card_us_visa",
     "attempted_at": "2026-10-01T08:00:00Z", "status": "SETTLED", "decline_code": None, "decline_text": None,
     "memo": "Terminal seat, London desk"},
    {"id": "txn_xb_07", "merchant": "Booking.com for Business", "descriptor": "BOOKING.COM BV",
     "merchant_country": "NL", "mcc": "4722", "amount": "9,120.00", "currency": "EUR", "card_id": "card_us_mc",
     "attempted_at": "2026-10-24T13:12:00Z", "status": "PENDING_AUTH", "decline_code": None,
     "decline_text": "3DS2 challenge pending - approver travelling, no OTP", "memo": "Offsite venue deposit, due 48h"},
    {"id": "txn_xb_08", "merchant": "Shopify Canada", "descriptor": "SHOPIFY* OTTAWA", "merchant_country": "CAN",
     "mcc": "5734", "amount": "1,045.00", "currency": "cad", "card_id": "card_us_visa",
     "attempted_at": "2026-10-15T19:45:00Z", "status": "SETTLED", "decline_code": None, "decline_text": None,
     "memo": None},
]
