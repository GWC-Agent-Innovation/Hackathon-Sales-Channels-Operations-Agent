"""Agent 4 — Renewal Opportunity Auto-Creation & Backlog Agent — request/response schemas."""
from typing import Literal

from pydantic import BaseModel, Field

EscalationStage = Literal["on_track", "am_notified", "manager_escalated", "executive_escalated", "expired"]


class RenewalQueueItem(BaseModel):
    renewal_id: str
    account_id: str
    account_name: str
    am_owner: str
    tier: str
    expected_value: float
    term_months: int
    renewal_date: str
    target_close_date: str
    quarter: str
    due_window: str
    escalation_stage: EscalationStage
    days_to_renewal: int
    days_since_last_activity: int | None = None
    risk_score: int = Field(..., ge=0, le=100)


class RenewalQueueResponse(BaseModel):
    renewals: list[RenewalQueueItem]
    total_backlog_value: float
    backlog_completeness_pct: float
    at_risk_count: int
    expired_count: int
    due_within_30_count: int
    due_31_to_60_count: int
    due_61_to_90_count: int
    due_beyond_90_count: int


class TriggerLogEntry(BaseModel):
    renewal_id: str
    account_name: str
    am_owner: str
    trigger_event: str
    trigger_timestamp: str
    created_timestamp: str
    target_close_date: str


class RenewalDetailResponse(BaseModel):
    renewal_id: str
    account_id: str
    account_name: str
    tier: str
    am_owner: str
    manager: str | None
    executive: str | None
    product_bundle: str
    term_months: int
    expected_value: float
    renewal_date: str
    target_close_date: str
    trigger_timestamp: str
    created_timestamp: str
    escalation_stage: EscalationStage
    days_to_renewal: int
    due_window: str
    days_since_last_activity: int | None
    last_activity_note: str | None
    risk_score: int = Field(..., ge=0, le=100)
    risk_factors: list[str]
    risk_summary: str | None
    proactive_suggestions: list[str]
    urgency_label: str | None


class LogActivityRequest(BaseModel):
    actor: str
    note: str


class AdjustRenewalRequest(BaseModel):
    field: Literal["am_owner", "target_close_date", "expected_value"]
    new_value: str
    adjusted_by: str


class NotifyRequest(BaseModel):
    triggered_by: str
    action: Literal["resolve", "recommend_meeting", "escalate_am", "escalate_manager", "escalate_executive"] | None = None


class NotifyResponse(BaseModel):
    escalation_id: str
    renewal_id: str
    level: str
    notified: str
    triggered_at: str
    action: str
