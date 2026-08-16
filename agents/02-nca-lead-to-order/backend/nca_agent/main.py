from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import data_store, agent_logic

app = FastAPI(title="NCA Lead-to-Order Conversion Assistant Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/opportunities")
def list_opportunities():
    return data_store.list_opportunities()


@app.get("/api/opportunities/{opp_id}")
def get_opportunity(opp_id: str):
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return {"opportunity": opp, "activities": data_store.get_activities(opp_id)}


@app.get("/api/opportunities/{opp_id}/timeline")
def get_timeline(opp_id: str):
    timeline = agent_logic.get_timeline(opp_id)
    if not timeline:
        raise HTTPException(404, "Opportunity not found")
    return timeline


@app.post("/api/opportunities/{opp_id}/suggest")
def suggest(opp_id: str):
    suggestion = agent_logic.get_suggestion(opp_id)
    if not suggestion:
        raise HTTPException(404, "Opportunity not found")
    return suggestion


@app.post("/api/opportunities/{opp_id}/fields/{field}/confirm")
def confirm_field(opp_id: str, field: str):
    result = agent_logic.confirm_field(opp_id, field)
    if not result:
        raise HTTPException(404, "Opportunity not found")
    return result


@app.post("/api/opportunities/{opp_id}/proposal/preview")
def preview_proposal(opp_id: str):
    document = agent_logic.generate_document_preview(opp_id)
    if not document:
        raise HTTPException(404, "Opportunity not found")
    return document


class DocumentEdit(BaseModel):
    document_type: str
    account_name: str
    contact_name: str
    product_line: str
    deal_value: float
    billing_model: str
    body: str


@app.post("/api/opportunities/{opp_id}/proposal/send")
def send_proposal(opp_id: str, edited_document: DocumentEdit | None = None):
    result = agent_logic.confirm_proposal_sent(
        opp_id, edited_document.model_dump() if edited_document else None
    )
    if not result:
        raise HTTPException(404, "Opportunity not found")
    return result


@app.post("/api/opportunities/{opp_id}/advance")
def advance_stage(opp_id: str):
    result = agent_logic.advance_stage_if_ready(opp_id)
    if not result:
        raise HTTPException(404, "Opportunity not found")
    return result


class ClosedLostRequest(BaseModel):
    reason: str


@app.post("/api/opportunities/{opp_id}/closed-lost")
def closed_lost(opp_id: str, req: ClosedLostRequest):
    opp = agent_logic.mark_closed_lost(opp_id, req.reason)
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return opp


@app.get("/api/opportunities/{opp_id}/commitments")
def get_open_commitments(opp_id: str):
    if not data_store.get_opportunity(opp_id):
        raise HTTPException(404, "Opportunity not found")
    return agent_logic.open_commitments(opp_id)


@app.post("/api/opportunities/{opp_id}/commitments/{activity_id}/fulfill")
def fulfill_commitment(opp_id: str, activity_id: str):
    if not data_store.get_opportunity(opp_id):
        raise HTTPException(404, "Opportunity not found")
    data_store.mark_commitment_fulfilled(activity_id, opp_id)
    return {"opportunity_id": opp_id, "activity_id": activity_id, "fulfilled": True}


@app.get("/api/reps")
def list_reps():
    return data_store.list_reps()


@app.get("/api/reps/{rep_name}/daily-priorities")
def daily_priorities(rep_name: str):
    return agent_logic.get_daily_priorities(rep_name)


class MeetingNoteRequest(BaseModel):
    note_text: str


@app.post("/api/opportunities/{opp_id}/meeting-note/analyze")
def analyze_meeting_note(opp_id: str, req: MeetingNoteRequest):
    result = agent_logic.analyze_meeting_note(opp_id, req.note_text)
    if not result:
        raise HTTPException(404, "Opportunity not found")
    return result


class ApplyMeetingNoteRequest(BaseModel):
    summary: str
    confirmed_fields: list[str]
    commitment: str = ""


@app.post("/api/opportunities/{opp_id}/meeting-note/apply")
def apply_meeting_note(opp_id: str, req: ApplyMeetingNoteRequest):
    result = agent_logic.apply_meeting_note(opp_id, req.summary, req.confirmed_fields, req.commitment)
    if not result:
        raise HTTPException(404, "Opportunity not found")
    return result


@app.get("/api/health")
def health():
    return {"status": "ok"}
