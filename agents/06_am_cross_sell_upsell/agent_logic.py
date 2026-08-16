import json
import re
from datetime import date

from .domo_service import (
    get_account_by_id,
    get_signals_by_account_id,
    get_tickets_by_account_id,
    get_product_catalog,
    get_opportunities,
    append_opportunity,
    replace_opportunities,
)
from .domo_client import generate_text

SYSTEM_PROMPT = (
    "You are a cross-sell/upsell assistant for an Account Manager. Given an account's "
    "profile, any detected signals, open tickets, and the product catalog, decide whether "
    "this is an upsell (expand an owned product) or cross-sell (recommend a new product), "
    "and draft a short, specific outreach email. If no signal is present, base the "
    "recommendation on the account profile (owned products, sentiment, risk) and open "
    "tickets. Never invent facts beyond what is given."
)


def _parse_llm_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _next_opportunity_id(existing: list | None) -> str:
    max_n = 500
    for row in existing or []:
        opp_id = str(row.get("opportunity_id") or "")
        prefix, _, n = opp_id.partition("-")
        if prefix == "UP" and n.isdigit():
            max_n = max(max_n, int(n))
    return f"UP-{max_n + 1}"


def _lookup_product(catalog: list | None, product_name: str | None) -> dict:
    for product in catalog or []:
        if (product.get("name") or "").strip().lower() == (product_name or "").strip().lower():
            return product
    return {}


async def generate_opportunity_for_account(account_id: str) -> dict | None:
    account = get_account_by_id(account_id)
    if not account:
        return {"error": f"No opportunity generated - account '{account_id}' not found"}

    signals = get_signals_by_account_id(account_id)
    tickets = get_tickets_by_account_id(account_id)
    catalog = get_product_catalog()

    prompt = _build_prompt(account[0], signals, tickets, catalog)
    raw = generate_text(prompt, system=SYSTEM_PROMPT)
    parsed = _parse_llm_json(raw)
    if not parsed:
        return {"error": "No opportunity generated - could not parse LLM response"}

    opp_type = parsed.get("opportunity_type")
    if not opp_type or str(opp_type).strip().lower() in ("none", "no opportunity", "skip"):
        return {
            "account_id": account_id,
            "skipped": True,
            "reason": parsed.get("reasoning"),
        }

    result = {"account_id": account_id, **parsed}

    signal = signals[0] if signals else {}
    product = _lookup_product(catalog, parsed.get("recommended_product"))
    existing_rows = get_opportunities() or []
    existing_row = next((r for r in existing_rows if r.get("account_id") == account_id), None)

    row = {
        "opportunity_id": existing_row["opportunity_id"] if existing_row else _next_opportunity_id(existing_rows),
        "account_id": account_id,
        "account_name": account[0].get("account_name", ""),
        "am_owner_name": account[0].get("am_owner_name", ""),
        "signal_id": signal.get("signal_id", ""),
        "signal_type": signal.get("signal_type", ""),
        "detected_signal": signal.get("detected_signal", ""),
        "current_products": account[0].get("products_owned", ""),
        "opportunity_type": parsed.get("opportunity_type", ""),
        "recommended_product": parsed.get("recommended_product", ""),
        "recommended_product_sku": product.get("product_id", ""),
        "potential_arr_usd": product.get("list_price_arr", ""),
        "fit_score_signal_strength": "",
        "fit_score_support_context": "",
        "fit_score_timing_fit": "",
        "fit_score_account_health": "",
        "fit_score_total": "",
        "outreach_subject": parsed.get("outreach_subject", ""),
        "outreach_draft": parsed.get("outreach_draft", ""),
        "status": "proposed",
        "discard_reason": "",
        "outcome": "",
        "created_date": date.today().isoformat(),
    }

    if existing_row:
        existing_row.update(row)
        persisted = await replace_opportunities(existing_rows)
    else:
        persisted = await append_opportunity(row)

    if not persisted:
        result["persist_warning"] = (
            "Generated but failed to save to Domo - it will not be actionable until retried."
        )

    return result


def _build_prompt(account_resp, signals_resp, tickets_resp, catalog_resp) -> str:
    return (
        f"Account: {account_resp}\n"
        f"Signals: {signals_resp if signals_resp else 'No signal detected'}\n"
        f"Open tickets: {tickets_resp if tickets_resp else 'None'}\n"
        f"Product catalog: {catalog_resp}\n\n"
        f"Return JSON with keys: opportunity_type, recommended_product, reasoning, "
        f"outreach_subject, outreach_draft."
    )
