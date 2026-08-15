from . import data_store, domo_client

SYSTEM_PROMPT = (
    "You are an assistant helping a Channel Manager review new partner applications for a "
    "distributor/reseller program. You are concise (2-3 sentences), factual, and never invent "
    "facts beyond what is given. You don't decide the program's eligibility rules yourself - "
    "you only explain, in plain language, what the rules-based check already determined."
)


def correct_track(app: dict) -> str:
    """The track the applicant's actual attributes imply, independent of what they requested."""
    if app["is_wholesale_only"] and not app["sells_direct"]:
        return "Distributor"
    if app["sells_direct"]:
        return "Reseller/MSP"
    return "Ambiguous"


def match_tier(track: str, app: dict) -> dict | None:
    """Highest tier this applicant qualifies for on the given track, or None if they
    don't meet the minimum bar for any tier yet."""
    candidates = [
        c for c in data_store.criteria_for_track(track)
        if app["volume_or_accounts"] >= c["min_volume_or_accounts"]
        and (not c["requires_managed_services"] or app["has_managed_services"])
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["min_volume_or_accounts"])


def _build_reasons(app: dict, correct: str, mismatch: bool, tier: dict | None, conflict: dict | None) -> list[str]:
    reasons = []
    if app["is_wholesale_only"]:
        reasons.append("Applicant confirmed a wholesale-only sales model (no direct end-customer sales).")
    if app["sells_direct"]:
        reasons.append("Applicant sells directly to end customers.")
    if app["has_managed_services"]:
        reasons.append("Applicant has a managed-services/technical-support capability.")
    reasons.append(f"Reported volume/account count: {app['volume_or_accounts']}.")

    if correct == "Ambiguous":
        reasons.append("Attributes don't clearly indicate wholesale-only or direct-selling - more information is needed.")
    elif mismatch:
        reasons.append(
            f"Requested track '{app['requested_track']}' does not match the applicant's actual "
            f"sales model, which fits the '{correct}' track instead."
        )
    if tier is None and correct != "Ambiguous":
        reasons.append(f"Volume/accounts fall below the minimum threshold for any {correct} tier.")
    elif tier:
        reasons.append(f"Qualifies for {tier['track']} {tier['tier']} tier ({tier['discount_pct']:.0f}% discount schedule).")
    if conflict:
        reasons.append(conflict["conflict_detail"])
    return reasons


def classify(app: dict) -> dict:
    """Rule-based classification only, no LLM call - fast enough to run for every row
    in the Applications Queue table (Screen 2's 'program-criteria match status')."""
    correct = correct_track(app)
    mismatch = correct != "Ambiguous" and correct != app["requested_track"]
    effective_track = correct if correct != "Ambiguous" else app["requested_track"]
    tier = match_tier(effective_track, app)
    conflict = data_store.get_conflict(app["company_name"])

    if correct == "Ambiguous":
        status = "Info Requested"
    elif conflict:
        status = "Exception"
    elif mismatch:
        status = "Exception"
    elif tier is None:
        status = "Exception"
    else:
        status = "Cleared"

    return {
        "correct_track": correct,
        "track_mismatch": mismatch,
        "recommended_tier": tier,
        "conflict": conflict,
        "status": status,
        "reasons": _build_reasons(app, correct, mismatch, tier, conflict),
    }


def queue_row(app: dict) -> dict:
    """One row for Screen 2's Applications Queue table."""
    c = classify(app)
    return {
        "id": app["id"],
        "company_name": app["company_name"],
        "requested_track": app["requested_track"],
        "match_status": c["status"],
        "current_status": app["status"],
        "submitted_date": app["submitted_date"],
    }


def queue_metrics(applications: list[dict]) -> dict:
    """Screen 2's metrics: applications this month, approval rate by track."""
    this_month = applications[0]["submitted_date"][:7] if applications else ""
    apps_this_month = sum(1 for a in applications if a["submitted_date"][:7] == this_month)

    by_track = {}
    for a in applications:
        track = a.get("assigned_track") or a["requested_track"]
        decided = a["status"] in ("Approved", "Rejected")
        if not decided:
            continue
        by_track.setdefault(track, {"approved": 0, "total": 0})
        by_track[track]["total"] += 1
        if a["status"] == "Approved":
            by_track[track]["approved"] += 1

    approval_rate_by_track = {
        track: round(100 * v["approved"] / v["total"]) if v["total"] else 0
        for track, v in by_track.items()
    }
    return {"applications_this_month": apps_this_month, "approval_rate_by_track": approval_rate_by_track}


def review_application(app_id: str) -> dict | None:
    """Screen 3's Approval card detail: rule-based classification plus an LLM-phrased
    summary for the Channel Manager."""
    app = data_store.get_application(app_id)
    if not app:
        return None

    c = classify(app)
    correct, mismatch, tier, conflict, status, reasons = (
        c["correct_track"], c["track_mismatch"], c["recommended_tier"], c["conflict"], c["status"], c["reasons"]
    )

    prompt = (
        f"Partner application: {app['company_name']} ({app['geography']}), requested track "
        f"'{app['requested_track']}'.\nFindings: {'; '.join(reasons)}\nOverall status: {status}.\n\n"
        f"Write a short summary for the Channel Manager explaining this application's status and "
        f"what, if anything, needs their attention."
    )
    summary = domo_client.generate_text(prompt, system=SYSTEM_PROMPT)
    if not summary:
        summary = f"{app['company_name']}: {status}. " + " ".join(reasons)

    return {
        "id": app["id"],
        "company_name": app["company_name"],
        "requested_track": app["requested_track"],
        "correct_track": correct,
        "track_mismatch": mismatch,
        "recommended_tier": tier,
        "conflict": conflict,
        "status": status,
        "reasons": reasons,
        "summary": summary,
    }


def list_queue() -> dict:
    """Screen 2's full Applications Queue payload: rows + metrics."""
    applications = data_store.list_applications()
    return {
        "rows": [queue_row(a) for a in applications],
        "metrics": queue_metrics(applications),
    }


def submit_application(
    company_name: str, contact_name: str, contact_email: str, requested_track: str,
    geography: str, is_wholesale_only: bool, sells_direct: bool, has_managed_services: bool,
    volume_or_accounts: int, notes: str = "",
) -> dict:
    """Screen 1's Partner Application Form submission."""
    return data_store.add_application({
        "company_name": company_name, "contact_name": contact_name, "contact_email": contact_email,
        "requested_track": requested_track, "geography": geography,
        "is_wholesale_only": is_wholesale_only, "sells_direct": sells_direct,
        "has_managed_services": has_managed_services, "volume_or_accounts": volume_or_accounts,
        "notes": notes,
    })


def approve_application(app_id: str, track: str, tier: str, note: str = "") -> dict | None:
    app = data_store.get_application(app_id)
    if not app:
        return None
    criteria = next(
        (c for c in data_store.criteria_for_track(track) if c["tier"] == tier), None
    )
    if not criteria:
        return {"error": f"No such tier '{tier}' for track '{track}'"}

    updates = {
        "status": "Approved",
        "assigned_track": track,
        "assigned_tier": tier,
        "notes": (app["notes"] + f" | Approved by Channel Manager: {note}").strip(" |"),
    }
    app = data_store.update_application(app_id, updates)
    return {
        "application": app,
        "provisioning": {
            "prm_status": "Provisioned",
            "track": track,
            "tier": tier,
            "discount_pct": criteria["discount_pct"],
            "notification": f"Notification sent to {app['contact_email']} confirming {track} {tier} tier enrollment.",
        },
    }


def reject_application(app_id: str, reason: str) -> dict | None:
    app = data_store.get_application(app_id)
    if not app:
        return None
    return data_store.update_application(app_id, {
        "status": "Rejected",
        "notes": (app["notes"] + f" | Rejected: {reason}").strip(" |"),
    })


def request_more_info(app_id: str, requested_info: str) -> dict | None:
    app = data_store.get_application(app_id)
    if not app:
        return None
    return data_store.update_application(app_id, {
        "status": "Info Requested",
        "notes": (app["notes"] + f" | Info requested: {requested_info}").strip(" |"),
    })
