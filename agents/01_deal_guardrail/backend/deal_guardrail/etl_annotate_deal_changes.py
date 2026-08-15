"""
Adds "existing customer changing an existing subscription" context to
deals.csv, on top of the base import from import_deals_from_excel.py.

A deal qualifies when the account already owns at least one product in the
deal's bundle (per entitlements.csv) - i.e. this isn't a brand-new sale,
it's the customer asking to change something they already have (more
seats, fewer seats, or a straight renewal at the same count).

None of this exists in the source workbook (deals.csv/entitlements.csv
only capture the *current* state, not a request-to-change-it), so
`previous_quantity` and `change_reason` are synthesized here - deliberately
including a few cases where the quantity direction and the stated reason
DON'T agree (e.g. quantity going up but the reason is lukewarm, or going
down for an administrative reason rather than a churn one), because those
mismatches are exactly where the LLM's read on intent adds value beyond
just diffing two numbers.

Run after etl_import_deals_from_excel.py (from the SAS/ project root):
    python agents/agent1_deal_guardrail/backend/deal_guardrail/etl_annotate_deal_changes.py
"""
import random
from pathlib import Path

import pandas as pd

THIS_BACKEND = Path(__file__).resolve().parent.parent  # agents/agent1_deal_guardrail/backend
AGENTS_ROOT = THIS_BACKEND.parent.parent                # agents/
DATA_DIR = THIS_BACKEND / "data"
AM_DATA_DIR = AGENTS_ROOT / "agent3_am_account_context" / "backend" / "data"

# (reason text, intended sentiment) - "intended" is only used to pick a
# balanced spread while writing the data; the agent re-derives sentiment
# itself from the text at review time, it never reads this label.
POSITIVE_REASONS = [
    "Customer acquired a smaller regional competitor and needs to cover the new hires",
    "Opening a second office location and wants everyone on the same footprint",
    "Business grew faster than forecast this quarter, existing seats are maxed out",
    "Rolling this out to a newly onboarded department after a successful pilot",
    "Landed a large new contract and is scaling their team to support it",
]
NEGATIVE_REASONS = [
    "Customer is reducing headcount after a round of layoffs",
    "Said budget was cut this cycle and they need to scale back spend",
    "Migrating part of their environment to a competitor product",
    "Flagged ongoing dissatisfaction with support response times and wants a smaller footprint",
    "Restructuring the team and consolidating licenses down to active users only",
]
NEUTRAL_REASONS = [
    "Straight renewal at the same seat count, no change in usage",
    "Routine annual true-up to match current headcount, no material change",
    "Administrative cleanup of unused seats flagged during a license audit",
    "Renewing as-is while they evaluate their roadmap for next year",
]


def pick_previous_quantity(rng: random.Random, quantity: int, direction: str) -> int:
    if direction == "increase":
        return max(1, quantity - rng.randint(2, max(3, quantity // 3 or 3)))
    if direction == "decrease":
        return quantity + rng.randint(2, max(3, quantity // 2 or 3))
    return quantity  # no_change


def main():
    deals = pd.read_csv(DATA_DIR / "deals.csv")
    entitlements = pd.read_csv(AM_DATA_DIR / "entitlements.csv")
    owned_lookup = {
        (row["account_id"], row["product"]) for _, row in entitlements.iterrows() if row["owned"]
    }

    rng = random.Random("agent1-deal-changes")

    is_change, prev_qty, reasons = [], [], []
    # deterministic-ish round-robin across scenarios so all 3 (+ mismatch) cases exist
    scenario_cycle = ["increase_positive", "decrease_negative", "no_change_neutral",
                       "increase_weak", "decrease_admin"]
    cycle_idx = 0

    for _, deal in deals.iterrows():
        products = [p.strip() for p in deal["product_bundle"].split("+")]
        owns_any = any((deal["account_id"], p) in owned_lookup for p in products)

        if not owns_any:
            is_change.append(False)
            prev_qty.append("")
            reasons.append("")
            continue

        scenario = scenario_cycle[cycle_idx % len(scenario_cycle)]
        cycle_idx += 1

        if scenario == "increase_positive":
            direction, reason = "increase", rng.choice(POSITIVE_REASONS)
        elif scenario == "decrease_negative":
            direction, reason = "decrease", rng.choice(NEGATIVE_REASONS)
        elif scenario == "no_change_neutral":
            direction, reason = "no_change", rng.choice(NEUTRAL_REASONS)
        elif scenario == "increase_weak":
            # quantity is going up, but the stated reason doesn't clearly justify it
            direction, reason = "increase", rng.choice(NEUTRAL_REASONS)
        else:  # decrease_admin - going down for a non-churn, administrative reason
            direction, reason = "decrease", rng.choice(NEUTRAL_REASONS)

        is_change.append(True)
        prev_qty.append(pick_previous_quantity(rng, int(deal["quantity"]), direction))
        reasons.append(reason)

    deals["is_existing_customer_change"] = is_change
    deals["previous_quantity"] = prev_qty
    deals["change_reason"] = reasons
    deals.to_csv(DATA_DIR / "deals.csv", index=False)

    n_change = sum(is_change)
    print(f"Annotated {n_change} of {len(deals)} deals as existing-customer subscription changes.")


if __name__ == "__main__":
    main()
