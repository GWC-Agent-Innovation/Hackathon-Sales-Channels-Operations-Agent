import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent_logic as ren_logic
from . import data_store as ren_store
from . import writer as ren_writer
from .domo_client import DomoClient, NoDomoKeyConfigured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("renewal_backlog")

app = FastAPI(title="Renewal Opportunity Auto-Creation & Backlog Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_domo_client: DomoClient | None = None


def get_domo_client() -> DomoClient:
    global _domo_client
    if _domo_client is None:
        _domo_client = DomoClient()
    return _domo_client


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _quarter_label(date_str: str) -> str:
    """e.g. '2026-09-01' -> 'Q3 2026' - computed server-side so every
    consumer groups the kanban identically."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


@app.get("/api/renewals/queue")
def renewal_queue(am_owner: str | None = None):
    renewals = ren_store.get_all_renewals()
    items = []
    for r in renewals:
        if am_owner and r["am_owner"] != am_owner:
            continue
        last_activity_date, _ = ren_logic.get_last_activity(r["renewal_id"])
        escalation = ren_logic.compute_escalation(r, last_activity_date)
        risk = ren_logic.compute_risk_score(r, escalation["days_since_activity"])
        items.append({
            "renewal_id": r["renewal_id"],
            "account_id": r["account_id"],
            "account_name": r["account_name"],
            "am_owner": r["am_owner"],
            "tier": r["tier"],
            "expected_value": r["expected_value"],
            "term_months": r["term_months"],
            "renewal_date": r["renewal_date"],
            "target_close_date": r["target_close_date"],
            "quarter": _quarter_label(r["renewal_date"]),
            "due_window": ren_logic.due_window(escalation["days_to_renewal"]),
            "escalation_stage": escalation["stage"],
            "days_to_renewal": escalation["days_to_renewal"],
            "days_since_last_activity": escalation["days_since_activity"],
            "risk_score": risk["risk_score"],
        })

    at_risk = [i for i in items if i["escalation_stage"] in
               ("am_notified", "manager_escalated", "executive_escalated")]
    expired = [i for i in items if i["escalation_stage"] == "expired"]
    healthy = len(items) - len(at_risk) - len(expired)

    return {
        "renewals": items,
        "total_backlog_value": sum(i["expected_value"] for i in items),
        "backlog_completeness_pct": round(100 * healthy / len(items), 1) if items else 100.0,
        "at_risk_count": len(at_risk),
        "expired_count": len(expired),
        "due_within_30_count": sum(1 for i in items if i["due_window"] == "30-day window"),
        "due_31_to_60_count": sum(1 for i in items if i["due_window"] == "60-day window"),
        "due_61_to_90_count": sum(1 for i in items if i["due_window"] == "90-day window"),
        "due_beyond_90_count": sum(1 for i in items if i["due_window"] == "beyond 90 days"),
    }


@app.get("/api/renewals/trigger-log")
def renewal_trigger_log():
    renewals = sorted(ren_store.get_all_renewals(), key=lambda r: r["trigger_timestamp"], reverse=True)
    return renewals


@app.get("/api/renewals/{renewal_id}/detail")
def renewal_detail(renewal_id: str):
    if ren_store.get_renewal_row(renewal_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown renewal_id: {renewal_id}")

    try:
        client = get_domo_client()
    except NoDomoKeyConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        return ren_logic.build_renewal_detail(renewal_id, client)
    except Exception as e:
        logger.exception("Renewal detail generation failed for %s", renewal_id)
        raise HTTPException(status_code=502, detail=f"Renewal review failed: {e}")


class LogActivityRequest(BaseModel):
    actor: str
    note: str


@app.post("/api/renewals/{renewal_id}/activity")
def log_renewal_activity(renewal_id: str, body: LogActivityRequest):
    if ren_store.get_renewal_row(renewal_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown renewal_id: {renewal_id}")
    return ren_writer.log_renewal_activity(renewal_id, body.actor, body.note)


class AdjustRenewalRequest(BaseModel):
    field: str
    new_value: str
    adjusted_by: str


@app.post("/api/renewals/{renewal_id}/adjust")
def adjust_renewal(renewal_id: str, body: AdjustRenewalRequest):
    if ren_store.get_renewal_row(renewal_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown renewal_id: {renewal_id}")
    return ren_writer.adjust_renewal_field(renewal_id, body.field, body.new_value, body.adjusted_by)


class NotifyRequest(BaseModel):
    triggered_by: str
    action: str | None = None


@app.post("/api/renewals/{renewal_id}/notify")
def notify_renewal(renewal_id: str, body: NotifyRequest):
    renewal = ren_store.get_renewal_row(renewal_id)
    if renewal is None:
        raise HTTPException(status_code=404, detail=f"Unknown renewal_id: {renewal_id}")

    hierarchy = ren_store.get_rep_hierarchy(renewal["am_owner"])
    manager = hierarchy["manager"] if hierarchy else "manager"
    executive = hierarchy["executive"] if hierarchy else "executive"

    if body.action == "resolve":
        ren_writer.log_renewal_activity(renewal_id, body.triggered_by,
                                         "Marked resolved — notified AM and created a follow-up task.")
        level, notified, action = "resolved", renewal["am_owner"], "resolve"
    elif body.action == "recommend_meeting":
        ren_writer.log_renewal_activity(renewal_id, body.triggered_by,
                                         "Recommended a customer meeting be scheduled to save this renewal.")
        level, notified, action = "am_notified", renewal["am_owner"], "recommend_meeting"
    elif body.action == "escalate_am":
        level, notified, action = "am_notified", renewal["am_owner"], "escalate_am"
    elif body.action == "escalate_manager":
        level, notified, action = "manager_escalated", manager, "escalate_manager"
    elif body.action == "escalate_executive":
        level, notified, action = "executive_escalated", executive, "escalate_executive"
    else:
        last_activity_date, _ = ren_logic.get_last_activity(renewal_id)
        escalation = ren_logic.compute_escalation(renewal, last_activity_date)
        notified_map = {
            "on_track": renewal["am_owner"], "am_notified": renewal["am_owner"],
            "manager_escalated": manager, "executive_escalated": executive, "expired": executive,
        }
        level, notified, action = escalation["stage"], notified_map[escalation["stage"]], "auto"

    return ren_writer.log_renewal_escalation(renewal_id, level, notified, action)
