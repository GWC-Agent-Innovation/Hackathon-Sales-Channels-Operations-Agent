from . import data_store, domo_client

SYSTEM_PROMPT = (
    "You are an assistant helping Sales Leadership (SLT) and frontline managers understand "
    "rep performance. You are concise (2-4 sentences), factual, and never invent facts beyond "
    "what is given. You diagnose WHY a gap exists using the supporting data provided (activity "
    "volume trend, deal value trend) rather than just restating that a number is below target."
)

# Below-target and above-target thresholds, in the primary metric's own units
# (percentage points for conversion_ratio/churn_rate).
COACHING_THRESHOLD = 5.0
RECOGNITION_THRESHOLD = 5.0
CHURN_COACHING_THRESHOLD = 1.5
CHURN_RECOGNITION_THRESHOLD = 1.5


def primary_metric(role: str) -> str:
    return "conversion_ratio" if role == "NCA" else "churn_rate"


def _trend_label(series: list[float], higher_is_better: bool) -> str:
    if len(series) < 2:
        return "stable"
    delta = series[-1] - series[0]
    if abs(delta) < 0.05 * max(abs(series[0]), 1):
        return "stable"
    improving = delta > 0 if higher_is_better else delta < 0
    return "improving" if improving else "declining"


def gap_analysis(rep_id: str) -> dict | None:
    rep = data_store.get_rep(rep_id)
    target = data_store.get_target(rep_id)
    history = data_store.get_history(rep_id)
    if not rep or not target or not history:
        return None

    metric = primary_metric(rep["role"])
    series = [h[metric] for h in history]
    periods = [h["period"] for h in history]
    latest = series[-1]

    if metric == "conversion_ratio":
        target_value = target["conversion_ratio_target"]
        gap = latest - target_value
        higher_is_better = True
        coaching_cut, recognition_cut = -COACHING_THRESHOLD, RECOGNITION_THRESHOLD
    else:
        target_value = target["churn_rate_target"]
        gap = target_value - latest  # positive = churn better (lower) than target
        higher_is_better = False
        coaching_cut, recognition_cut = -CHURN_COACHING_THRESHOLD, CHURN_RECOGNITION_THRESHOLD

    if gap <= coaching_cut:
        status = "Below Target"
    elif gap >= recognition_cut:
        status = "Exceeding Target"
    else:
        status = "On Target"

    deal_value_series = [h["deal_value"] for h in history]
    deal_value_latest = deal_value_series[-1]
    deal_value_target = target["deal_value_target"]
    deal_value_gap_pct = (
        round(100 * (deal_value_latest - deal_value_target) / deal_value_target, 1)
        if deal_value_target else None
    )

    activity_series = [h["activity_volume"] for h in history]

    return {
        "rep_id": rep_id,
        "name": rep["name"],
        "role": rep["role"],
        "manager_name": rep["manager_name"],
        "metric": metric,
        "latest_value": latest,
        "target_value": target_value,
        "gap": round(gap, 1),
        "status": status,
        "metric_trend": _trend_label(series, higher_is_better),
        "activity_trend": _trend_label(activity_series, True),
        "deal_value_latest": deal_value_latest,
        "deal_value_target": deal_value_target,
        "deal_value_gap_pct": deal_value_gap_pct,
        "periods": periods,
        "metric_series": series,
        "activity_series": activity_series,
        "deal_value_series": deal_value_series,
    }


def dashboard_rows() -> list[dict]:
    return [gap_analysis(r["id"]) for r in data_store.list_reps()]


def dashboard_metrics(rows: list[dict]) -> dict:
    below = [r for r in rows if r["status"] == "Below Target"]
    return {
        "reps_below_target": len(below),
        "avg_gap_size": round(sum(abs(r["gap"]) for r in below) / len(below), 1) if below else 0.0,
    }


def _diagnosis_prompt(g: dict) -> str:
    metric_label = "conversion ratio" if g["metric"] == "conversion_ratio" else "churn rate"
    return (
        f"Rep: {g['name']} ({g['role']})\n"
        f"{metric_label.title()} trend over the last {len(g['periods'])} periods: {g['metric_series']} "
        f"(target: {g['target_value']}, latest: {g['latest_value']}, trend: {g['metric_trend']})\n"
        f"Activity volume trend (calls/customer touchpoints): {g['activity_series']} (trend: {g['activity_trend']})\n"
        f"Deal value trend: {g['deal_value_series']} (target: {g['deal_value_target']}, "
        f"gap vs target: {g['deal_value_gap_pct']}%)\n"
        f"Overall status: {g['status']}.\n\n"
        f"Diagnose what's likely driving this - is it an activity/effort problem, a skill/conversion "
        f"problem, or something else? Reference the specific numbers above."
    )


def review_rep(rep_id: str) -> dict | None:
    g = gap_analysis(rep_id)
    if not g:
        return None

    diagnosis = domo_client.generate_text(_diagnosis_prompt(g), system=SYSTEM_PROMPT)
    if not diagnosis:
        metric_label = "conversion ratio" if g["metric"] == "conversion_ratio" else "churn rate"
        diagnosis = (
            f"{g['name']}'s {metric_label} is {g['status'].lower()} (latest {g['latest_value']} vs "
            f"target {g['target_value']}), trending {g['metric_trend']} while activity volume is "
            f"{g['activity_trend']}."
        )

    recommended_action = (
        "Create Coaching Task" if g["status"] == "Below Target"
        else "Nominate for Recognition" if g["status"] == "Exceeding Target"
        else "None"
    )

    return {**g, "diagnosis": diagnosis, "recommended_action": recommended_action}


def create_coaching_task(rep_id: str, note: str = "") -> dict | None:
    g = gap_analysis(rep_id)
    rep = data_store.get_rep(rep_id)
    if not g or not rep:
        return None
    metric_label = "conversion ratio" if g["metric"] == "conversion_ratio" else "churn rate"
    summary = (
        f"{g['name']}'s {metric_label} is {g['status'].lower()} "
        f"(latest {g['latest_value']} vs target {g['target_value']}, trending {g['metric_trend']})."
        + (f" Note: {note}" if note else "")
    )
    return data_store.create_coaching_task(rep_id, rep["manager_name"], summary)


def nominate_recognition(rep_id: str, note: str = "") -> dict | None:
    g = gap_analysis(rep_id)
    if not g:
        return None
    metric_label = "conversion ratio" if g["metric"] == "conversion_ratio" else "churn rate"
    summary = (
        f"{g['name']} is exceeding target on {metric_label} "
        f"(latest {g['latest_value']} vs target {g['target_value']}, trending {g['metric_trend']})."
        + (f" Note: {note}" if note else "")
    )
    return data_store.create_recognition_nomination(rep_id, summary)


def decide_recognition(nomination_id: str, approved: bool) -> dict | None:
    return data_store.update_recognition_nomination(
        nomination_id, "Approved" if approved else "Rejected"
    )
