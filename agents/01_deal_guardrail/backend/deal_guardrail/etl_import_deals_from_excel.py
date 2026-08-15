"""
One-time ETL: converts the "Deals" sheet of the org's master
"Sales and ChannelPartner Operations Data.xlsx" into deals.csv for
Agent 1 (Sales Deal Guardrail & Order Validation Agent), and generates
shipping_addresses.csv (synthetic - no address field exists anywhere in
the source workbook, and hardware SKUs like Firebox M590 need somewhere
to ship to).

Run (from the SAS/ project root):
    python agents/agent1_deal_guardrail/backend/deal_guardrail/etl_import_deals_from_excel.py "C:\\path\\to\\Sales and ChannelPartner Operations Data.xlsx"

Notes:
- account_id is cross-referenced from accounts.csv (Agent 3's account
  master) by matching Account Name - both agents share the same account
  system in real life, so this mirrors that.
- All 88 deals become Agent 1's review backlog (the source workbook's own
  Status/Exception Reason columns reflect a *different*, already-decided
  process - Agent 1 independently re-validates every deal against its own
  rules engine rather than trusting those labels). The original status is
  kept as `source_status_reference` for context only, never used as the
  agent's own verdict.
- HARDWARE_PRODUCTS defines which SKUs need a physical ship-to address
  (Firebox M590 only, currently) - purely a config decision, not sourced.
"""
import random
import re
import sys
from pathlib import Path

import pandas as pd

THIS_BACKEND = Path(__file__).resolve().parent.parent  # agents/agent1_deal_guardrail/backend
AGENTS_ROOT = THIS_BACKEND.parent.parent                # agents/
DATA_DIR = THIS_BACKEND / "data"
AM_DATA_DIR = AGENTS_ROOT / "agent3_am_account_context" / "backend" / "data"
HARDWARE_PRODUCTS = {"Firebox M590"}


def parse_term_months(term: str) -> int:
    m = re.match(r"(\d+)\s*mo", str(term).strip(), re.IGNORECASE)
    return int(m.group(1)) if m else 12


def build_deals(xlsx_path: str, accounts: pd.DataFrame) -> pd.DataFrame:
    xls = pd.ExcelFile(xlsx_path)
    deals = xls.parse("Deals")
    name_to_id = dict(zip(accounts["account_name"], accounts["account_id"]))

    rows = []
    for _, d in deals.iterrows():
        account_name = d["Account"]
        products = [p.strip() for p in str(d["Product"]).split("+")]
        rows.append({
            "deal_id": d["Deal ID"],
            "account_id": name_to_id.get(account_name, ""),
            "account_name": account_name,
            "rep": d["Rep"],
            "rep_role": d["Rep Role"],
            "product_bundle": d["Product"],
            "requires_hardware_shipment": any(p in HARDWARE_PRODUCTS for p in products),
            "quantity": int(d["Quantity"]),
            "discount_pct": float(d["Discount (%)"]),
            "max_discount_pct": float(d["Max Discount Allowed (%)"]),
            "billing_model": d["Billing Model"],
            "term_months": parse_term_months(d["Term"]),
            "arr": int(d["ARR ($)"]),
            "submitted_age": d["Date / Age"],
            "source_status_reference": d["Status"],
        })
    return pd.DataFrame(rows)


def build_addresses(accounts: pd.DataFrame) -> pd.DataFrame:
    """
    Synthetic ship-to address per account. A handful are deliberately
    incomplete/malformed so the address-completeness guardrail has
    something real to catch in the demo.
    """
    rng = random.Random("agent1-addresses")
    streets = ["100 Harbor Way", "48 Commerce Dr", "220 Industrial Pkwy", "77 Market St",
               "9 Innovation Loop", "310 Riverside Ave", "15 Corporate Blvd", "60 Foundry Rd"]
    cities = [("Chicago", "IL", "60601"), ("Denver", "CO", "80202"), ("Austin", "TX", "73301"),
              ("Portland", "OR", "97201"), ("Raleigh", "NC", "27601"), ("Boise", "ID", "83702"),
              ("Hartford", "CT", "06103"), ("Tulsa", "OK", "74103"), ("Reno", "NV", "89501"),
              ("Madison", "WI", "53703")]

    broken_kinds = ["missing_postal", "missing_region", "missing_street", "wrong_country_placeholder"]
    broken_accounts = rng.sample(list(accounts["account_id"]), 5)

    rows = []
    for _, a in accounts.iterrows():
        city, region, postal = rng.choice(cities)
        row = {
            "account_id": a["account_id"],
            "street": rng.choice(streets),
            "city": city,
            "region": region,
            "postal_code": postal,
            "country": "United States",
        }
        if a["account_id"] in broken_accounts:
            kind = rng.choice(broken_kinds)
            if kind == "missing_postal":
                row["postal_code"] = ""
            elif kind == "missing_region":
                row["region"] = ""
            elif kind == "missing_street":
                row["street"] = ""
            elif kind == "wrong_country_placeholder":
                row["country"] = "TBD"
        rows.append(row)
    return pd.DataFrame(rows)


def main(xlsx_path: str):
    accounts = pd.read_csv(AM_DATA_DIR / "accounts.csv")

    deals_df = build_deals(xlsx_path, accounts)
    deals_df.to_csv(DATA_DIR / "deals.csv", index=False)

    addresses_df = build_addresses(accounts)
    addresses_df.to_csv(DATA_DIR / "shipping_addresses.csv", index=False)

    (DATA_DIR / "deal_review_log.csv").write_text(
        "review_id,deal_id,decision,reviewer,comment,decided_at\n"
    )

    unmatched = deals_df[deals_df["account_id"] == ""]["account_name"].unique().tolist()
    print(f"Imported {len(deals_df)} deals, {len(addresses_df)} shipping addresses.")
    if unmatched:
        print(f"WARNING - {len(unmatched)} account name(s) in Deals didn't match accounts.csv: {unmatched}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_deals_from_excel.py <path-to-xlsx>")
        sys.exit(1)
    main(sys.argv[1])
