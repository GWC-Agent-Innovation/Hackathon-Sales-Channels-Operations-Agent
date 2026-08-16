import csv
import io
import logging
import re

from . import mailer
from .domo_client import get_dataset_id, query_dataset
from .domo_dataset_plugin import DomoDatasetUploader

logger = logging.getLogger("domo_service")

OPPORTUNITY_COLUMNS = [
    "opportunity_id",
    "account_id",
    "account_name",
    "am_owner_name",
    "signal_id",
    "signal_type",
    "detected_signal",
    "current_products",
    "opportunity_type",
    "recommended_product",
    "recommended_product_sku",
    "potential_arr_usd",
    "fit_score_signal_strength",
    "fit_score_support_context",
    "fit_score_timing_fit",
    "fit_score_account_health",
    "fit_score_total",
    "outreach_subject",
    "outreach_draft",
    "status",
    "discard_reason",
    "outcome",
    "created_date",
]


def _rows(response: dict | None) -> list | None:
    if not response:
        return None
    columns = response.get("columns") or []
    return [dict(zip(columns, row)) for row in (response.get("rows") or [])]


def get_accounts() -> list | None:
    dataset_id = get_dataset_id("accounts")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, "SELECT * FROM table"))


def get_account_by_id(account_id: str) -> list | None:
    dataset_id = get_dataset_id("accounts")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, f"SELECT * FROM table WHERE account_id = '{account_id}'"))


def get_signals_by_account_id(account_id: str) -> list | None:
    dataset_id = get_dataset_id("detected_signals")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, f"SELECT * FROM table WHERE account_id = '{account_id}'"))


def get_tickets() -> list | None:
    dataset_id = get_dataset_id("tickets")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, "SELECT * FROM table"))


def get_tickets_by_account_id(account_id: str) -> list | None:
    dataset_id = get_dataset_id("tickets")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, f"SELECT * FROM table WHERE account_id = '{account_id}'"))


def get_product_catalog() -> list | None:
    dataset_id = get_dataset_id("product_catalog")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, "SELECT * FROM table"))


def get_opportunities() -> list | None:
    dataset_id = get_dataset_id("opportunities")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, "SELECT * FROM table"))


def get_opportunity_by_id(opp_id: str) -> list | None:
    dataset_id = get_dataset_id("opportunities")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, f"SELECT * FROM table WHERE opportunity_id = '{opp_id}'"))


def get_opportunities_by_account_id(account_id: str) -> list | None:
    dataset_id = get_dataset_id("opportunities")
    if not dataset_id:
        return None
    return _rows(query_dataset(dataset_id, f"SELECT * FROM table WHERE account_id = '{account_id}'"))


async def replace_opportunities(
    rows: list[dict],
    *,
    triggered_account_id: str | None = None,
    triggered_action: str | None = None,
    triggered_to_emails: list[str] | None = None,
) -> bool:
    dataset_id = get_dataset_id("opportunities")
    if not dataset_id:
        return False

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=OPPORTUNITY_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in OPPORTUNITY_COLUMNS})

    uploader = DomoDatasetUploader()
    ok = await uploader.upload_csv_data(dataset_id, buffer.getvalue(), action="REPLACE")

    if ok and triggered_action == "approved" and triggered_account_id:
        row = next((r for r in rows if r.get("account_id") == triggered_account_id), None)
        if row:
            await _send_approval_email(row, to_emails=triggered_to_emails)

    return ok


async def append_opportunity(row: dict) -> bool:
    dataset_id = get_dataset_id("opportunities")
    if not dataset_id:
        return False

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=OPPORTUNITY_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerow({col: row.get(col, "") for col in OPPORTUNITY_COLUMNS})

    uploader = DomoDatasetUploader()
    return await uploader.upload_csv_data(dataset_id, buffer.getvalue(), action="APPEND")


CUSTOMER_NAME_PLACEHOLDER = re.compile(
    r"\[\s*(?:customer|contact|client|account)\s+name\s*\]", re.IGNORECASE
)


async def _send_approval_email(row: dict, *, to_emails: list[str] | None = None) -> None:
    account_name = row.get("account_name") or ""
    potential_arr_usd = row.get("potential_arr_usd") or ""
    outreach_draft = CUSTOMER_NAME_PLACEHOLDER.sub(f"{account_name} team", row.get("outreach_draft") or "")
    try:
        await mailer.send_opportunity_email(
            subject=row.get("outreach_subject") or f"Scaling {account_name}'s coverage",
            to_emails=to_emails,
            greeting_name=row.get("am_owner_name") or "",
            intro_html=outreach_draft,
            ask_html="",
            opportunity_value=f"${potential_arr_usd}" if potential_arr_usd else "",
            product=row.get("recommended_product") or "",
            account_name=account_name,
            opportunity_id=row.get("opportunity_id") or "",
        )
    except mailer.MailNotConfigured as e:
        logger.warning("Skipped approval email for %s: %s", row.get("account_id"), e)
    except Exception:
        logger.exception("Failed to send approval email for %s", row.get("account_id"))
