"""Agent 1 — Sales Deal Guardrail & Order Validation Agent — request/response schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class RuleViolation(BaseModel):
    severity: Literal["hard", "soft"]
    category: Literal["exception", "escalated"]
    message: str


class DealQueueItem(BaseModel):
    deal_id: str
    account_id: str
    account_name: str
    rep: str
    rep_role: str
    config_summary: str
    fit_status: Literal["auto-cleared", "exception", "escalated"]
    is_existing_customer_change: bool
    quantity_change_type: Literal["increase", "decrease", "no_change"] | None = None
    submitted_age: str


class DealQueueResponse(BaseModel):
    deals: list[DealQueueItem]
    total_pending: int
    exception_count: int
    escalated_count: int
    upsell_count: int
    downsell_count: int


class DealDetailResponse(BaseModel):
    deal_id: str
    account_id: str
    account_name: str
    rep: str
    rep_role: str
    product_bundle: str
    quantity: int
    discount_pct: float
    max_discount_pct: float
    billing_model: str
    term_months: int
    arr: int
    requires_hardware_shipment: bool
    shipping_address: dict | None
    fit_status: Literal["auto-cleared", "exception", "escalated"]
    violations: list[RuleViolation]
    is_existing_customer_change: bool
    quantity_change_type: Literal["increase", "decrease", "no_change"] | None = None
    previous_quantity: int | None = None
    change_reason: str | None = None
    rationale_trace: list[str]
    gap_summary: str | None
    reason_sentiment: Literal["positive", "negative", "neutral"] | None = None
    signal_interpretation: str | None = None
    confidence_score: int | None = Field(None, ge=0, le=100)
    recommended_action: Literal["auto-approve", "return-to-rep", "escalate-to-erp-integration"] | None = None
    already_decided: bool = False
    auto_executed: bool = False
    final_decision: str | None = None


class DealAuditLogEntry(BaseModel):
    review_id: str
    deal_id: str
    decision: str
    reviewer: str
    comment: str
    decided_at: str


class DealDecisionRequest(BaseModel):
    decision: Literal["approved", "returned", "escalated"]
    reviewer: str
    comment: str | None = None


class DealDecisionResponse(BaseModel):
    review_id: str
    deal_id: str
    decision: str
    reviewer: str
    comment: str
    decided_at: str


class DealEscalateEmailRequest(BaseModel):
    to_email: str
    reviewer: str
    comment: str | None = None


class DealEscalateEmailResponse(BaseModel):
    review_id: str
    deal_id: str
    decision: str
    reviewer: str
    comment: str
    decided_at: str
    emailed_to: str
    email_subject: str
