"""Writes Agent 3 output back to its own append-only logs."""
from . import data_store


def log_call_notes(account_id: str, meeting_id: str, am_rep: str, notes_text: str) -> str:
    log_id = data_store.next_log_id("call_notes_log.csv", "log_id", "CN")
    data_store.append_row("call_notes_log.csv", {
        "log_id": log_id,
        "account_id": account_id,
        "meeting_id": meeting_id,
        "am_rep": am_rep,
        "timestamp": data_store.now_iso(),
        "call_notes_text": notes_text,
    })
    return log_id


def write_approved_tasks(account_id: str, actions: list[dict], approved_by: str) -> list[dict]:
    written = []
    for action in actions:
        task_id = data_store.next_log_id("crm_tasks_log.csv", "task_id", "TASK")
        row = {
            "task_id": task_id,
            "account_id": account_id,
            "type": action["type"],
            "description": action["description"],
            "status": "approved",
            "created_at": data_store.now_iso(),
            "approved_by": approved_by,
        }
        data_store.append_row("crm_tasks_log.csv", row)
        written.append(row)
    return written
