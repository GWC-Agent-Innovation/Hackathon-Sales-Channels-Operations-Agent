import csv
import threading
from . import config

_lock = threading.Lock()

_opportunities: dict[str, dict] = {}
_activities: dict[str, list[dict]] = {}
_product_catalog: dict[str, dict] = {}
_historical_patterns: dict[str, str] = {}
_generated_documents: dict[str, dict] = {}

BOOL_FIELDS = ("need_confirmed", "budget_confirmed", "decision_maker_identified",
               "requirements_captured", "terms_agreed")
DATE_FIELDS = ("proposal_shared_date", "signature_received_date")

OPPORTUNITY_FIELDS = [
    "id", "rep_name", "account_name", "contact_name", "contact_email",
    "product_line", "deal_value", "stage", "created_date", "last_activity_date",
    "need_confirmed", "budget_confirmed", "decision_maker_identified",
    "requirements_captured", "proposal_shared_date", "terms_agreed",
    "signature_received_date", "closed_lost_reason", "notes",
]

ACTIVITY_FIELDS = [
    "id", "opportunity_id", "activity_date", "activity_type", "summary",
    "commitment", "commitment_fulfilled",
]


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_bool(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def load_all():
    with _lock:
        _opportunities.clear()
        for row in _read_csv(config.OPPORTUNITIES_CSV):
            row["deal_value"] = float(row["deal_value"])
            for field in BOOL_FIELDS:
                row[field] = _to_bool(row.get(field, ""))
            _opportunities[row["id"]] = row

        _activities.clear()
        for row in _read_csv(config.ACTIVITIES_CSV):
            row["commitment_fulfilled"] = (
                _to_bool(row["commitment_fulfilled"]) if row.get("commitment") else None
            )
            _activities.setdefault(row["opportunity_id"], []).append(row)
        for acts in _activities.values():
            acts.sort(key=lambda a: a["activity_date"], reverse=True)

        _product_catalog.clear()
        for row in _read_csv(config.PRODUCT_CATALOG_CSV):
            _product_catalog[row["product_line"]] = row

        _historical_patterns.clear()
        for row in _read_csv(config.HISTORICAL_PATTERNS_CSV):
            _historical_patterns[row["scope"]] = row["insight"]


def list_opportunities():
    return sorted(_opportunities.values(), key=lambda o: o["last_activity_date"], reverse=True)


def list_opportunities_for_rep(rep_name: str, open_only: bool = True):
    opps = [o for o in _opportunities.values() if o["rep_name"] == rep_name]
    if open_only:
        opps = [o for o in opps if o["stage"] not in ("Closed Won", "Closed Lost")]
    return sorted(opps, key=lambda o: o["last_activity_date"])


def list_reps():
    return sorted({o["rep_name"] for o in _opportunities.values()})


def get_opportunity(opp_id: str):
    return _opportunities.get(opp_id)


def get_activities(opp_id: str):
    return _activities.get(opp_id, [])


def get_product(product_line: str):
    return _product_catalog.get(product_line)


def get_pattern(scope: str):
    return _historical_patterns.get(scope)


def update_opportunity_fields(opp_id: str, updates: dict):
    with _lock:
        opp = _opportunities.get(opp_id)
        if not opp:
            return None
        opp.update(updates)
        _persist_opportunities()
        return opp


def update_stage(opp_id: str, new_stage: str):
    return update_opportunity_fields(opp_id, {"stage": new_stage})


def _persist_opportunities():
    with open(config.OPPORTUNITIES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OPPORTUNITY_FIELDS)
        writer.writeheader()
        for opp in _opportunities.values():
            row = dict(opp)
            for field in BOOL_FIELDS:
                row[field] = str(row.get(field, False))
            writer.writerow(row)


def add_activity(opp_id: str, activity_date: str, activity_type: str, summary: str,
                  commitment: str = "", commitment_fulfilled=None):
    with _lock:
        next_num = sum(len(v) for v in _activities.values()) + 1
        row = {
            "id": f"ACT-{next_num}",
            "opportunity_id": opp_id,
            "activity_date": activity_date,
            "activity_type": activity_type,
            "summary": summary,
            "commitment": commitment,
            "commitment_fulfilled": commitment_fulfilled if commitment else None,
        }
        _activities.setdefault(opp_id, []).insert(0, row)
        _persist_activities()
        return row


def mark_commitment_fulfilled(activity_id: str, opp_id: str):
    with _lock:
        for act in _activities.get(opp_id, []):
            if act["id"] == activity_id:
                act["commitment_fulfilled"] = True
        _persist_activities()


def _persist_activities():
    with open(config.ACTIVITIES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ACTIVITY_FIELDS)
        writer.writeheader()
        for acts in _activities.values():
            for act in acts:
                row = dict(act)
                row["commitment_fulfilled"] = (
                    "" if row["commitment_fulfilled"] is None else str(row["commitment_fulfilled"])
                )
                writer.writerow(row)


def save_document(opp_id: str, document: dict):
    _generated_documents[opp_id] = document


def get_document(opp_id: str):
    return _generated_documents.get(opp_id)


load_all()
