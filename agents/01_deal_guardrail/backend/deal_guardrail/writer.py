"""Writes Agent 1 output back to its own append-only logs."""
from . import data_store


def write_deal_decision(deal_id: str, decision: str, reviewer: str, comment: str | None) -> dict:
    review_id = data_store.next_log_id("deal_review_log.csv", "review_id", "REV")
    row = {
        "review_id": review_id,
        "deal_id": deal_id,
        "decision": decision,
        "reviewer": reviewer,
        "comment": comment or "",
        "decided_at": data_store.now_iso(),
    }
    data_store.append_row("deal_review_log.csv", row)
    return row
