"""Writes Agent 4 output back to its own append-only logs."""
from . import data_store


def log_renewal_activity(renewal_id: str, actor: str, note: str) -> dict:
    log_id = data_store.next_log_id("renewal_activity_log.csv", "log_id", "RACT")
    row = {
        "log_id": log_id,
        "renewal_id": renewal_id,
        "activity_date": data_store.now_iso()[:10],
        "actor": actor,
        "note": note,
    }
    data_store.append_row("renewal_activity_log.csv", row)
    return row


def adjust_renewal_field(renewal_id: str, field: str, new_value: str, adjusted_by: str) -> dict:
    adjustment_id = data_store.next_log_id("renewal_adjustments_log.csv", "adjustment_id", "ADJ")
    row = {
        "adjustment_id": adjustment_id,
        "renewal_id": renewal_id,
        "field": field,
        "new_value": new_value,
        "adjusted_by": adjusted_by,
        "adjusted_at": data_store.now_iso(),
    }
    data_store.append_row("renewal_adjustments_log.csv", row)
    return row


def log_renewal_escalation(renewal_id: str, level: str, notified: str, action: str) -> dict:
    escalation_id = data_store.next_log_id("renewal_escalation_log.csv", "escalation_id", "ESC")
    row = {
        "escalation_id": escalation_id,
        "renewal_id": renewal_id,
        "level": level,
        "notified": notified,
        "action": action,
        "triggered_at": data_store.now_iso(),
    }
    data_store.append_row("renewal_escalation_log.csv", row)
    return row
