from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import data_store, agent_logic

app = FastAPI(title="Sales Rep Performance & Coaching Trigger Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Screen 1: Rep Performance Dashboard ----

@app.get("/api/dashboard")
def dashboard():
    rows = agent_logic.dashboard_rows()
    return {"rows": rows, "metrics": agent_logic.dashboard_metrics(rows)}


@app.get("/api/reps")
def list_reps():
    return data_store.list_reps()


# ---- Screen 2: Rep Detail pop-up ----

@app.get("/api/reps/{rep_id}/detail")
def rep_detail(rep_id: str):
    review = agent_logic.review_rep(rep_id)
    if not review:
        raise HTTPException(404, "Rep not found")
    return review


# ---- Screen 3: Coaching/Recognition Approval card ----

class CoachingRequest(BaseModel):
    note: str = ""


@app.post("/api/reps/{rep_id}/coaching-task")
def create_coaching_task(rep_id: str, req: CoachingRequest):
    task = agent_logic.create_coaching_task(rep_id, req.note)
    if not task:
        raise HTTPException(404, "Rep not found")
    return task


class RecognitionRequest(BaseModel):
    note: str = ""


@app.post("/api/reps/{rep_id}/recognition-nomination")
def create_recognition_nomination(rep_id: str, req: RecognitionRequest):
    nomination = agent_logic.nominate_recognition(rep_id, req.note)
    if not nomination:
        raise HTTPException(404, "Rep not found")
    return nomination


@app.get("/api/coaching-tasks")
def list_coaching_tasks():
    return data_store.list_coaching_tasks()


@app.get("/api/recognition-nominations")
def list_recognition_nominations():
    return data_store.list_recognition_nominations()


class DecideRecognitionRequest(BaseModel):
    approved: bool


@app.post("/api/recognition-nominations/{nomination_id}/decide")
def decide_recognition(nomination_id: str, req: DecideRecognitionRequest):
    result = agent_logic.decide_recognition(nomination_id, req.approved)
    if not result:
        raise HTTPException(404, "Nomination not found")
    return result


@app.get("/api/health")
def health():
    return {"status": "ok"}
