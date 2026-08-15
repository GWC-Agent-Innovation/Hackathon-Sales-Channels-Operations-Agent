import csv
import threading
from datetime import date
from . import config

_lock = threading.Lock()

_reps: dict[str, dict] = {}
_targets: dict[str, dict] = {}
_history: dict[str, list[dict]] = {}
_coaching_tasks: dict[str, dict] = {}
_recognition_nominations: dict[str, dict] = {}

COACHING_TASK_FIELDS = ["id", "rep_id", "manager_name", "gap_summary", "created_date", "status"]
RECOGNITION_FIELDS = ["id", "rep_id", "note", "created_date", "status"]


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _float_or_none(value):
    value = (value or "").strip()
    return float(value) if value else None


def load_all():
    with _lock:
        _reps.clear()
        for row in _read_csv(config.REPS_CSV):
            _reps[row["id"]] = row

        _targets.clear()
        for row in _read_csv(config.TARGETS_CSV):
            row["conversion_ratio_target"] = _float_or_none(row.get("conversion_ratio_target"))
            row["deal_value_target"] = _float_or_none(row.get("deal_value_target"))
            row["churn_rate_target"] = _float_or_none(row.get("churn_rate_target"))
            _targets[row["rep_id"]] = row

        _history.clear()
        for row in _read_csv(config.PERFORMANCE_HISTORY_CSV):
            row["activity_volume"] = _float_or_none(row.get("activity_volume"))
            row["conversion_ratio"] = _float_or_none(row.get("conversion_ratio"))
            row["deal_value"] = _float_or_none(row.get("deal_value"))
            row["churn_rate"] = _float_or_none(row.get("churn_rate"))
            _history.setdefault(row["rep_id"], []).append(row)
        for hist in _history.values():
            hist.sort(key=lambda r: r["period"])

        _coaching_tasks.clear()
        for row in _read_csv(config.COACHING_TASKS_CSV):
            _coaching_tasks[row["id"]] = row

        _recognition_nominations.clear()
        for row in _read_csv(config.RECOGNITION_NOMINATIONS_CSV):
            _recognition_nominations[row["id"]] = row


def list_reps():
    return sorted(_reps.values(), key=lambda r: r["name"])


def get_rep(rep_id: str):
    return _reps.get(rep_id)


def get_target(rep_id: str):
    return _targets.get(rep_id)


def get_history(rep_id: str):
    return _history.get(rep_id, [])


def list_coaching_tasks():
    return sorted(_coaching_tasks.values(), key=lambda t: t["created_date"], reverse=True)


def list_recognition_nominations():
    return sorted(_recognition_nominations.values(), key=lambda n: n["created_date"], reverse=True)


def create_coaching_task(rep_id: str, manager_name: str, gap_summary: str) -> dict:
    with _lock:
        next_id = f"COACH-{len(_coaching_tasks) + 1}"
        row = {
            "id": next_id, "rep_id": rep_id, "manager_name": manager_name,
            "gap_summary": gap_summary, "created_date": date.today().isoformat(), "status": "Open",
        }
        _coaching_tasks[next_id] = row
        _persist_coaching_tasks()
        return row


def create_recognition_nomination(rep_id: str, note: str) -> dict:
    with _lock:
        next_id = f"REC-{len(_recognition_nominations) + 1}"
        row = {
            "id": next_id, "rep_id": rep_id, "note": note,
            "created_date": date.today().isoformat(), "status": "Pending SLT Review",
        }
        _recognition_nominations[next_id] = row
        _persist_recognition_nominations()
        return row


def update_recognition_nomination(nomination_id: str, status: str) -> dict | None:
    with _lock:
        row = _recognition_nominations.get(nomination_id)
        if not row:
            return None
        row["status"] = status
        _persist_recognition_nominations()
        return row


def _persist_coaching_tasks():
    with open(config.COACHING_TASKS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COACHING_TASK_FIELDS)
        writer.writeheader()
        for row in _coaching_tasks.values():
            writer.writerow(row)


def _persist_recognition_nominations():
    with open(config.RECOGNITION_NOMINATIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RECOGNITION_FIELDS)
        writer.writeheader()
        for row in _recognition_nominations.values():
            writer.writerow(row)


load_all()
