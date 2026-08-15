"""
Agent 1 — Sales Deal Guardrail & Order Validation Agent.

Two-tier design, deliberately split so Screen 1 (the queue) stays fast
and cheap while Screen 2 (the detail view) does the expensive reasoning:

  1. `run_rules_engine` - deterministic, no LLM call. Runs on every deal
     in the queue so Screen 1 can show a fit_status instantly for all of
     them at once.
  2. `build_deal_detail` - calls Groq to turn the rule-engine output into
     a confidence score, a plain-English rationale trace, and a
     recommended action, for one deal at a time (Screen 2, on click).

Business rules encoded below are our own config standing in for "billing
model rules" / "product SKU capability matrix" - the org workbook doesn't
publish these as data, so they're written here the same way Agent 3's
SYSTEM_PROMPT is code, not a fabricated fact about any one account.
"""
import json

from .domo_client import DomoClient, parse_json_response

from . import data_store

MONTHLY_MAX_TERM_MONTHS = 24  # a 36mo commitment billed Monthly isn't a supported structure
PLATFORM_RESTRICTED_MONTHLY_PRODUCTS = {"AuthPoint", "DNSWatch"}  # need provisioning input if billed Monthly
MIN_SANE_QUANTITY = 4
MAX_SANE_QUANTITY = 100
REQUIRED_ADDRESS_FIELDS = ["street", "city", "region", "postal_code", "country"]


def _address_gaps(address: dict) -> list[str]:
    if not address:
        return ["No shipping address on file for this account."]
    gaps = []
    for field in REQUIRED_ADDRESS_FIELDS:
        value = str(address.get(field, "")).strip()
        if not value:
            gaps.append(f"missing {field.replace('_', ' ')}")
    if str(address.get("country", "")).strip().upper() == "TBD":
        gaps.append("country is a placeholder (\"TBD\"), not a real value")
    return gaps


def compute_change_type(deal: dict) -> str | None:
    """
    Deterministic (no LLM): compares requested quantity to the account's
    previous quantity on this subscription. Returns None for brand-new
    sales (deal["is_existing_customer_change"] is False) - the
    increase/decrease/no_change classification only applies when the
    customer already has this product and is asking to change it.
    """
    if not deal.get("is_existing_customer_change"):
        return None
    prev = deal.get("previous_quantity")
    if prev is None:
        return None
    if deal["quantity"] > prev:
        return "increase"
    if deal["quantity"] < prev:
        return "decrease"
    return "no_change"


def run_rules_engine(deal: dict, address: dict | None) -> dict:
    """
    Deterministic pass. Returns {fit_status, violations: [{severity, category, message}]}
    severity: "hard" (blocks auto-clear) | "soft" (lowers confidence, doesn't block)
    category: "exception" (rep/config issue) | "escalated" (needs ERP-integration/platform input)
    """
    violations = []
    products = [p.strip() for p in deal["product_bundle"].split("+")]

    if deal["discount_pct"] > deal["max_discount_pct"]:
        violations.append({
            "severity": "hard",
            "category": "exception",
            "message": (
                f"Requested discount of {deal['discount_pct']:.0f}% exceeds the "
                f"{deal['max_discount_pct']:.0f}% ceiling approved for {deal['billing_model']} "
                f"billing at this quantity tier."
            ),
        })

    if deal["billing_model"] == "Monthly" and deal["term_months"] > MONTHLY_MAX_TERM_MONTHS:
        violations.append({
            "severity": "hard",
            "category": "escalated",
            "message": (
                f"{deal['term_months']}mo term billed Monthly isn't a structure the billing "
                f"platform supports today (Monthly tops out at {MONTHLY_MAX_TERM_MONTHS}mo) - "
                f"needs ERP-Integration input on how to represent this."
            ),
        })

    restricted_hit = [p for p in products if p in PLATFORM_RESTRICTED_MONTHLY_PRODUCTS]
    if deal["billing_model"] == "Monthly" and restricted_hit:
        violations.append({
            "severity": "hard",
            "category": "escalated",
            "message": (
                f"{', '.join(restricted_hit)} isn't provisionable under Monthly billing - "
                f"a product entitlement/provisioning mismatch that needs ERP-Integration input "
                f"before this can post to billing."
            ),
        })

    if deal["quantity"] < MIN_SANE_QUANTITY or deal["quantity"] > MAX_SANE_QUANTITY:
        violations.append({
            "severity": "soft",
            "category": "exception",
            "message": (
                f"Quantity of {deal['quantity']} is outside the usual range "
                f"({MIN_SANE_QUANTITY}-{MAX_SANE_QUANTITY}) for this product mix - worth a sanity check."
            ),
        })

    if deal["requires_hardware_shipment"]:
        gaps = _address_gaps(address)
        if gaps:
            violations.append({
                "severity": "hard",
                "category": "exception",
                "message": f"Ship-to address incomplete for hardware fulfillment: {', '.join(gaps)}.",
            })

    if any(v["severity"] == "hard" and v["category"] == "escalated" for v in violations):
        fit_status = "escalated"
    elif any(v["severity"] == "hard" for v in violations):
        fit_status = "exception"
    elif violations:  # only soft violations
        fit_status = "exception"
    else:
        fit_status = "auto-cleared"

    return {
        "fit_status": fit_status,
        "violations": violations,
        "change_type": compute_change_type(deal),
    }


def config_summary(deal: dict) -> str:
    base = (
        f"{deal['quantity']}x {deal['product_bundle']}, {deal['discount_pct']:.0f}% discount, "
        f"{deal['term_months']}mo {deal['billing_model']}"
    )
    change_type = compute_change_type(deal)
    if change_type == "increase":
        return f"{base} (up from {int(deal['previous_quantity'])})"
    if change_type == "decrease":
        return f"{base} (down from {int(deal['previous_quantity'])})"
    if change_type == "no_change":
        return f"{base} (renewal, same seat count)"
    return base


SYSTEM_PROMPT = """You are a Sales Ops deal guardrail assistant. You review one \
closed-won deal that a rep submitted, plus the results of a deterministic rules \
engine that already checked it against billing/product platform capability rules \
(discount ceilings, term/billing-model compatibility, provisioning restrictions, \
quantity sanity, and shipping address completeness for hardware).

Some deals are an EXISTING customer changing an EXISTING subscription (see \
"existing_customer_change" in the input) - the quantity is moving up (upsell), \
down (downsell), or staying flat (renewal), and the rep logged a reason for the \
change. For these deals only, also do this:

5. Read the "change_reason" text and classify "reason_sentiment" as "positive" \
(a real growth signal - new hires, new business, expansion), "negative" (a risk/ \
churn signal - layoffs, budget cuts, dissatisfaction, moving to a competitor), or \
"neutral" (administrative - a routine renewal/true-up/audit, not clearly either).
6. Write one sentence for "signal_interpretation" that combines the quantity \
direction with the reason's sentiment into something actionable for the AM/Sales \
Ops - and explicitly call out when they DON'T match (e.g. quantity is increasing \
but the stated reason doesn't really justify growth, or quantity is decreasing for \
a reason that looks administrative rather than a churn risk). This is the most \
valuable thing you can add here - don't just restate the numbers.

For deals that are NOT an existing-customer change, omit reason_sentiment and \
signal_interpretation (set both to null).

Your job otherwise:
1. Write a "rationale_trace": 3-5 short steps narrating how you reviewed this deal \
(what you checked, in order, including the change-quantity/reason check when \
applicable) - written like an audit log, grounded only in the fields given, no \
invented details.
2. Write a one-sentence "gap_summary": the single most important issue for Sales \
Ops to act on, or "No gaps found - configuration is clean." if there are none.
3. Give a "confidence_score" 0-100 for how safe it is to auto-approve this deal \
without human review. If ANY rule violation has severity "hard", confidence MUST \
be below 90 (hard violations always require human review). A negative \
reason_sentiment on a downsell should also pull confidence down even with no rule \
violations - that's an account-health signal Sales Ops/the AM should see, not a \
silent auto-approve. If there are no violations and no concerning signal, \
confidence should typically be 90+.
4. Set "recommended_action" to one of: "auto-approve" (confidence >= 90, no hard \
violations, no negative signal), "return-to-rep" (a rep-fixable config issue, e.g. \
discount/quantity/address, OR a downsell with a negative/churn signal that the AM \
should be looped in on before processing), or "escalate-to-erp-integration" (a \
platform/provisioning limitation the rep can't fix themselves).

Respond with ONLY a JSON object of this exact shape:
{
  "rationale_trace": [string, ...],
  "gap_summary": string,
  "reason_sentiment": "positive" | "negative" | "neutral" | null,
  "signal_interpretation": string or null,
  "confidence_score": integer 0-100,
  "recommended_action": "auto-approve" | "return-to-rep" | "escalate-to-erp-integration"
}
"""


def build_detail_from_rules_only(deal_id: str) -> dict:
    """
    Cheap path for an already-decided deal: no Groq call, just the same
    non-LLM fields build_deal_detail would return. The caller (main.py)
    overlays the recorded decision on top instead of LLM-generated
    rationale/confidence, since re-litigating a finalized deal isn't useful.
    """
    deal = data_store.get_deal_row(deal_id)
    if deal is None:
        raise KeyError(f"Unknown deal_id: {deal_id}")

    address = data_store.get_shipping_address(deal["account_id"])
    rules_result = run_rules_engine(deal, address)

    return {
        "deal_id": deal_id,
        "account_id": deal["account_id"],
        "account_name": deal["account_name"],
        "rep": deal["rep"],
        "rep_role": deal["rep_role"],
        "product_bundle": deal["product_bundle"],
        "quantity": deal["quantity"],
        "discount_pct": deal["discount_pct"],
        "max_discount_pct": deal["max_discount_pct"],
        "billing_model": deal["billing_model"],
        "term_months": deal["term_months"],
        "arr": deal["arr"],
        "requires_hardware_shipment": deal["requires_hardware_shipment"],
        "shipping_address": address,
        "fit_status": rules_result["fit_status"],
        "violations": rules_result["violations"],
        "is_existing_customer_change": bool(deal.get("is_existing_customer_change")),
        "quantity_change_type": rules_result["change_type"],
        "previous_quantity": int(deal["previous_quantity"]) if deal["previous_quantity"] is not None else None,
        "change_reason": deal["change_reason"],
    }


def build_deal_detail(deal_id: str, client: DomoClient) -> dict:
    deal = data_store.get_deal_row(deal_id)
    if deal is None:
        raise KeyError(f"Unknown deal_id: {deal_id}")

    address = data_store.get_shipping_address(deal["account_id"])
    rules_result = run_rules_engine(deal, address)

    llm_input = {
        "deal": {
            "account_name": deal["account_name"],
            "rep": deal["rep"],
            "rep_role": deal["rep_role"],
            "product_bundle": deal["product_bundle"],
            "quantity": deal["quantity"],
            "discount_pct": deal["discount_pct"],
            "max_discount_pct": deal["max_discount_pct"],
            "billing_model": deal["billing_model"],
            "term_months": deal["term_months"],
            "arr": deal["arr"],
            "requires_hardware_shipment": deal["requires_hardware_shipment"],
        },
        "shipping_address": address,
        "rule_engine_violations": rules_result["violations"],
        "existing_customer_change": {
            "quantity_change_type": rules_result["change_type"],
            "previous_quantity": deal["previous_quantity"],
            "change_reason": deal["change_reason"],
        } if deal.get("is_existing_customer_change") else None,
    }

    raw = client.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(llm_input)},
        ],
        json_mode=True,
        temperature=0.1,
    )
    synthesis = parse_json_response(raw)

    return {
        "deal_id": deal_id,
        "account_id": deal["account_id"],
        "account_name": deal["account_name"],
        "rep": deal["rep"],
        "rep_role": deal["rep_role"],
        "product_bundle": deal["product_bundle"],
        "quantity": deal["quantity"],
        "discount_pct": deal["discount_pct"],
        "max_discount_pct": deal["max_discount_pct"],
        "billing_model": deal["billing_model"],
        "term_months": deal["term_months"],
        "arr": deal["arr"],
        "requires_hardware_shipment": deal["requires_hardware_shipment"],
        "shipping_address": address,
        "fit_status": rules_result["fit_status"],
        "violations": rules_result["violations"],
        "is_existing_customer_change": bool(deal.get("is_existing_customer_change")),
        "quantity_change_type": rules_result["change_type"],
        "previous_quantity": int(deal["previous_quantity"]) if deal["previous_quantity"] is not None else None,
        "change_reason": deal["change_reason"],
        "rationale_trace": synthesis.get("rationale_trace", []),
        "gap_summary": synthesis.get("gap_summary"),
        "reason_sentiment": synthesis.get("reason_sentiment"),
        "signal_interpretation": synthesis.get("signal_interpretation"),
        "confidence_score": synthesis.get("confidence_score"),
        "recommended_action": synthesis.get("recommended_action"),
    }
