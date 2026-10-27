"""Recurring liability transactions (Liquidity Guard, LOCKED): recurring liabilities, mixing fixed SaaS seats with
variable usage-based consumption lines that auto-debit with surprise amounts.

Provisioned now so the data layer is complete; the Liquidity Guard pipeline stays locked
until it is built.
"""

RECURRING_TRANSACTIONS: list[dict] = [
    {"id": "txn_rc_01", "descriptor": "AWS EMEA aws.amazon.co", "amount": 48211.77, "currency": "USD",
     "prior_3mo_avg": 21400.00, "billing_day": 2, "line_items": ["EC2 On-Demand", "Data Transfer Out", "Bedrock tokens"]},
    {"id": "txn_rc_02", "descriptor": "GOOGLE*CLOUD 7HX2LQ", "amount": 15620.05, "currency": "USD",
     "prior_3mo_avg": 14980.00, "billing_day": 1, "line_items": ["BigQuery analysis", "GKE Autopilot"]},
    {"id": "txn_rc_03", "descriptor": "FACEBK *ADS 9QZ3KL4", "amount": 33000.00, "currency": "USD",
     "prior_3mo_avg": 12500.00, "billing_day": None, "line_items": ["Threshold billing x4"]},
    {"id": "txn_rc_04", "descriptor": "SLACK T02ABCD", "amount": 6120.00, "currency": "USD",
     "prior_3mo_avg": 6120.00, "billing_day": 14, "line_items": ["Business+ 72 seats"]},
]
