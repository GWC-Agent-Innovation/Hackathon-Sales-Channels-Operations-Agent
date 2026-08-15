"""
Agent 3 (AM Account Context Assembly & Post-Call Action) — self-contained
data access. This is the "system of record" for account facts that
Agent 4 (renewal_backlog) cross-references via its own duplicated copies -
see agents/renewal_backlog/data/ and its data_store.py for why those are
copies rather than a shared import.

    accounts.csv                 -> CRM account master
    contracts.csv                 -> ERP / billing contract terms
    entitlements.csv               -> Product entitlement system
    product_usage.csv               -> Usage telemetry
    invoices_payments.csv            -> ERP invoice/payment status
    tickets.csv                       -> Ticketing system
    calendar_meetings.csv              -> Calendar integration
    account_last_interaction.csv        -> stands in for meeting/call history
    account_signals.csv                  -> stands in for a CRM notes/email-signal feed
    call_notes_log.csv                    -> written by writer.py (Screen 2 output)
    crm_tasks_log.csv                      -> written by writer.py (Screen 3 output)
"""
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # backend/data (sibling of this package)
USAGE_TREND_WEEKS = 12


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name)


@lru_cache(maxsize=1)
def load_all() -> dict[str, pd.DataFrame]:
    return {
        "accounts": _read("accounts.csv"),
        "contracts": _read("contracts.csv"),
        "entitlements": _read("entitlements.csv"),
        "product_usage": _read("product_usage.csv"),
        "invoices_payments": _read("invoices_payments.csv"),
        "tickets": _read("tickets.csv"),
        "calendar_meetings": _read("calendar_meetings.csv"),
        "account_last_interaction": _read("account_last_interaction.csv"),
        "account_signals": _read("account_signals.csv"),
    }


def get_account_row(account_id: str) -> dict | None:
    df = load_all()["accounts"]
    match = df[df["account_id"] == account_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_upcoming_meetings(am_rep: str | None = None) -> list[dict]:
    """
    Powers the customer-selection screen: "what customers, when is their
    next call scheduled." Joined with account_name so the frontend doesn't
    need a second lookup.
    """
    tables = load_all()
    meetings = tables["calendar_meetings"].merge(
        tables["accounts"][["account_id", "account_name", "tier"]],
        on="account_id", how="left",
    )
    if am_rep:
        meetings = meetings[meetings["am_rep"] == am_rep]

    meetings = meetings.sort_values("scheduled_datetime")
    return meetings.to_dict(orient="records")


def get_last_interaction(account_id: str) -> dict | None:
    df = load_all()["account_last_interaction"]
    match = df[df["account_id"] == account_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_account_signal(account_id: str) -> dict | None:
    df = load_all()["account_signals"]
    match = df[df["account_id"] == account_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_account_context(account_id: str) -> dict:
    """
    The core aggregator: joins every "system" for one account into a
    single dict. This is what gets hydrated into the LLM prompt for the
    pre-call briefing (Screen 1), and is also useful as raw JSON for the
    frontend cards even before the LLM synthesis step runs.
    """
    tables = load_all()

    account = get_account_row(account_id)
    if account is None:
        raise KeyError(f"Unknown account_id: {account_id}")

    contract_rows = tables["contracts"][tables["contracts"]["account_id"] == account_id]
    contract = contract_rows.iloc[0].to_dict() if not contract_rows.empty else None

    entitlements = tables["entitlements"][tables["entitlements"]["account_id"] == account_id]
    owned_products = entitlements[entitlements["owned"] == True]["product"].tolist()  # noqa: E712
    missing_products = entitlements[entitlements["owned"] == False]["product"].tolist()  # noqa: E712

    usage = tables["product_usage"][tables["product_usage"]["account_id"] == account_id]
    usage = usage.sort_values("week_ending").tail(USAGE_TREND_WEEKS)
    usage_trend = usage["usage_score"].tolist()
    usage_direction = "flat"
    if len(usage_trend) >= 2:
        delta = usage_trend[-1] - usage_trend[0]
        usage_direction = "up" if delta > 5 else "down" if delta < -5 else "flat"

    invoices = tables["invoices_payments"][tables["invoices_payments"]["account_id"] == account_id]
    invoices = invoices.sort_values("invoice_date", ascending=False)
    overdue_invoices = invoices[invoices["status"] == "overdue"]
    dso = int(invoices.iloc[0]["dso_days"]) if not invoices.empty else None

    tickets = tables["tickets"][tables["tickets"]["account_id"] == account_id]
    tickets = tickets.sort_values("priority")  # Sev-1 sorts before Sev-2/3 lexically... see note below
    # priority sorts lexically (Sev-1 < Sev-2 < Sev-3) which happens to match severity order
    tickets = tickets.astype(object).where(pd.notnull(tickets), None)  # NaN -> None (JSON-safe)

    return {
        "account_id": account_id,
        "account_name": account["account_name"],
        "tier": account["tier"],
        "am_owner": account["am_owner"],
        "account_since": int(account["account_since"]),
        "contract": {
            "product_bundle": contract["product_bundle"] if contract else None,
            "term_months": contract["term_months"] if contract else None,
            "renewal_date": contract["renewal_date"] if contract else None,
            "arr": contract["arr"] if contract else None,
            "billing_model": contract["billing_model"] if contract else None,
        } if contract else None,
        "entitlements": {
            "owned": owned_products,
            "missing": missing_products,
        },
        "usage": {
            "trend": usage_trend,
            "direction": usage_direction,
        },
        "invoices": {
            "overdue_count": int(len(overdue_invoices)),
            "overdue_summary": (
                f"{len(overdue_invoices)} invoice(s) over 30 days"
                if len(overdue_invoices) > 0 else "Current"
            ),
            "dso_days": dso,
        },
        "tickets": {
            "open_count": int(len(tickets)),
            "open_tickets": tickets.to_dict(orient="records"),
        },
    }


def append_row(csv_name: str, row: dict) -> None:
    path = DATA_DIR / csv_name
    df_existing = pd.read_csv(path)
    df_new = pd.concat([df_existing, pd.DataFrame([row])], ignore_index=True)
    df_new.to_csv(path, index=False)
    load_all.cache_clear()


def next_log_id(csv_name: str, id_column: str, prefix: str) -> str:
    path = DATA_DIR / csv_name
    df = pd.read_csv(path)
    if df.empty:
        return f"{prefix}-001"
    nums = df[id_column].astype(str).str.extract(rf"{prefix}-(\d+)")[0].dropna().astype(int)
    next_n = (nums.max() + 1) if not nums.empty else 1
    return f"{prefix}-{next_n:03d}"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
