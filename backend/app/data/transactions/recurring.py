"""Upcoming auto-debits and the bank accounts they hit (Liquidity Guard).

Each bill is a vendor statement for the October cycle, captured on 28 Oct with 27 of 31 days elapsed, that will
auto-debit in early November. Bills mix fixed lines (seats, licences, commitments) with variable usage-based
consumption lines whose month-to-date amount is only part of what will be charged. The feed is messy on purpose:
amounts as strings with separators, vendor descriptors that don't match legal names, an ad account billed per
impression, a support plan priced as a percentage of usage, and line text copied straight from the invoice.

Bills debit one of three accounts: the operating account (ACH vendors, payroll, customer receipts), the card
settlement account that auto-pays the corporate card statements, and the marketing account that funds ad platforms.
"""

ANALYSIS_DATE = "2026-10-28"

# The billing cycle the month-to-date amounts cover.
CYCLE = {"start": "2026-10-01", "end": "2026-10-31", "days": 31, "days_elapsed": 27}

ACCOUNTS: list[dict] = [
    {"id": "acct_operating", "name": "Operating account (USD) ****2210", "purpose": "ACH vendors, payroll, receipts",
     "balance": "240,000.00", "currency": "USD", "minimum_buffer": 75000.00},
    {"id": "acct_cards", "name": "Card settlement (USD) ****7731", "purpose": "Auto-pays the Visa and Mastercard statements",
     "balance": "135,000.00", "currency": "USD", "minimum_buffer": 60000.00},
    {"id": "acct_marketing", "name": "Marketing account (USD) ****4408", "purpose": "Funds the ad platforms",
     "balance": "70,000.00", "currency": "USD", "minimum_buffer": 20000.00},
]

# Known non-bill cash movements in the forecast window (not classified, just part of the cash timeline).
KNOWN_FLOWS: list[dict] = [
    {"account_id": "acct_operating", "date": "2026-11-01", "label": "Payroll (semi-monthly)", "amount": -98000.00},
    {"account_id": "acct_operating", "date": "2026-11-04", "label": "Customer receipts (Acme Corp invoice INV-2291)",
     "amount": 45000.00},
]

# Each line: description as printed on the invoice, month-to-date amount, and the last three cycles' charges.
RECURRING_BILLS: list[dict] = [
    {"id": "bill_aws", "account_id": "acct_cards", "vendor": "Amazon Web Services", "descriptor": "AWS EMEA aws.amazon.co",
     "debit_date": "2026-11-02", "payment_method": "card_us_visa", "lines": [
        {"id": "aws_ec2", "description": "Amazon EC2 - On-Demand Linux m7i.4xlarge, 18,412 Hrs",
         "mtd": "21,880.40", "history": [9100.00, 9650.00, 10020.00]},
        {"id": "aws_transfer", "description": "Data Transfer - Out to Internet, 212.4 TB",
         "mtd": "14,302.10", "history": [3900.00, 4100.00, 4050.00]},
        {"id": "aws_bedrock", "description": "Amazon Bedrock - model inference, input and output tokens",
         "mtd": "6,410.00", "history": [1200.00, 2300.00, 3100.00]},
        {"id": "aws_support", "description": "AWS Business Support (greater of $100 or 10% of monthly AWS usage)",
         "mtd": "4,259.25", "history": [1715.00, 1805.00, 1717.00]},
        {"id": "aws_savings_plan", "description": "Compute Savings Plan - 1yr No Upfront, $3,000.00/month commitment",
         "mtd": "3,000.00", "history": [3000.00, 3000.00, 3000.00]},
    ]},
    {"id": "bill_gcp", "account_id": "acct_operating", "vendor": "Google Cloud", "descriptor": "GOOGLE*CLOUD 7HX2LQ",
     "debit_date": "2026-11-01", "payment_method": "ach", "lines": [
        {"id": "gcp_bigquery", "description": "BigQuery Analysis - on-demand, 1,840 TiB scanned",
         "mtd": "9,890.00", "history": [8650.00, 9020.00, 9310.00]},
        {"id": "gcp_gke", "description": "GKE Autopilot - vCPU and memory, pod hours",
         "mtd": "3,912.55", "history": [4010.00, 3980.00, 4105.00]},
        {"id": "gcp_storage", "description": "Cloud Storage - Standard, us-central1, 410 TiB-months",
         "mtd": "1,640.00", "history": [1510.00, 1555.00, 1600.00]},
        {"id": "gcp_cud", "description": "Committed Use Discount - 3 year, 64 vCPU, monthly fee",
         "mtd": "1,820.00", "history": [1820.00, 1820.00, 1820.00]},
    ]},
    {"id": "bill_meta", "account_id": "acct_marketing", "vendor": "Meta Platforms (Ads)", "descriptor": "FACEBK *ADS 9QZ3KL4",
     "debit_date": "2026-11-03", "payment_method": "card_us_mc", "lines": [
        {"id": "meta_launch", "description": "Campaign 'Q4 Launch' - Advantage+ shopping, billed per 1,000 impressions",
         "mtd": "24,600.00", "history": [6200.00, 7100.00, 8800.00]},
        {"id": "meta_retarget", "description": "Campaign 'Retargeting EU' - billed per link click",
         "mtd": "4,180.00", "history": [3900.00, 4300.00, 4050.00]},
    ]},
    {"id": "bill_snowflake", "account_id": "acct_operating", "vendor": "Snowflake Inc.", "descriptor": "SNOWFLAKE INC SAN MATEO",
     "debit_date": "2026-11-05", "payment_method": "ach", "lines": [
        {"id": "sf_compute", "description": "Compute credits - on-demand, 1,912 credits @ $3.00",
         "mtd": "5,736.00", "history": [4800.00, 5100.00, 5250.00]},
        {"id": "sf_storage", "description": "Storage - 88 TB average @ $23.00/TB",
         "mtd": "2,024.00", "history": [1870.00, 1930.00, 1990.00]},
        {"id": "sf_capacity", "description": "Capacity commitment - annual contract, billed monthly",
         "mtd": "6,250.00", "history": [6250.00, 6250.00, 6250.00]},
    ]},
    {"id": "bill_twilio", "account_id": "acct_cards", "vendor": "Twilio Inc.", "descriptor": "TWILIO SENDGRID 8774",
     "debit_date": "2026-11-02", "payment_method": "card_us_visa", "lines": [
        {"id": "tw_sms", "description": "Programmable Messaging - SMS outbound US, 1.42M segments",
         "mtd": "11,218.00", "history": [7900.00, 8150.00, 8400.00]},
        {"id": "tw_numbers", "description": "Phone Numbers - 120 local numbers @ $1.15/number/month",
         "mtd": "138.00", "history": [138.00, 138.00, 138.00]},
    ]},
    {"id": "bill_datadog", "account_id": "acct_cards", "vendor": "Datadog, Inc.", "descriptor": "DATADOG INC NEW YORK",
     "debit_date": "2026-11-03", "payment_method": "card_us_mc", "lines": [
        {"id": "dd_hosts", "description": "Infrastructure Pro - 150 committed hosts, annual plan",
         "mtd": "3,450.00", "history": [3450.00, 3450.00, 3450.00]},
        {"id": "dd_ondemand", "description": "Infrastructure Pro - on-demand hosts above commitment, billed hourly",
         "mtd": "1,288.00", "history": [410.00, 620.00, 540.00]},
        {"id": "dd_logs", "description": "Log Management - ingestion, 38.2 TB @ $0.10/GB",
         "mtd": "3,820.00", "history": [2900.00, 3100.00, 3350.00]},
    ]},
    {"id": "bill_slack", "account_id": "acct_cards", "vendor": "Slack Technologies", "descriptor": "SLACK T02ABCD",
     "debit_date": "2026-11-14", "payment_method": "card_us_visa", "lines": [
        {"id": "slack_seats", "description": "Business+ - 72 seats, annual plan billed monthly",
         "mtd": "1,080.00", "history": [1080.00, 1080.00, 1080.00]},
    ]},
    {"id": "bill_salesforce", "account_id": "acct_operating", "vendor": "Salesforce, Inc.", "descriptor": "SFDC*SALESFORCE.COM",
     "debit_date": "2026-11-01", "payment_method": "ach", "lines": [
        {"id": "sfdc_licenses", "description": "Sales Cloud Enterprise - 40 user licenses",
         "mtd": "6,600.00", "history": [6600.00, 6600.00, 6600.00]},
    ]},
    {"id": "bill_office", "account_id": "acct_operating", "vendor": "Common Desk Coworking", "descriptor": "COMMONDESK AUSTIN",
     "debit_date": "2026-11-01", "payment_method": "ach", "lines": [
        {"id": "office_desks", "description": "Private office - 14 desks, monthly membership",
         "mtd": "9,800.00", "history": [9800.00, 9800.00, 9800.00]},
    ]},
    {"id": "bill_google_ads", "account_id": "acct_marketing", "vendor": "Google Ads", "descriptor": "GOOGLE *ADS4471982",
     "debit_date": "2026-11-04", "payment_method": "ach", "lines": [
        {"id": "gads_search", "description": "Search campaign 'Brand + Competitor' - billed per click",
         "mtd": "9,450.00", "history": [7800.00, 8200.00, 8650.00]},
        {"id": "gads_display", "description": "Display remarketing - billed per 1,000 impressions",
         "mtd": "2,610.00", "history": [2100.00, 2350.00, 2400.00]},
    ]},
    {"id": "bill_linkedin", "account_id": "acct_marketing", "vendor": "LinkedIn Ireland", "descriptor": "LINKEDIN 8261934",
     "debit_date": "2026-11-06", "payment_method": "ach", "lines": [
        {"id": "li_sponsored", "description": "Sponsored Content 'Q4 Launch' - billed per 1,000 impressions",
         "mtd": "5,400.00", "history": [3900.00, 4200.00, 4600.00]},
        {"id": "li_navigator", "description": "Sales Navigator Advanced - 10 seats, annual plan billed monthly",
         "mtd": "1,000.00", "history": [1000.00, 1000.00, 1000.00]},
    ]},
]

# Kept for the transactions package's exports.
RECURRING_TRANSACTIONS = RECURRING_BILLS
