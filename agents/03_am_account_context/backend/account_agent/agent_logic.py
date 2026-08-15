"""
Agent 3 — AM Account Context Assembly & Post-Call Action Agent.

Screen 1 (build_briefing): joins the account's ERP/CRM/entitlement/
ticketing/usage/interaction-history data and asks Groq to do the
"Reason -> Decide" step - which of those raw facts actually matter for
this specific call, ranked, plus the single best upsell candidate, a
sentiment read, and 3-5 talking points that include any recent CRM/email
signal on file.

Screen 2 (extract_actions): takes free-text call notes (typed, or
transcribed from audio via Groq Whisper) and extracts structured
follow-up actions, grounded against the account's actual open tickets and
product catalog so the agent links to real ticket IDs instead of
inventing them.
"""
import json
from datetime import datetime

from .domo_client import DomoClient, parse_json_response

from . import data_store


def _today() -> datetime:
    return datetime.now()

BRIEFING_SYSTEM_PROMPT = """You are an assistant that prepares Account Managers for \
customer check-in calls. You are given a JSON snapshot of one account: \
invoice/payment status, product usage trend, open support tickets, contract \
terms, how long they've been a customer, which products from the catalog \
the account owns vs. doesn't own, when they last interacted with the AM, \
and (if any) a recent notable signal from CRM notes/email.

Your job:
1. Identify the single best upsell candidate from the products the account \
does NOT own, with a one-sentence reasoning grounded in the data given \
(usage trend, account tier, similar products already owned). If nothing in \
the data supports a confident recommendation, return null for the product \
rather than guessing. Give a fit_score from 0-100 reflecting how strong \
the signal actually is - do not default to a high score.
2. Read all the signals together (invoice status, ticket severity, usage \
direction, days since last interaction, the recent signal if present) and \
classify overall "customer_sentiment" as one of "positive", "cautiously_positive", \
"neutral", "at_risk", or "negative", plus a short human-readable \
"sentiment_label" (2-4 words, e.g. "Cautiously positive", "At risk of churn") \
and a one-sentence "sentiment_reason" grounded in the specific facts that drove it.
3. Produce 3-5 talking points for the AM, ordered by urgency. Financial \
issues (overdue invoices) and high-severity open tickets should generally \
outrank soft opportunities. If a recent signal is present, it should almost \
always produce one of the talking points (e.g. asking about a mentioned \
acquisition/expansion/headcount change). Each point must be grounded in a \
specific fact from the input - do not invent details not present in the data.
4. Write a short "pitch_strategy" (2-4 sentences) coaching the AM on HOW to \
run this specific call so the customer feels genuinely known, not sold to: \
what tone to take given the account's tier, tenure, and sentiment, what to \
lead with before asking for anything, and how to weave in the upsell \
candidate or top talking point naturally if/when the moment fits. Ground \
every sentence in the actual data - no generic sales platitudes.
5. Write one specific "opening_line" (one sentence, conversational, in \
quotes-free plain text) the AM could literally say in the first minute of \
the call to show they came prepared - referencing a real fact from the \
data (tenure, a ticket, a usage trend, or the recent signal), not a canned \
greeting.

Respond with ONLY a JSON object of this exact shape:
{
  "upsell_candidate": {
    "recommended_product": string or null,
    "reasoning": string or null,
    "fit_score": integer 0-100 or null
  },
  "customer_sentiment": "positive" | "cautiously_positive" | "neutral" | "at_risk" | "negative",
  "sentiment_label": string,
  "sentiment_reason": string,
  "talking_points": [
    {"point": string, "urgency": "high" | "medium" | "low"}
  ],
  "pitch_strategy": string,
  "opening_line": string
}
"""


def build_briefing(account_id: str, client: DomoClient) -> dict:
    context = data_store.get_account_context(account_id)
    last_interaction = data_store.get_last_interaction(account_id)
    signal = data_store.get_account_signal(account_id)

    days_since_interaction = None
    if last_interaction:
        days_since_interaction = (_today() - datetime.strptime(last_interaction["interaction_date"], "%Y-%m-%d")).days

    trace = [
        f"OBSERVE — Upcoming call: {context['account_name']}",
        "Fetching ERP invoice/payment status...",
        "Fetching product usage telemetry...",
        "Fetching open support tickets...",
        "Fetching recent interaction history and account signals...",
        "Checking contract terms and entitlements...",
        "REASON — Cross-referencing entitlement, sentiment, and risk signals...",
    ]

    llm_input = {
        "account_name": context["account_name"],
        "tier": context["tier"],
        "customer_since": context["account_since"],
        "contract": context["contract"],
        "owned_products": context["entitlements"]["owned"],
        "missing_products": context["entitlements"]["missing"],
        "usage_trend_last_12_weeks": context["usage"]["trend"],
        "usage_direction": context["usage"]["direction"],
        "invoice_status": context["invoices"]["overdue_summary"],
        "dso_days": context["invoices"]["dso_days"],
        "open_tickets": context["tickets"]["open_tickets"],
        "last_interaction": {
            "type": last_interaction["interaction_type"],
            "days_ago": days_since_interaction,
        } if last_interaction else None,
        "recent_signal": signal["signal_text"] if signal else None,
    }

    raw = client.chat(
        messages=[
            {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(llm_input)},
        ],
        json_mode=True,
        temperature=0.2,
    )
    synthesis = parse_json_response(raw)

    trace.append(
        f"DECIDE — Briefing assembled, {len(synthesis.get('talking_points', []))} talking points generated"
    )

    return {
        "account_id": account_id,
        "account_name": context["account_name"],
        "trace": trace,
        "invoice_status": context["invoices"]["overdue_summary"],
        "dso_days": context["invoices"]["dso_days"],
        "usage_trend": context["usage"]["trend"],
        "usage_direction": context["usage"]["direction"],
        "open_tickets": context["tickets"]["open_tickets"],
        "contract": context["contract"],
        "owned_products": context["entitlements"]["owned"],
        "last_interaction": {
            "type": last_interaction["interaction_type"],
            "date": last_interaction["interaction_date"],
            "days_ago": days_since_interaction,
        } if last_interaction else None,
        "recent_signal": signal["signal_text"] if signal else None,
        "upsell_candidate": synthesis.get("upsell_candidate", {}),
        "customer_sentiment": synthesis.get("customer_sentiment"),
        "sentiment_label": synthesis.get("sentiment_label"),
        "sentiment_reason": synthesis.get("sentiment_reason"),
        "talking_points": synthesis.get("talking_points", []),
        "pitch_strategy": synthesis.get("pitch_strategy"),
        "opening_line": synthesis.get("opening_line"),
    }


EXTRACTION_SYSTEM_PROMPT = """You extract concrete follow-up actions from an Account \
Manager's call notes. You are given the notes text plus a small amount of \
account context (currently open tickets, products the account already \
owns, products it doesn't own).

Rules:
- Each action is either type "task" (something operational to do, e.g. \
escalate a ticket, send a document) or "opportunity" (a sales/expansion \
signal to log against the account).
- If the notes reference an issue that matches one of the account's open \
tickets, set linked_ticket_id to that ticket's id. Otherwise leave it null.
- If the notes reference a product, set linked_product to the catalog \
product name if it matches one from owned_products or missing_products. \
Otherwise leave it null.
- Only extract actions actually implied by the notes. Do not invent \
actions that aren't supported by the text. If nothing actionable is in \
the notes, return an empty list.
- Keep each description under ~20 words, written as an instruction \
(e.g. "Escalate SIEM ticket TCK-570 to P1 before renewal call").

Respond with ONLY a JSON object of this exact shape:
{
  "actions": [
    {
      "type": "task" | "opportunity",
      "description": string,
      "linked_ticket_id": string or null,
      "linked_product": string or null
    }
  ]
}
"""


def extract_actions(account_id: str, notes_text: str, client: DomoClient) -> list[dict]:
    context = data_store.get_account_context(account_id)

    llm_input = {
        "notes_text": notes_text,
        "open_tickets": [
            {"ticket_id": t["ticket_id"], "subject": t["subject"], "product_area": t["product_area"]}
            for t in context["tickets"]["open_tickets"]
        ],
        "owned_products": context["entitlements"]["owned"],
        "missing_products": context["entitlements"]["missing"],
    }

    raw = client.chat(
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(llm_input)},
        ],
        json_mode=True,
        temperature=0.1,
    )
    parsed = parse_json_response(raw)

    if isinstance(parsed, dict):
        return parsed.get("actions", [])
    if isinstance(parsed, list):
        return parsed
    return []
