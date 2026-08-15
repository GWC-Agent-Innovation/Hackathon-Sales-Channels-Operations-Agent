from datetime import date, datetime

from . import data_store, domo_client

STAGE_ORDER = ["Lead", "Opportunity", "Qualified", "Proposal", "Negotiation", "Contract Signature", "Closed Won"]

# Each stage's gate: the fields that must be satisfied before the deal can move
# to the next stage. This mirrors the mandatory-field rules already enforced in
# the CRM (built by the CRM admin team) - the agent doesn't invent the rules,
# it just tells the rep which ones are still open.
GATES = {
    "Lead": {
        "next": "Opportunity",
        "requirements": [("need_confirmed", "Confirm the prospect has a genuine need (hold a discovery call)", "bool")],
    },
    "Opportunity": {
        "next": "Qualified",
        "requirements": [
            ("budget_confirmed", "Confirm the customer has budget", "bool"),
            ("decision_maker_identified", "Identify and engage the decision maker", "bool"),
        ],
    },
    "Qualified": {
        "next": "Proposal",
        "requirements": [("requirements_captured", "Capture and scope the customer's requirements", "bool")],
    },
    "Proposal": {
        "next": "Negotiation",
        "requirements": [("proposal_shared_date", "Draft and share the proposal with the client", "date")],
    },
    "Negotiation": {
        "next": "Contract Signature",
        "requirements": [("terms_agreed", "Resolve redlines and agree on commercial terms", "bool")],
    },
    "Contract Signature": {
        "next": "Closed Won",
        "requirements": [("signature_received_date", "Receive the signed contract", "date")],
    },
    "Closed Won": {"next": None, "requirements": []},
    "Closed Lost": {"next": None, "requirements": []},
}

SYSTEM_PROMPT = (
    "You are a sales assistant embedded in a CRM, helping a New Customer Acquisition "
    "(NCA) rep move a deal through the pipeline as fast as possible. You are concise, "
    "conversational (1-3 sentences), and specific to the account - never invent facts "
    "beyond what is given. You don't decide CRM rules yourself, you only phrase what the "
    "rep should confirm or do next."
)


def missing_requirements(opp: dict) -> list[dict]:
    gate = GATES.get(opp["stage"])
    if not gate or not gate["next"]:
        return []
    missing = []
    for field, label, ftype in gate["requirements"]:
        value = opp.get(field)
        satisfied = bool(value) if ftype == "bool" else bool(str(value or "").strip())
        if not satisfied:
            missing.append({"field": field, "label": label, "type": ftype})
    return missing


def days_since_last_activity(opp: dict, today: date | None = None) -> int:
    today = today or date.today()
    last = datetime.strptime(opp["last_activity_date"], "%Y-%m-%d").date()
    return (today - last).days


def open_commitments(opp_id: str) -> list[dict]:
    return [
        a for a in data_store.get_activities(opp_id)
        if a.get("commitment") and a.get("commitment_fulfilled") is False
    ]


def _context_block(opp: dict) -> str:
    activities = data_store.get_activities(opp["id"])
    recent = "; ".join(f"{a['activity_date']} {a['activity_type']}: {a['summary']}" for a in activities[:3]) or "None logged."
    return (
        f"Account: {opp['account_name']}\nContact: {opp['contact_name']}\n"
        f"Product: {opp['product_line']}\nDeal value: ${opp['deal_value']:,.0f}\n"
        f"Stage: {opp['stage']}\nRecent activity: {recent}\nNotes: {opp['notes']}"
    )


def get_suggestion(opp_id: str) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None

    if opp["stage"] in ("Closed Won", "Closed Lost"):
        return {
            "message": f"{opp['account_name']} is {opp['stage']} - no further stage-progression action needed.",
            "missing": [],
            "ready_to_advance": False,
            "next_stage": None,
            "document_type": None,
        }

    missing = missing_requirements(opp)
    gate = GATES[opp["stage"]]
    context = _context_block(opp)

    if missing:
        fields_text = "; ".join(m["label"] for m in missing)
        prompt = (
            f"{context}\n\nTo progress this deal to '{gate['next']}', these fields/actions are still "
            f"outstanding: {fields_text}. Write a short chat message telling the rep exactly what's "
            f"missing, referencing something concrete from the account context."
        )
    else:
        prompt = (
            f"{context}\n\nAll requirements for the current stage are satisfied. Write a short chat "
            f"message telling the rep this deal is ready to advance to '{gate['next']}', referencing "
            f"something concrete from the account context."
        )
    message = domo_client.generate_text(prompt, system=SYSTEM_PROMPT)
    if not message:
        message = (
            f"{opp['account_name']} still needs: {'; '.join(m['label'] for m in missing)}."
            if missing else f"{opp['account_name']} is ready to advance to {gate['next']}."
        )

    return {
        "message": message,
        "missing": missing,
        "ready_to_advance": not missing,
        "next_stage": gate["next"],
        "document_type": "Proposal" if opp["stage"] == "Proposal" and missing else None,
    }


def confirm_field(opp_id: str, field: str) -> dict | None:
    """Rep confirms a boolean/date requirement is done; auto-advances the stage if the gate is now clear."""
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    ftype = "date" if field in data_store.DATE_FIELDS else "bool"
    value = date.today().isoformat() if ftype == "date" else True
    opp = data_store.update_opportunity_fields(opp_id, {field: value})

    advanced = False
    if not missing_requirements(opp):
        next_stage = GATES[opp["stage"]]["next"]
        if next_stage:
            opp = data_store.update_stage(opp_id, next_stage)
            advanced = True
    return {"opportunity": opp, "advanced": advanced}


def advance_stage_if_ready(opp_id: str) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp or missing_requirements(opp):
        return {"opportunity": opp, "advanced": False}
    next_stage = GATES[opp["stage"]]["next"]
    if not next_stage:
        return {"opportunity": opp, "advanced": False}
    opp = data_store.update_stage(opp_id, next_stage)
    return {"opportunity": opp, "advanced": True}


def mark_closed_lost(opp_id: str, reason: str) -> dict | None:
    return data_store.update_opportunity_fields(opp_id, {"stage": "Closed Lost", "closed_lost_reason": reason})


def _draft_proposal(opp: dict) -> dict:
    product = data_store.get_product(opp["product_line"]) or {}
    prompt = (
        f"Draft a short, professional proposal body (plain text, 4-6 sentences, no markdown) for:\n"
        f"Account: {opp['account_name']}\nContact: {opp['contact_name']}\n"
        f"Product: {opp['product_line']} - {product.get('description', '')}\n"
        f"Deal value: ${opp['deal_value']:,.0f}\nBilling: {product.get('billing_model', 'Annual')}\n"
        f"Notes: {opp['notes']}\n\nSummarize the offer and the next step for the customer to confirm."
    )
    body = domo_client.generate_text(prompt, system="You are drafting a sales proposal for a B2B security software deal.")
    if not body:
        body = (
            f"Dear {opp['contact_name']},\n\nThank you for considering {opp['product_line']} for "
            f"{opp['account_name']}. We're pleased to propose this solution at ${opp['deal_value']:,.0f} "
            f"on a {product.get('billing_model', 'Annual').lower()} basis. Please review and let us know "
            f"if you have any questions - we look forward to moving forward together."
        )
    return {
        "document_type": "Proposal", "account_name": opp["account_name"], "contact_name": opp["contact_name"],
        "product_line": opp["product_line"], "deal_value": opp["deal_value"],
        "billing_model": product.get("billing_model", "Annual"), "body": body,
    }


def generate_document_preview(opp_id: str) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    document = _draft_proposal(opp)
    data_store.save_document(opp_id, document)
    return document


def confirm_proposal_sent(opp_id: str, edited_document: dict | None = None) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    document = edited_document or data_store.get_document(opp_id) or _draft_proposal(opp)
    data_store.save_document(opp_id, document)
    data_store.add_activity(
        opp_id, date.today().isoformat(), "Email",
        f"Proposal shared with {opp['contact_name']} ({opp['account_name']})",
    )
    return confirm_field(opp_id, "proposal_shared_date") | {"document": document}


def get_timeline(opp_id: str) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    if opp["stage"] == "Closed Lost":
        return {"opportunity_id": opp_id, "current_stage": "Closed Lost", "stages": [
            {"name": s, "status": "complete"} for s in STAGE_ORDER[:-1]
        ] + [{"name": "Closed Lost", "status": "current"}]}
    current_index = STAGE_ORDER.index(opp["stage"])
    stages = [
        {"name": s, "status": "complete" if i < current_index else "current" if i == current_index else "pending"}
        for i, s in enumerate(STAGE_ORDER)
    ]
    return {"opportunity_id": opp_id, "current_stage": opp["stage"], "stages": stages}


# ---- Daily action-prioritization assistant ----

def _priority_score(opp: dict, missing: list[dict], commitments: list[dict], stale_days: int) -> int:
    score = 0
    score += 4 * len(commitments)
    score += 3 if stale_days >= 10 else (1 if stale_days >= 5 else 0)
    score += 2 if opp["stage"] in ("Negotiation", "Contract Signature") else 0
    score += len(missing)
    return score


def get_daily_priorities(rep_name: str) -> list[dict]:
    opps = data_store.list_opportunities_for_rep(rep_name, open_only=True)
    results = []
    for opp in opps:
        missing = missing_requirements(opp)
        commitments = open_commitments(opp["id"])
        stale_days = days_since_last_activity(opp)

        if commitments:
            pattern = data_store.get_pattern("commitment")
        elif stale_days >= 10:
            pattern = data_store.get_pattern("stale")
        else:
            pattern = data_store.get_pattern(opp["stage"])

        context = _context_block(opp)
        commitment_text = (
            "; ".join(f"promised '{c['commitment']}' on {c['activity_date']}, still not done" for c in commitments)
            or "None outstanding."
        )
        prompt = (
            f"{context}\nDays since last activity: {stale_days}\nOpen unfulfilled commitments: {commitment_text}\n"
            f"Relevant historical pattern: {pattern}\n\n"
            f"In one short, specific sentence, tell the rep the single most important action to take on this "
            f"deal today to move it forward as fast as possible."
        )
        action = domo_client.generate_text(
            prompt, system="You prioritize a sales rep's daily action list across open deals."
        )
        if not action:
            if commitments:
                action = f"Follow through on your promise: {commitments[0]['commitment']}."
            elif missing:
                action = f"Move this forward by addressing: {missing[0]['label']}."
            else:
                action = f"Stale for {stale_days} days - check in with {opp['contact_name']}."

        results.append({
            "opportunity_id": opp["id"], "account_name": opp["account_name"], "stage": opp["stage"],
            "deal_value": opp["deal_value"], "stale_days": stale_days,
            "missing": missing, "commitments": commitments, "pattern": pattern,
            "recommended_action": action,
            "score": _priority_score(opp, missing, commitments, stale_days),
        })
    return sorted(results, key=lambda r: r["score"], reverse=True)


# ---- Meeting/call note ingestion ----

def analyze_meeting_note(opp_id: str, note_text: str) -> dict | None:
    """Uses the LLM to extract which pending gate fields the note satisfies and any new
    commitment made, so the rep can confirm before anything is written to the CRM."""
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    missing = missing_requirements(opp)
    pending_fields = ", ".join(m["field"] for m in missing) or "none"

    prompt = (
        f"A sales rep just logged this note about a call/meeting with {opp['account_name']}:\n"
        f'"{note_text}"\n\n'
        f"Pending CRM fields for this deal's current stage ({opp['stage']}): {pending_fields}.\n\n"
        f"Reply in exactly this format, nothing else:\n"
        f"FIELDS_SATISFIED: <comma-separated field names from the pending list that this note confirms, or 'none'>\n"
        f"COMMITMENT: <a new promise the rep made to the customer in this note, or 'none'>\n"
        f"SUMMARY: <one sentence summary of the note for the activity log>"
    )
    raw = domo_client.generate_text(
        prompt, system="You extract structured CRM updates from freeform sales call notes. Be conservative - only mark a field satisfied if the note clearly confirms it."
    )

    satisfied_fields, commitment, summary = [], "", note_text[:200]
    if raw:
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("FIELDS_SATISFIED:"):
                value = line.split(":", 1)[1].strip()
                if value.lower() != "none":
                    pending_names = [m["field"] for m in missing]
                    satisfied_fields = [f.strip() for f in value.split(",") if f.strip() in pending_names]
            elif line.upper().startswith("COMMITMENT:"):
                value = line.split(":", 1)[1].strip()
                commitment = "" if value.lower() == "none" else value
            elif line.upper().startswith("SUMMARY:"):
                summary = line.split(":", 1)[1].strip()

    return {
        "note_text": note_text,
        "suggested_fields": [m for m in missing if m["field"] in satisfied_fields],
        "suggested_commitment": commitment,
        "summary": summary,
    }


def apply_meeting_note(opp_id: str, summary: str, confirmed_fields: list[str], commitment: str) -> dict | None:
    opp = data_store.get_opportunity(opp_id)
    if not opp:
        return None
    data_store.add_activity(
        opp_id, date.today().isoformat(), "Call/Meeting", summary,
        commitment=commitment, commitment_fulfilled=False if commitment else None,
    )
    for field in confirmed_fields:
        ftype = "date" if field in data_store.DATE_FIELDS else "bool"
        value = date.today().isoformat() if ftype == "date" else True
        opp = data_store.update_opportunity_fields(opp_id, {field: value})

    advanced = False
    if not missing_requirements(opp):
        next_stage = GATES[opp["stage"]]["next"]
        if next_stage:
            opp = data_store.update_stage(opp_id, next_stage)
            advanced = True
    return {"opportunity": opp, "advanced": advanced}
