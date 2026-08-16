import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent_logic as dg_logic
from . import data_store as dg_store
from . import emailer
from . import writer as dg_writer
from .emailer import GmailNotConfigured
from .domo_client import DomoClient, NoDomoKeyConfigured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deal_guardrail")

app = FastAPI(title="Sales Deal Guardrail & Order Validation Agent")

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


@app.get("/api/deals/queue")
def deal_queue(rep: str | None = None):
    pending = dg_store.get_pending_deals()
    items = []
    for deal in pending:
        if rep and deal["rep"] != rep:
            continue
        address = dg_store.get_shipping_address(deal["account_id"])
        rules_result = dg_logic.run_rules_engine(deal, address)
        items.append({
            "deal_id": deal["deal_id"],
            "account_id": deal["account_id"],
            "account_name": deal["account_name"],
            "rep": deal["rep"],
            "rep_role": deal["rep_role"],
            "config_summary": dg_logic.config_summary(deal),
            "fit_status": rules_result["fit_status"],
            "is_existing_customer_change": bool(deal.get("is_existing_customer_change")),
            "quantity_change_type": rules_result["change_type"],
            "submitted_age": str(deal["submitted_age"]),
        })

    return {
        "deals": items,
        "total_pending": len(items),
        "exception_count": sum(1 for i in items if i["fit_status"] == "exception"),
        "escalated_count": sum(1 for i in items if i["fit_status"] == "escalated"),
        "upsell_count": sum(1 for i in items if i["quantity_change_type"] == "increase"),
        "downsell_count": sum(1 for i in items if i["quantity_change_type"] == "decrease"),
    }


AUTO_APPROVE_CONFIDENCE_THRESHOLD = 90


@app.get("/api/deals/{deal_id}/detail")
def deal_detail(deal_id: str):
    if dg_store.get_deal_row(deal_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown deal_id: {deal_id}")

    existing = dg_store.get_deal_decision(deal_id)
    if existing:
        return {
            **dg_logic.build_detail_from_rules_only(deal_id),
            "already_decided": True,
            "auto_executed": existing["reviewer"] == "Deal Guardrail Agent",
            "final_decision": existing["decision"],
            "rationale_trace": [f"Already {existing['decision']} by {existing['reviewer']} on {existing['decided_at']}."],
            "gap_summary": existing["comment"] or None,
            "confidence_score": None,
            "recommended_action": None,
        }

    try:
        client = get_domo_client()
    except NoDomoKeyConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        detail = dg_logic.build_deal_detail(deal_id, client)
    except Exception as e:
        logger.exception("Deal detail generation failed for %s", deal_id)
        raise HTTPException(status_code=502, detail=f"Deal review failed: {e}")

    # Server-side backstop: never auto-execute if a hard rule violation is
    # present, regardless of what confidence score the LLM reported.
    has_hard_violation = any(v["severity"] == "hard" for v in detail["violations"])
    auto_executed = (
        detail["fit_status"] == "auto-cleared"
        and not has_hard_violation
        and detail["confidence_score"] is not None
        and detail["confidence_score"] >= AUTO_APPROVE_CONFIDENCE_THRESHOLD
        and detail["recommended_action"] == "auto-approve"
    )
    if auto_executed:
        dg_writer.write_deal_decision(
            deal_id, "approved", "Deal Guardrail Agent",
            f"Auto-approved — confidence {detail['confidence_score']}/100, no rule violations.",
        )

    detail["already_decided"] = auto_executed
    detail["auto_executed"] = auto_executed
    detail["final_decision"] = "approved" if auto_executed else None
    return detail


class DealDecisionRequest(BaseModel):
    decision: str
    reviewer: str
    comment: str | None = None


@app.post("/api/deals/{deal_id}/decision")
def deal_decision(deal_id: str, body: DealDecisionRequest):
    if dg_store.get_deal_row(deal_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown deal_id: {deal_id}")
    if dg_store.get_deal_decision(deal_id) is not None:
        raise HTTPException(status_code=409, detail=f"Deal {deal_id} has already been decided.")

    return dg_writer.write_deal_decision(deal_id, body.decision, body.reviewer, body.comment)


def _build_escalation_email(deal_id: str, deal: dict, reviewer: str, comment: str | None) -> tuple[str, str]:
    address = dg_store.get_shipping_address(deal["account_id"])
    rules_result = dg_logic.run_rules_engine(deal, address)
    violation_lines = "\n".join(f"  - [{v['category']}] {v['message']}" for v in rules_result["violations"]) \
        or "  - (none flagged by the rules engine - escalated manually by reviewer)"

    subject = f"[Deal Guardrail] Escalation needed — {deal_id} ({deal['account_name']})"
    body = f"""A deal has been escalated by Sales Ops and needs your input.

Deal: {deal_id}
Account: {deal['account_name']}
Rep: {deal['rep']} ({deal['rep_role']})
Product bundle: {deal['product_bundle']}
Quantity: {deal['quantity']}
Discount: {deal['discount_pct']}% (max allowed: {deal['max_discount_pct']}%)
Billing model: {deal['billing_model']}
Term: {deal['term_months']} months
ARR: ${deal['arr']:,}

Rule engine findings:
{violation_lines}

Escalated by: {reviewer}
Reviewer comment: {comment or '(none)'}

— Sent automatically by the Sales Deal Guardrail Agent
"""
    return subject, body


class DealEscalateEmailPreviewRequest(BaseModel):
    reviewer: str
    comment: str | None = None


@app.post("/api/deals/{deal_id}/escalate-email/preview")
def preview_escalation_email(deal_id: str, body: DealEscalateEmailPreviewRequest):
    """
    Builds the exact subject/body that /escalate-email would send, without
    sending it and without touching the recipient address - lets the
    frontend show the reviewer a preview before they type an address and
    confirm the send.
    """
    deal = dg_store.get_deal_row(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail=f"Unknown deal_id: {deal_id}")
    if dg_store.get_deal_decision(deal_id) is not None:
        raise HTTPException(status_code=409, detail=f"Deal {deal_id} has already been decided.")

    subject, email_body = _build_escalation_email(deal_id, deal, body.reviewer, body.comment)
    return {"subject": subject, "body": email_body}


class DealEscalateEmailRequest(BaseModel):
    to_email: str
    reviewer: str
    comment: str | None = None
    # Reviewer may edit the previewed body before sending — fall back to the
    # auto-generated one when omitted so older callers keep working.
    subject: str | None = None
    body: str | None = None


@app.post("/api/deals/{deal_id}/escalate-email")
def escalate_deal_via_email(deal_id: str, req: DealEscalateEmailRequest):
    deal = dg_store.get_deal_row(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail=f"Unknown deal_id: {deal_id}")
    if dg_store.get_deal_decision(deal_id) is not None:
        raise HTTPException(status_code=409, detail=f"Deal {deal_id} has already been decided.")

    default_subject, default_body = _build_escalation_email(deal_id, deal, req.reviewer, req.comment)
    subject = req.subject or default_subject
    email_body = req.body or default_body

    try:
        emailer.send_email(req.to_email, subject, email_body)
    except GmailNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Escalation email failed for %s", deal_id)
        raise HTTPException(status_code=502, detail=f"Email send failed: {e}")

    decision_row = dg_writer.write_deal_decision(deal_id, "escalated", req.reviewer, req.comment)
    return {**decision_row, "emailed_to": req.to_email, "email_subject": subject}


@app.get("/api/deals/audit-log")
def deal_audit_log():
    return dg_store.get_deal_decisions()
