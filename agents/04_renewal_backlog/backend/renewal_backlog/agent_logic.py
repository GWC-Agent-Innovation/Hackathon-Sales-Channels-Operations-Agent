"""
Agent 4 — Renewal Opportunity Auto-Creation & Backlog Agent.

Per Shashank: auto-creating the renewal opportunity at deal-close time is
already automation (data/build_renewal_backlog.py does that once, from
Agent 3's real contracts.csv). The actual agent work is what happens
after that - noticing when a renewal is expiring soon with no AM activity
on it, and escalating through AM -> manager -> executive.

Same two-tier split as Agent 1:
  1. `compute_escalation` - deterministic, no LLM. Runs on the whole
     backlog for the kanban view (Screen 1).
  2. `build_renewal_detail` - Groq call, one renewal at a time (Screen 3):
     turns the escalation state into a risk summary plus concrete,
     account-specific proactive suggestions - Shashank's open-ended
     "what else could the agent do" ask.
"""
import json
from datetime import datetime

from .domo_client import DomoClient, parse_json_response

from . import data_store

# Thresholds are our own config (not sourced) - same spirit as Agent 1's
# capability rules: how "expiring soon" and "not being worked" are defined.
AM_NOTIFY_WINDOW_DAYS = 60      # start flagging once inside this many days of renewal
MANAGER_ESCALATE_WINDOW_DAYS = 30
EXECUTIVE_ESCALATE_WINDOW_DAYS = 14
STALE_ACTIVITY_DAYS = 14        # no activity in this many days = "not being worked"


def _today() -> datetime:
    return datetime.now()


def _days_between(later: datetime, earlier: datetime) -> int:
    return (later - earlier).days


def compute_escalation(renewal: dict, last_activity_date: datetime | None) -> dict:
    """
    Deterministic. Returns {stage, escalation_level, days_to_renewal, days_since_activity}
    stage: "on_track" | "am_notified" | "manager_escalated" | "executive_escalated" | "expired"
    """
    today = _today()
    renewal_date = datetime.strptime(renewal["renewal_date"], "%Y-%m-%d")
    days_to_renewal = _days_between(renewal_date, today)
    days_since_activity = _days_between(today, last_activity_date) if last_activity_date else None

    is_stale = days_since_activity is None or days_since_activity > STALE_ACTIVITY_DAYS

    if days_to_renewal < 0:
        stage = "expired"
    elif not is_stale:
        stage = "on_track"
    elif days_to_renewal <= EXECUTIVE_ESCALATE_WINDOW_DAYS:
        stage = "executive_escalated"
    elif days_to_renewal <= MANAGER_ESCALATE_WINDOW_DAYS:
        stage = "manager_escalated"
    elif days_to_renewal <= AM_NOTIFY_WINDOW_DAYS:
        stage = "am_notified"
    else:
        stage = "on_track"

    return {
        "stage": stage,
        "days_to_renewal": days_to_renewal,
        "days_since_activity": days_since_activity,
    }


def get_last_activity(renewal_id: str) -> tuple[datetime | None, dict | None]:
    activities = data_store.get_renewal_activities(renewal_id)
    if not activities:
        return None, None
    latest = max(activities, key=lambda a: a["activity_date"])
    return datetime.strptime(latest["activity_date"], "%Y-%m-%d"), latest


def due_window(days_to_renewal: int) -> str:
    """Bucket label matching the reference UI's 30/60/90-day command center
    columns, computed server-side so every consumer groups identically."""
    if days_to_renewal < 0:
        return "expired"
    if days_to_renewal <= 30:
        return "30-day window"
    if days_to_renewal <= 60:
        return "60-day window"
    if days_to_renewal <= 90:
        return "90-day window"
    return "beyond 90 days"


def compute_risk_score(renewal: dict, days_since_activity: int | None) -> dict:
    """
    Deterministic 0-100 risk score, genuinely cross-referencing Agent 3's
    real account data (open tickets, usage direction, invoice status) -
    not just the renewal's own dormancy clock. Same spirit as Agent 1's
    rules engine: a numeric score plus the specific factors that drove it,
    so "why this score" is always explainable, never an LLM guess.
    """
    score = 0
    factors = []

    if days_since_activity is None:
        score += 30
        factors.append("No renewal activity recorded")
    elif days_since_activity > 60:
        score += 25
        factors.append(f"No customer meeting in {days_since_activity} days")
    elif days_since_activity > 30:
        score += 15
        factors.append(f"No customer meeting in {days_since_activity} days")
    elif days_since_activity > 14:
        score += 8
        factors.append(f"No customer meeting in {days_since_activity} days")

    try:
        account_context = data_store.get_account_context(renewal["account_id"])
    except KeyError:
        account_context = None

    if account_context:
        ticket_count = account_context["tickets"]["open_count"]
        if ticket_count > 0:
            score += min(20, ticket_count * 10)
            factors.append(f"{ticket_count} unresolved support ticket(s)")

        if account_context["usage"]["direction"] == "down":
            score += 15
            factors.append("Product usage trending down")
        elif account_context["usage"]["direction"] == "flat":
            score += 5
            factors.append("Low/flat product utilization")

        if account_context["invoices"]["overdue_count"] > 0:
            score += 20
            factors.append(f"Payment overdue ({account_context['invoices']['overdue_summary']})")

    if not factors:
        factors.append("No risk signals detected — account is healthy")

    return {"risk_score": min(100, score), "risk_factors": factors}


SYSTEM_PROMPT = """You are a renewals operations assistant. You are given one \
renewal opportunity (account, ARR, tier, term, renewal date), the deterministic \
escalation state and 0-100 risk score a rules engine already computed (days to \
renewal, days since the last AM activity, which escalation stage that puts it in, \
a risk_score, and the specific risk_factors that produced it - cross-referencing \
this account's real open tickets, usage trend, and invoice status), and optionally \
the most recent AM activity note. Do NOT recompute or contradict the risk_score or \
risk_factors - they are ground truth from the rules engine; your job is to narrate \
and recommend, not re-score.

Your job:
1. Write a "risk_summary": 1-2 sentences on why this renewal needs attention right \
now (or why it doesn't, if stage is "on_track") - grounded in the risk_factors \
given, no invented customer details.
2. Write 2-4 "proactive_suggestions": concrete, specific next actions to prevent \
this renewal from reaching expired/dormant - not generic advice like "reach out to \
the customer." Ground each in the account's actual ARR/tier/term/timeline. Think \
beyond notifications: e.g. auto-drafting a specific outreach email, proposing a \
multi-year lock-in incentive given how close the deadline is, suggesting an exec \
sponsor call for high-ARR accounts, recommending a calendar hold be auto-created, \
or flagging that this account's usage/upsell context (if relevant) should be woven \
into the renewal conversation instead of treated as a separate outreach.
3. Set "urgency_label" - a short (2-4 word) human label for the stage, e.g. \
"On track", "AM follow-up needed", "Manager attention needed", "Executive escalation", \
"Expired - needs recovery plan".

Respond with ONLY a JSON object of this exact shape:
{
  "risk_summary": string,
  "proactive_suggestions": [string, ...],
  "urgency_label": string
}
"""


def build_renewal_detail(renewal_id: str, client: DomoClient) -> dict:
    renewal = data_store.get_renewal_row(renewal_id)
    if renewal is None:
        raise KeyError(f"Unknown renewal_id: {renewal_id}")

    last_activity_date, last_activity = get_last_activity(renewal_id)
    escalation = compute_escalation(renewal, last_activity_date)
    risk = compute_risk_score(renewal, escalation["days_since_activity"])
    hierarchy = data_store.get_rep_hierarchy(renewal["am_owner"])

    llm_input = {
        "account_name": renewal["account_name"],
        "tier": renewal["tier"],
        "am_owner": renewal["am_owner"],
        "product_bundle": renewal["product_bundle"],
        "term_months": renewal["term_months"],
        "expected_value": renewal["expected_value"],
        "renewal_date": renewal["renewal_date"],
        "escalation_stage": escalation["stage"],
        "days_to_renewal": escalation["days_to_renewal"],
        "days_since_last_activity": escalation["days_since_activity"],
        "last_activity_note": last_activity["note"] if last_activity else None,
        "risk_score": risk["risk_score"],
        "risk_factors": risk["risk_factors"],
    }

    raw = client.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(llm_input)},
        ],
        json_mode=True,
        temperature=0.3,
    )
    synthesis = parse_json_response(raw)

    return {
        "renewal_id": renewal_id,
        "account_id": renewal["account_id"],
        "account_name": renewal["account_name"],
        "tier": renewal["tier"],
        "am_owner": renewal["am_owner"],
        "manager": hierarchy["manager"] if hierarchy else None,
        "executive": hierarchy["executive"] if hierarchy else None,
        "product_bundle": renewal["product_bundle"],
        "term_months": renewal["term_months"],
        "expected_value": renewal["expected_value"],
        "renewal_date": renewal["renewal_date"],
        "target_close_date": renewal["target_close_date"],
        "trigger_timestamp": renewal["trigger_timestamp"],
        "created_timestamp": renewal["created_timestamp"],
        "escalation_stage": escalation["stage"],
        "days_to_renewal": escalation["days_to_renewal"],
        "due_window": due_window(escalation["days_to_renewal"]),
        "days_since_last_activity": escalation["days_since_activity"],
        "last_activity_note": last_activity["note"] if last_activity else None,
        "risk_score": risk["risk_score"],
        "risk_factors": risk["risk_factors"],
        "risk_summary": synthesis.get("risk_summary"),
        "proactive_suggestions": synthesis.get("proactive_suggestions", []),
        "urgency_label": synthesis.get("urgency_label"),
    }
