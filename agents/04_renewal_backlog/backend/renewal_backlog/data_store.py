"""
Agent 4 (Renewal Opportunity Auto-Creation & Backlog) — self-contained
data access.

    renewal_opportunities.csv    -> CRM renewal-opportunity records (auto-created
                                     from Agent 3's contracts.csv - see
                                     data/build_renewal_backlog.py)
    rep_hierarchy.csv             -> AM -> manager -> executive reporting lines
    renewal_activity_log.csv       -> AM "worked this renewal" activity feed
    renewal_adjustments_log.csv     -> written by writer.py (Screen 3 manual field edits)
    renewal_escalation_log.csv       -> written by writer.py (notify/escalate actions)

    accounts.csv, contracts.csv, entitlements.csv, product_usage.csv,
    invoices_payments.csv, tickets.csv
        -> DUPLICATED copies of Agent 3's tables, kept here so this agent's
           risk-scoring (get_account_context, cross-referencing real open
           tickets/usage/invoice status) is self-contained and doesn't
           reach into another agent's folder. In production these would
           be the same live ERP/CRM/ticketing APIs Agent 3 calls, not a
           file each agent has to keep in sync - see README.md.
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
        "renewal_opportunities": _read("renewal_opportunities.csv"),
        "rep_hierarchy": _read("rep_hierarchy.csv"),
        "accounts": _read("accounts.csv"),
        "contracts": _read("contracts.csv"),
        "entitlements": _read("entitlements.csv"),
        "product_usage": _read("product_usage.csv"),
        "invoices_payments": _read("invoices_payments.csv"),
        "tickets": _read("tickets.csv"),
    }


def _latest_adjustments(renewal_id: str) -> dict:
    """Latest edited value per field from renewal_adjustments_log.csv, if any."""
    df = pd.read_csv(DATA_DIR / "renewal_adjustments_log.csv")
    df = df[df["renewal_id"] == renewal_id]
    if df.empty:
        return {}
    df = df.sort_values("adjusted_at")
    latest = df.groupby("field").tail(1)
    return dict(zip(latest["field"], latest["new_value"]))


def _apply_adjustments(renewal: dict) -> dict:
    overrides = _latest_adjustments(renewal["renewal_id"])
    if not overrides:
        return renewal
    renewal = dict(renewal)
    if "am_owner" in overrides:
        renewal["am_owner"] = overrides["am_owner"]
    if "target_close_date" in overrides:
        renewal["target_close_date"] = overrides["target_close_date"]
    if "expected_value" in overrides:
        renewal["expected_value"] = float(overrides["expected_value"])
    return renewal


def get_renewal_row(renewal_id: str) -> dict | None:
    df = load_all()["renewal_opportunities"]
    match = df[df["renewal_id"] == renewal_id]
    if match.empty:
        return None
    return _apply_adjustments(match.iloc[0].to_dict())


def get_all_renewals() -> list[dict]:
    """The full backlog, with any Screen 3 manual adjustments applied on top."""
    df = load_all()["renewal_opportunities"]
    return [_apply_adjustments(row) for row in df.to_dict(orient="records")]


def get_renewal_activities(renewal_id: str) -> list[dict]:
    df = pd.read_csv(DATA_DIR / "renewal_activity_log.csv")
    return df[df["renewal_id"] == renewal_id].to_dict(orient="records")


def get_rep_hierarchy(am_owner: str) -> dict | None:
    df = load_all()["rep_hierarchy"]
    match = df[df["am_owner"] == am_owner]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_account_context(account_id: str) -> dict:
    """
    Own copy of Agent 3's account aggregator (open ticket count, usage
    direction, invoice status) - used only by compute_risk_score to
    cross-reference real account health, not for any user-facing screen
    of this agent.
    """
    tables = load_all()

    account_rows = tables["accounts"][tables["accounts"]["account_id"] == account_id]
    if account_rows.empty:
        raise KeyError(f"Unknown account_id: {account_id}")

    usage = tables["product_usage"][tables["product_usage"]["account_id"] == account_id]
    usage = usage.sort_values("week_ending").tail(USAGE_TREND_WEEKS)
    usage_trend = usage["usage_score"].tolist()
    usage_direction = "flat"
    if len(usage_trend) >= 2:
        delta = usage_trend[-1] - usage_trend[0]
        usage_direction = "up" if delta > 5 else "down" if delta < -5 else "flat"

    invoices = tables["invoices_payments"][tables["invoices_payments"]["account_id"] == account_id]
    overdue_invoices = invoices[invoices["status"] == "overdue"]

    tickets = tables["tickets"][tables["tickets"]["account_id"] == account_id]

    return {
        "usage": {"direction": usage_direction},
        "invoices": {
            "overdue_count": int(len(overdue_invoices)),
            "overdue_summary": (
                f"{len(overdue_invoices)} invoice(s) over 30 days"
                if len(overdue_invoices) > 0 else "Current"
            ),
        },
        "tickets": {"open_count": int(len(tickets))},
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
