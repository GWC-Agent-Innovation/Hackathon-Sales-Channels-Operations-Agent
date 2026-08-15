"""
Agent 1 (Deal Guardrail & Order Validation) — self-contained data access.

    deals.csv                 -> CRM closed-won deals
    shipping_addresses.csv    -> order/fulfillment ship-to records
    deal_review_log.csv        -> written by writer.py (Screen 3 output)

Fully self-contained: this agent never reads another agent's data folder.
"""
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # backend/data (sibling of this package)


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name)


@lru_cache(maxsize=1)
def load_all() -> dict[str, pd.DataFrame]:
    return {
        "deals": _read("deals.csv"),
        "shipping_addresses": _read("shipping_addresses.csv"),
    }


def get_deal_row(deal_id: str) -> dict | None:
    df = load_all()["deals"]
    match = df[df["deal_id"] == deal_id]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}


def get_shipping_address(account_id: str) -> dict | None:
    df = load_all()["shipping_addresses"]
    match = df[df["account_id"] == account_id]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {k: ("" if pd.isna(v) else v) for k, v in row.items()}


def get_pending_deals() -> list[dict]:
    """Every deal not yet decided by Sales Ops (or auto-approved by the
    agent) - i.e. not present in deal_review_log.csv."""
    reviewed_ids = set(pd.read_csv(DATA_DIR / "deal_review_log.csv")["deal_id"])
    deals = load_all()["deals"]
    pending = deals[~deals["deal_id"].isin(reviewed_ids)]
    pending = pending.astype(object).where(pd.notnull(pending), None)
    return pending.to_dict(orient="records")


def get_deal_decision(deal_id: str) -> dict | None:
    df = pd.read_csv(DATA_DIR / "deal_review_log.csv", keep_default_na=False)
    match = df[df["deal_id"] == deal_id]
    if match.empty:
        return None
    return match.sort_values("decided_at").iloc[-1].to_dict()


def get_deal_decisions() -> list[dict]:
    df = pd.read_csv(DATA_DIR / "deal_review_log.csv", keep_default_na=False)
    df = df.sort_values("decided_at", ascending=False)
    return df.to_dict(orient="records")


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
