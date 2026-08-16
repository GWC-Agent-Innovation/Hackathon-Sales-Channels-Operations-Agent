import hashlib
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
    "profile, a detected signal, and open tickets, decide whether this is an upsell "
    "(expand an owned product) or cross-sell (recommend a new product). "
    "\n\n"
    "RULE 1 — Signal required. This function is only called when a signal already "
    "exists for the account, so you can assume that has been checked. Tickets are "
    "supporting context only — never the reason to recommend a product on their own. "
    "\n\n"
    "RULE 2 — Verify ownership before cross-sell. Before recommending a cross-sell "
    "product, verify it is NOT already listed in the account's 'products_owned' field. "
    "A support ticket mentioning a capability (e.g. 'backup restore test') often means "
    "the customer ALREADY has that product — treat this as evidence of ownership or "
    "usage, not as a gap to sell into. "
    "\n\n"
    "RULE 3 — Do not state a dollar value. Pricing and fit scoring are computed "
    "separately by the system, not by you. Do not include any 'opportunity_value' or "
    "dollar figure in your reasoning or outreach draft — leave pricing out of your "
    "response entirely. "
    "\n\n"
    "RULE 4 — Trace every claim. Every fact you state (product, ticket, severity, "
    "status, sentiment, signal) must be traceable to what was given to you in the "
    "prompt. Never invent facts."
)

SIGNAL_STRENGTH = {
    "acquisition": 35,
    "security_incident": 32,
    "compliance_deadline": 30,
    "headcount_growth": 28,
    "usage_increase": 22,
    "new_office": 18,
    "expiring_addon": 15,
}

ACCOUNT_HEALTH = {
    "At Risk": 4,
    "Neutral": 13,
    "Positive": 20,
}


def _account_health_score(sentiment: str) -> int:
    return ACCOUNT_HEALTH.get((sentiment or "").strip(), 13)


def _support_context_score(tickets: list | None) -> int:
    has_open = any((t.get("status") or "").strip() == "Open" for t in (tickets or []))
    return 12 if has_open else 3


def _timing_fit_score(renewal_date: str, detected_date: str) -> int:
    try:
        renewal = date.fromisoformat(renewal_date)
        detected = date.fromisoformat(detected_date)
    except (TypeError, ValueError):
        return 10
    days = (renewal - detected).days
    if 0 <= days <= 90:
        return 25
    elif 90 < days <= 270:
        return 18
    else:
        return 10


def _deterministic_unit_interval(*parts: str) -> float:
    """Stable pseudo-random float in [0,1) seeded from the given parts, so the
    same account/signal/product always prices the same way instead of
    re-rolling on every regeneration."""
    key = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _potential_arr_usd(
    opportunity_type: str,
    list_price_arr: float,
    account_id: str,
    signal_id: str,
    sku: str,
) -> int:
    if not list_price_arr:
        return 0
    jitter = _deterministic_unit_interval(account_id, signal_id, sku)
    if opportunity_type == "cross-sell":
        # historically ~0.85x - 1.15x list price
        ratio = 0.85 + jitter * 0.30
    else:  # upsell
        # historically ~0.35x - 0.60x list price (partial expansion, not a full new license)
        ratio = 0.35 + jitter * 0.25
    return int(round(list_price_arr * ratio, -2))


def compute_fit_scores(account: dict, signal: dict, tickets: list | None, opportunity_type: str) -> dict:
    signal_strength = SIGNAL_STRENGTH.get((signal.get("signal_type") or "").strip(), 15)
    support_context = _support_context_score(tickets)
    timing_fit = _timing_fit_score(account.get("renewal_date"), signal.get("detected_date"))
    account_health = _account_health_score(account.get("sentiment"))
    total = signal_strength + support_context + timing_fit + account_health
    return {
        "signal_strength": signal_strength,
        "support_context": support_context,
        "timing_fit": timing_fit,
        "account_health": account_health,
        "total": total,
    }


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

    if not signals:
        return {
            "account_id": account_id,
            "skipped": True,
            "lead_type": "support_driven" if tickets else "no_signal",
            "reason": (
                f"No detected signal on file for account '{account_id}'. Opportunities are only "
                f"generated from detected_signals.csv; open tickets alone cannot trigger one."
            ),
        }

    catalog = get_product_catalog()

    # NOTE: potential_arr_usd is deliberately NOT part of what we ask the LLM
    # for anymore - see SYSTEM_PROMPT RULE 3 and compute_fit_scores() below.
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

    owned_products = set(
        p.strip() for p in account[0].get("products_owned", "").split(",") if p.strip()
    )
    recommended_raw = str(parsed.get("recommended_product", ""))
    recommended_base = recommended_raw.replace(" (expanded coverage)", "").strip()

    normalized_opp_type = str(opp_type).strip().lower().replace("_", "-")
    if normalized_opp_type == "cross-sell" and recommended_base in owned_products:
        return {
            "account_id": account_id,
            "skipped": True,
            "reason": (
                f"Recommended product '{recommended_base}' is already owned by this "
                f"account — likely miscategorized as cross-sell instead of upsell."
            ),
        }

    result = {"account_id": account_id, **parsed}

    signal = signals[0]
    product = _lookup_product(catalog, recommended_base)

    existing_rows = get_opportunities() or []
    existing_row = next(
        (r for r in existing_rows
         if r.get("account_id") == account_id and r.get("signal_id") == signal.get("signal_id")),
        None,
    )

    scores = compute_fit_scores(
        account=account[0],
        signal=signal,
        tickets=tickets,
        opportunity_type=normalized_opp_type,
    )

    potential_arr_usd = _potential_arr_usd(
        opportunity_type=normalized_opp_type,
        list_price_arr=float(product.get("list_price_arr") or 0),
        account_id=account_id,
        signal_id=signal.get("signal_id", ""),
        sku=product.get("product_id", ""),
    )

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
        "potential_arr_usd": potential_arr_usd,
        "fit_score_signal_strength": scores["signal_strength"],
        "fit_score_support_context": scores["support_context"],
        "fit_score_timing_fit": scores["timing_fit"],
        "fit_score_account_health": scores["account_health"],
        "fit_score_total": scores["total"],
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

    result["opportunity_value"] = potential_arr_usd
    result["fit_scores"] = scores
    return result


def _build_prompt(account_resp, signals_resp, tickets_resp, catalog_resp) -> str:
    return (
        f"Account: {account_resp}\n"
        f"Signal: {signals_resp}\n"
        f"Open tickets: {tickets_resp if tickets_resp else 'None'}\n"
        f"Product catalog (for reference — DO NOT quote prices from this): {catalog_resp}\n\n"
        f"Return JSON with keys: opportunity_type, recommended_product, reasoning, "
        f"outreach_subject, outreach_draft. Do NOT include a dollar value anywhere "
        f"in your response — pricing is calculated separately by the system."
    )
