from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import data_store, agent_logic

app = FastAPI(title="Distributor & Reseller (MSP) Partner Onboarding Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Screen 1: Partner Application Form ----

class SubmitApplicationRequest(BaseModel):
    company_name: str
    contact_name: str
    contact_email: str
    requested_track: str
    geography: str
    is_wholesale_only: bool = False
    sells_direct: bool = False
    has_managed_services: bool = False
    volume_or_accounts: int = 0
    notes: str = ""


@app.post("/api/applications")
def submit_application(req: SubmitApplicationRequest):
    return agent_logic.submit_application(**req.model_dump())


# ---- Screen 2: Applications Queue ----

@app.get("/api/applications")
def list_applications():
    return data_store.list_applications()


@app.get("/api/applications-queue")
def applications_queue():
    return agent_logic.list_queue()


@app.get("/api/applications/{app_id}")
def get_application(app_id: str):
    app_ = data_store.get_application(app_id)
    if not app_:
        raise HTTPException(404, "Application not found")
    return app_


# ---- Screen 3: Approval card ----

@app.get("/api/applications/{app_id}/review")
def review_application(app_id: str):
    review = agent_logic.review_application(app_id)
    if not review:
        raise HTTPException(404, "Application not found")
    return review


class ApproveRequest(BaseModel):
    track: str
    tier: str
    note: str = ""


@app.post("/api/applications/{app_id}/approve")
def approve_application(app_id: str, req: ApproveRequest):
    result = agent_logic.approve_application(app_id, req.track, req.tier, req.note)
    if not result:
        raise HTTPException(404, "Application not found")
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


class RejectRequest(BaseModel):
    reason: str


@app.post("/api/applications/{app_id}/reject")
def reject_application(app_id: str, req: RejectRequest):
    app_ = agent_logic.reject_application(app_id, req.reason)
    if not app_:
        raise HTTPException(404, "Application not found")
    return app_


class MoreInfoRequest(BaseModel):
    requested_info: str


@app.post("/api/applications/{app_id}/request-info")
def request_more_info(app_id: str, req: MoreInfoRequest):
    app_ = agent_logic.request_more_info(app_id, req.requested_info)
    if not app_:
        raise HTTPException(404, "Application not found")
    return app_


@app.get("/api/program-criteria")
def program_criteria():
    return {
        "Distributor": data_store.criteria_for_track("Distributor"),
        "Reseller/MSP": data_store.criteria_for_track("Reseller/MSP"),
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
