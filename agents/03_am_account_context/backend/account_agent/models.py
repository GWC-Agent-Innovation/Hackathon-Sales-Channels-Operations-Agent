"""Agent 3 — AM Account Context Assembly & Post-Call Action Agent — request/response schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class UpcomingMeeting(BaseModel):
    account_id: str
    account_name: str
    tier: str
    meeting_id: str
    am_rep: str
    scheduled_datetime: str
    meeting_type: str


class TalkingPoint(BaseModel):
    point: str
    urgency: Literal["high", "medium", "low"]


class UpsellCandidate(BaseModel):
    recommended_product: str | None = None
    reasoning: str | None = None
    fit_score: int | None = Field(None, ge=0, le=100)


class LastInteraction(BaseModel):
    type: str
    date: str | None = None
    days_ago: int | None = None


class BriefingResponse(BaseModel):
    account_id: str
    account_name: str
    trace: list[str]
    invoice_status: str
    dso_days: int | None
    usage_trend: list[int]
    usage_direction: str
    open_tickets: list[dict]
    contract: dict | None
    owned_products: list[str]
    last_interaction: LastInteraction | None = None
    recent_signal: str | None = None
    upsell_candidate: UpsellCandidate
    customer_sentiment: Literal["positive", "cautiously_positive", "neutral", "at_risk", "negative"] | None = None
    sentiment_label: str | None = None
    sentiment_reason: str | None = None
    talking_points: list[TalkingPoint]
    pitch_strategy: str | None = None
    opening_line: str | None = None


class NotesTextRequest(BaseModel):
    meeting_id: str
    am_rep: str
    notes_text: str


class ExtractedAction(BaseModel):
    type: Literal["task", "opportunity"]
    description: str
    linked_ticket_id: str | None = None
    linked_product: str | None = None


class NotesResponse(BaseModel):
    call_notes_log_id: str
    account_id: str
    notes_text: str
    extracted_actions: list[ExtractedAction]


class ApproveActionsRequest(BaseModel):
    call_notes_log_id: str
    am_rep: str
    actions: list[ExtractedAction]  # only the ones the rep approved/edited


class ApprovedTask(BaseModel):
    task_id: str
    account_id: str
    type: str
    description: str
    status: str
    created_at: str
    approved_by: str


class ApproveActionsResponse(BaseModel):
    account_id: str
    written_tasks: list[ApprovedTask]
