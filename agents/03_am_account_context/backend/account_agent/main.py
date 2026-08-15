import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent_logic as am_logic
from . import data_store as am_store
from . import writer as am_writer
from .domo_client import DomoClient, NoDomoKeyConfigured, NoGroqKeysConfigured, AllGroqKeysExhausted

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("account_agent")

app = FastAPI(title="AM Account Context Assembly & Post-Call Action Agent")

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


@app.get("/api/meetings/upcoming")
def upcoming_meetings(am_rep: str | None = None):
    """List of upcoming AM calls, each tagged with account + schedule -
    the customer-selection list for Screen 1."""
    return am_store.get_upcoming_meetings(am_rep=am_rep)


@app.get("/api/accounts/{account_id}/briefing")
def get_briefing(account_id: str):
    try:
        am_store.get_account_context(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {account_id}")

    try:
        client = get_domo_client()
    except NoDomoKeyConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        return am_logic.build_briefing(account_id, client)
    except Exception as e:
        logger.exception("Briefing generation failed for %s", account_id)
        raise HTTPException(status_code=502, detail=f"Briefing generation failed: {e}")


@app.post("/api/accounts/{account_id}/transcribe")
async def transcribe_audio(account_id: str, audio: UploadFile = File(...)):
    """Voice-to-text only - does NOT log notes or extract actions. Uses
    Groq Whisper under the hood (Domo has no speech-to-text equivalent in
    this project); the frontend should drop the returned text into the
    notes textarea, let the rep review/edit it, then call POST /notes."""
    try:
        client = get_domo_client()
    except NoDomoKeyConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    audio_bytes = await audio.read()
    try:
        text = client.transcribe(audio_bytes, filename=audio.filename or "call.wav")
    except (NoGroqKeysConfigured, AllGroqKeysExhausted) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Transcription failed for %s", account_id)
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    return {"account_id": account_id, "transcribed_text": text}


@app.post("/api/accounts/{account_id}/notes")
def submit_notes(
    account_id: str,
    meeting_id: str = Form(...),
    am_rep: str = Form(...),
    notes_text: str = Form(...),
):
    """Logs the (typed or transcribed) call notes, then runs extraction
    and returns suggested actions for Screen 3 approval. Nothing is
    written to crm_tasks_log.csv yet - that only happens after approval."""
    try:
        am_store.get_account_context(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {account_id}")

    log_id = am_writer.log_call_notes(account_id, meeting_id, am_rep, notes_text)

    try:
        client = get_domo_client()
        extracted = am_logic.extract_actions(account_id, notes_text, client)
    except NoDomoKeyConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Extraction failed for %s", account_id)
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}")

    return {
        "call_notes_log_id": log_id,
        "account_id": account_id,
        "notes_text": notes_text,
        "extracted_actions": extracted,
    }


class ExtractedAction(BaseModel):
    type: str
    description: str
    linked_ticket_id: str | None = None
    linked_product: str | None = None


class ApproveActionsRequest(BaseModel):
    call_notes_log_id: str
    am_rep: str
    actions: list[ExtractedAction]


@app.post("/api/accounts/{account_id}/approve-actions")
def approve_actions(account_id: str, body: ApproveActionsRequest):
    """Writes only the rep-approved (and possibly rep-edited) actions to
    crm_tasks_log.csv - the CSV stand-in for "write to CRM via API."."""
    try:
        am_store.get_account_context(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown account_id: {account_id}")

    if not body.actions:
        raise HTTPException(status_code=400, detail="No actions submitted for approval.")

    written = am_writer.write_approved_tasks(
        account_id,
        [a.model_dump() for a in body.actions],
        approved_by=body.am_rep,
    )
    return {"account_id": account_id, "written_tasks": written}
