from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent_logic import generate_opportunity_for_account
from .domo_service import (
    get_accounts,
    get_account_by_id,
    get_signals_by_account_id,
    get_tickets,
    get_tickets_by_account_id,
    get_product_catalog,
    get_opportunities,
    get_opportunity_by_id,
    get_opportunities_by_account_id,
    replace_opportunities,
)

app = FastAPI(title="AM Cross-Sell/Upsell Opportunity Creation Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/accounts")
def accounts():
    return get_accounts()


@app.get("/api/accounts/{account_id}")
def account_by_id(account_id: str):
    return get_account_by_id(account_id)


@app.get("/api/accounts/{account_id}/signals")
def signals_by_account(account_id: str):
    return get_signals_by_account_id(account_id)


@app.get("/api/tickets")
def tickets():
    return get_tickets()


@app.get("/api/accounts/{account_id}/tickets")
def tickets_by_account(account_id: str):
    return get_tickets_by_account_id(account_id)


@app.get("/api/product-catalog")
def product_catalog():
    return get_product_catalog()


@app.get("/api/opportunities")
def opportunities():
    return get_opportunities()


@app.get("/api/opportunities/{opp_id}")
def opportunity_by_id(opp_id: str):
    return get_opportunity_by_id(opp_id)


@app.get("/api/accounts/{account_id}/opportunities")
def opportunities_by_account(account_id: str):
    return get_opportunities_by_account_id(account_id)


@app.post("/api/accounts/{account_id}/generate-opportunity")
async def generate_opportunity(account_id: str):
    result = await generate_opportunity_for_account(account_id)
    if not result:
        return {"error": "No opportunity generated"}
    return result


class OpportunityActionRequest(BaseModel):
    action: Literal["approved", "pending", "discard"]
    discard_reason: str | None = None
    outreach_subject: str | None = None
    outreach_draft: str | None = None
    to_emails: list[str] | None = None


@app.post("/api/accounts/{account_id}/actions")
async def submit_opportunity_action(account_id: str, body: OpportunityActionRequest):
    print(f"[actions] request: account_id={account_id!r} action={body.action!r} discard_reason={body.discard_reason!r}")

    rows = get_opportunities()
    print(f"[actions] fetched {len(rows) if rows else 0} rows from get_opportunities()")
    if not rows:
        print("[actions] no rows returned from Domo, aborting with 502")
        raise HTTPException(status_code=502, detail="Could not fetch opportunities from Domo.")

    print(f"[actions] available account_ids: {[row.get('account_id') for row in rows]}")

    matched = False
    for row in rows:
        if row.get("account_id") == account_id:
            print(f"[actions] match found, updating row: {row}")
            row["status"] = body.action
            if body.discard_reason is not None:
                row["discard_reason"] = body.discard_reason
            if body.outreach_subject is not None:
                row["outreach_subject"] = body.outreach_subject
            if body.outreach_draft is not None:
                row["outreach_draft"] = body.outreach_draft
            matched = True

    if not matched:
        print(f"[actions] no row matched account_id={account_id!r}, aborting with 404")
        raise HTTPException(
            status_code=404, detail=f"No opportunity found for account_id: {account_id}"
        )

    try:
        ok = await replace_opportunities(
            rows, triggered_account_id=account_id, triggered_action=body.action,
            triggered_to_emails=body.to_emails,
        )
    except ValueError as e:
        print(f"[actions] replace_opportunities raised ValueError: {e}")
        raise HTTPException(status_code=503, detail=str(e))

    print(f"[actions] replace_opportunities returned ok={ok}")
    if not ok:
        raise HTTPException(
            status_code=502,
            detail="Opportunity status updated, but the Domo REPLACE upload failed.",
        )

    return {"account_id": account_id, "status": body.action}
