"""
One-time ETL: converts the org's master
"Sales and ChannelPartner Operations Data.xlsx" (Accounts / Deals sheets)
into Agent 3's seed CSVs. Not imported by the running app — run manually
whenever the source workbook changes:

    python data/import_from_excel.py "C:\\path\\to\\Sales and ChannelPartner Operations Data.xlsx"

Decisions baked in here (see conversation record for why):
- industry / region: dropped entirely, not in the source.
- tier: derived from ARR bands (not in the source).
- usage trend: 12 weeks for every account. Where the source's Upsells sheet
  has 7 real weeks, those are kept as the last 7 and 5 synthetic weeks are
  extrapolated backwards along the same trend. Where there's no real data
  at all (11/30 accounts), the whole 12 weeks is synthetic but plausible
  (seeded per-account so re-running this script is reproducible).
- ticket product_area: inferred from subject keywords, null if no match.
- ticket opened_date: dropped, not in the source (would be pure fabrication).
- contract billing_model: backfilled from the Deals sheet (first matching
  deal per account) since it's not on the Accounts sheet itself.
- contract start_date: approximated as renewal_date - term (day-of-month
  is unknowable since the source only gives "Nov 2027"-style months).
- calendar_meetings: synthesized entirely - no calendar data exists in the
  source workbook at all, for any agent.
"""
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # agents/agent3_am_account_context/backend/data
CATALOG = ["Firebox M590", "Endpoint Security", "DNSWatch", "AuthPoint", "Backup", "Secure Wi-Fi"]

TICKET_PRODUCT_RULES = [
    (["dnswatch"], "DNSWatch"),
    (["wi-fi", "wifi"], "Secure Wi-Fi"),
    (["firmware", "firewall"], "Firebox M590"),
    (["siem"], "Firebox M590"),
    (["backup"], "Backup"),
    (["sso", "portal login"], "AuthPoint"),
    (["license reassignment"], "Endpoint Security"),
]

MEETING_TYPES = ["QBR", "Monthly check-in", "Renewal discussion", "Escalation follow-up", "Expansion discovery"]


def infer_product_area(subject: str) -> str | None:
    s = (subject or "").lower()
    for keywords, product in TICKET_PRODUCT_RULES:
        if any(k in s for k in keywords):
            return product
    return None


def tier_from_arr(arr: float) -> str:
    if arr >= 175_000:
        return "Platinum"
    if arr >= 100_000:
        return "Gold"
    if arr >= 50_000:
        return "Silver"
    return "Bronze"


def parse_term_months(term: str) -> int:
    m = re.match(r"(\d+)\s*mo", str(term).strip(), re.IGNORECASE)
    return int(m.group(1)) if m else 12


def parse_renewal_date(val: str) -> datetime:
    return datetime.strptime(str(val).strip(), "%b %Y")


def parse_tickets(detail: str, account_id: str) -> list[dict]:
    if not isinstance(detail, str) or not detail.strip():
        return []
    rows = []
    for segment in detail.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        m = re.match(r"(TCK-\d+)\s*\(Sev-(\d)\):\s*(.*)", segment)
        if not m:
            continue
        ticket_id, sev, subject = m.groups()
        subject = subject.strip() or "Unspecified issue"
        rows.append({
            "account_id": account_id,
            "ticket_id": ticket_id,
            "priority": f"Sev-{sev}",
            "subject": subject,
            "product_area": infer_product_area(subject),
            "status": "Open",
        })
    return rows


def synth_usage_trend(account_id: str, real_last_7: list[int] | None) -> list[int]:
    rng = random.Random(account_id)  # deterministic per account
    if real_last_7:
        # extrapolate 5 earlier weeks backwards along the same rough trend
        step = (real_last_7[-1] - real_last_7[0]) / max(len(real_last_7) - 1, 1)
        lead = []
        v = real_last_7[0]
        for _ in range(5):
            v = max(1, v - step + rng.uniform(-3, 3))
            lead.insert(0, round(v))
        return [max(1, x) for x in lead] + real_last_7
    # fully synthetic but plausible 12-week trend
    base = rng.uniform(20, 55)
    drift = rng.uniform(-1.5, 2.5)
    trend = []
    v = base
    for _ in range(12):
        v = max(1, v + drift + rng.uniform(-4, 4))
        trend.append(round(v))
    return trend


def synth_invoice_rows(account_id: str, invoice_status: str, dso_days: int) -> list[dict]:
    today = datetime(2026, 8, 15)
    m = re.match(r"(\d+) invoices? over 30 days", str(invoice_status).strip())
    rows = []
    if m:
        n_overdue = int(m.group(1))
        for i in range(n_overdue):
            rows.append({
                "account_id": account_id,
                "invoice_date": (today - timedelta(days=35 + i * 15)).date().isoformat(),
                "status": "overdue",
                "dso_days": dso_days,
            })
        rows.append({
            "account_id": account_id,
            "invoice_date": (today - timedelta(days=5)).date().isoformat(),
            "status": "current",
            "dso_days": dso_days,
        })
    else:
        rows.append({
            "account_id": account_id,
            "invoice_date": (today - timedelta(days=5)).date().isoformat(),
            "status": "current",
            "dso_days": dso_days,
        })
    return rows


def synth_calendar(accounts: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random("agent3-calendar")
    base = datetime(2026, 8, 15, 9, 0)
    rows = []
    for i, row in accounts.iterrows():
        offset_days = rng.randint(0, 13)
        offset_hour = rng.choice([9, 10, 11, 13, 14, 15, 16])
        dt = base + timedelta(days=offset_days)
        dt = dt.replace(hour=offset_hour, minute=rng.choice([0, 15, 30, 45]))
        rows.append({
            "account_id": row["account_id"],
            "meeting_id": f"MTG-{i + 1:03d}",
            "am_rep": row["am_owner"],
            "scheduled_datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "meeting_type": rng.choice(MEETING_TYPES),
        })
    return pd.DataFrame(rows).sort_values("scheduled_datetime")


def main(xlsx_path: str):
    xls = pd.ExcelFile(xlsx_path)
    acc_raw = xls.parse("Accounts").sort_values("Account Name").reset_index(drop=True)
    deals_raw = xls.parse("Deals")
    upsells_raw = xls.parse("Upsells")

    acc_raw["account_id"] = [f"ACC-{i + 1:03d}" for i in range(len(acc_raw))]
    name_to_id = dict(zip(acc_raw["Account Name"], acc_raw["account_id"]))

    first_deal_billing = deals_raw.drop_duplicates("Account").set_index("Account")["Billing Model"].to_dict()
    usage_by_account = {
        row["Account"]: [int(x) for x in str(row["90-Day Usage Trend"]).split(",")]
        for _, row in upsells_raw.iterrows()
    }

    accounts_rows, contracts_rows, entitlements_rows = [], [], []
    usage_rows, invoice_rows, ticket_rows = [], [], []

    for _, row in acc_raw.iterrows():
        account_id = row["account_id"]
        name = row["Account Name"]
        arr = float(row["ARR ($)"])
        term_months = parse_term_months(row["Contract Term"])
        renewal_dt = parse_renewal_date(row["Renewal Date"])
        start_dt = renewal_dt - pd.DateOffset(months=term_months)

        accounts_rows.append({
            "account_id": account_id,
            "account_name": name,
            "am_owner": row["Account Owner"],
            "tier": tier_from_arr(arr),
            "account_since": int(row["Customer Since"]),
        })

        owned = [p.strip() for p in str(row["Products Owned"]).split(",") if p.strip()]
        contracts_rows.append({
            "account_id": account_id,
            "product_bundle": " + ".join(owned),
            "term_months": term_months,
            "start_date": start_dt.date().isoformat(),
            "renewal_date": renewal_dt.date().isoformat(),
            "arr": int(arr),
            "billing_model": first_deal_billing.get(name, "Unknown"),
        })

        for product in CATALOG:
            entitlements_rows.append({"account_id": account_id, "product": product, "owned": product in owned})

        real_trend = usage_by_account.get(name)
        for wi, score in enumerate(synth_usage_trend(account_id, real_trend)):
            week_ending = (datetime(2026, 8, 15) - timedelta(weeks=(11 - wi))).date().isoformat()
            usage_rows.append({"account_id": account_id, "week_ending": week_ending, "usage_score": score})

        invoice_rows.extend(synth_invoice_rows(account_id, row["Invoice Status"], int(row["DSO (days)"])))
        ticket_rows.extend(parse_tickets(row["Open Ticket Detail"], account_id))

    pd.DataFrame(accounts_rows).to_csv(DATA_DIR / "accounts.csv", index=False)
    pd.DataFrame(contracts_rows).to_csv(DATA_DIR / "contracts.csv", index=False)
    pd.DataFrame(entitlements_rows).to_csv(DATA_DIR / "entitlements.csv", index=False)
    pd.DataFrame(usage_rows).to_csv(DATA_DIR / "product_usage.csv", index=False)
    pd.DataFrame(invoice_rows).to_csv(DATA_DIR / "invoices_payments.csv", index=False)
    pd.DataFrame(ticket_rows).to_csv(DATA_DIR / "tickets.csv", index=False)
    synth_calendar(pd.DataFrame(accounts_rows)).to_csv(DATA_DIR / "calendar_meetings.csv", index=False)

    for log_name, header in [
        ("call_notes_log.csv", "log_id,account_id,meeting_id,am_rep,timestamp,call_notes_text\n"),
        ("crm_tasks_log.csv", "task_id,account_id,type,description,status,created_at,approved_by\n"),
    ]:
        (DATA_DIR / log_name).write_text(header)

    print(f"Imported {len(accounts_rows)} accounts, {len(ticket_rows)} tickets, "
          f"{sum(1 for v in usage_by_account.values())} accounts with real usage data "
          f"(rest synthesized).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_from_excel.py <path-to-xlsx>")
        sys.exit(1)
    main(sys.argv[1])
