import csv
import threading
from datetime import date
from . import config

_lock = threading.Lock()

_applications: dict[str, dict] = {}
_criteria: list[dict] = []
_conflicts: dict[str, dict] = {}

BOOL_FIELDS = ("is_wholesale_only", "sells_direct", "has_managed_services")

APPLICATION_FIELDS = [
    "id", "company_name", "contact_name", "contact_email", "requested_track", "geography",
    "is_wholesale_only", "sells_direct", "has_managed_services", "volume_or_accounts",
    "submitted_date", "status", "assigned_track", "assigned_tier", "notes",
]


def _to_bool(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_all():
    with _lock:
        _applications.clear()
        for row in _read_csv(config.APPLICATIONS_CSV):
            row["volume_or_accounts"] = int(row["volume_or_accounts"])
            for field in BOOL_FIELDS:
                row[field] = _to_bool(row.get(field, ""))
            _applications[row["id"]] = row

        _criteria.clear()
        for row in _read_csv(config.PROGRAM_CRITERIA_CSV):
            row["discount_pct"] = float(row["discount_pct"])
            row["min_volume_or_accounts"] = int(row["min_volume_or_accounts"])
            row["requires_wholesale_only"] = _to_bool(row["requires_wholesale_only"])
            row["requires_direct_selling"] = _to_bool(row["requires_direct_selling"])
            row["requires_managed_services"] = _to_bool(row["requires_managed_services"])
            _criteria.append(row)

        _conflicts.clear()
        for row in _read_csv(config.CHANNEL_CONFLICTS_CSV):
            _conflicts[row["company_name"]] = row


def list_applications():
    return sorted(_applications.values(), key=lambda a: a["submitted_date"], reverse=True)


def get_application(app_id: str):
    return _applications.get(app_id)


def criteria_for_track(track: str):
    return [c for c in _criteria if c["track"] == track]


def get_conflict(company_name: str):
    return _conflicts.get(company_name)


def add_application(data: dict) -> dict:
    with _lock:
        existing_nums = [int(a["id"].split("-")[1]) for a in _applications.values()]
        next_id = f"APP-{(max(existing_nums) + 1) if existing_nums else 301}"
        row = {field: "" for field in APPLICATION_FIELDS}
        row.update(data)
        row["id"] = next_id
        row["submitted_date"] = date.today().isoformat()
        row["status"] = "Pending"
        row["assigned_track"] = ""
        row["assigned_tier"] = ""
        for field in BOOL_FIELDS:
            row[field] = bool(row.get(field, False))
        row["volume_or_accounts"] = int(row.get("volume_or_accounts", 0))
        _applications[next_id] = row
        _persist_applications()
        return row


def update_application(app_id: str, updates: dict):
    with _lock:
        app = _applications.get(app_id)
        if not app:
            return None
        app.update(updates)
        _persist_applications()
        return app


def _persist_applications():
    with open(config.APPLICATIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=APPLICATION_FIELDS)
        writer.writeheader()
        for app in _applications.values():
            row = dict(app)
            for field in BOOL_FIELDS:
                row[field] = str(row.get(field, False))
            writer.writerow(row)


load_all()
