"""
Agent 4 — Renewal Opportunity Auto-Creation & Backlog Agent: seed data build.

Per Shashank's framing, the *base* renewal-creation step (a renewal
opportunity gets created the moment a deal closes, target date = contract
end date, assigned to the owning AM) is already automation, not the agent
- so this script just materializes that backlog directly from Agent 3's
real contracts.csv (account_id, term_months, start_date, renewal_date,
arr, am_owner all come straight from there; nothing about WHICH accounts
have a renewal or its value/date is invented).

What genuinely doesn't exist anywhere in the source data, and is
synthesized here:
- rep_hierarchy.csv - AM -> manager -> exec reporting lines (needed for
  the escalation hierarchy Shashank described). Manager/exec names reuse
  "Sandra", "Brian" from the transcript context (Sales Ops reviewers) for
  flavor.
- renewal_activity_log.csv - seed AM activity ("worked this renewal")
  entries. Deliberately skewed so some renewals look actively worked
  (recent activity) and others look dormant (stale or no activity at
  all) - that's the gap the agent exists to catch, so the seed data has
  to contain some.

Run once (or re-run after contracts.csv changes):
    python agents/agent4_renewal_backlog/backend/renewal_backlog/etl_build_renewal_backlog.py
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

THIS_BACKEND = Path(__file__).resolve().parent.parent  # agents/agent4_renewal_backlog/backend
AGENTS_ROOT = THIS_BACKEND.parent.parent                # agents/
AM_DATA_DIR = AGENTS_ROOT / "agent3_am_account_context" / "backend" / "data"
DATA_DIR = THIS_BACKEND / "data"
TODAY = datetime(2026, 8, 15)  # matches this environment's actual current date

# These 6 tables are Agent 3's own data - duplicated here so this agent's
# risk-scoring stays self-contained (see agents/renewal_backlog/data_store.py
# docstring for why duplication was chosen over a shared folder).
SHARED_TABLES = ["accounts.csv", "contracts.csv", "entitlements.csv",
                  "product_usage.csv", "invoices_payments.csv", "tickets.csv"]

MANAGERS = {
    "Ananya S.": "Sandra K.", "Daniel R.": "Sandra K.", "Elena F.": "Sandra K.",
    "Grace L.": "Sandra K.", "Hassan D.": "Sandra K.", "Jordan K.": "Sandra K.",
    "Leo B.": "Sandra K.",
    "Marcus T.": "Brian M.", "Nadia P.": "Brian M.", "Owen T.": "Brian M.",
    "Priya N.": "Brian M.", "Ravi C.": "Brian M.", "Tomas W.": "Brian M.",
}
EXECUTIVE = "Victor A. (VP Sales)"


def build_hierarchy() -> pd.DataFrame:
    rows = [{"am_owner": am, "manager": mgr, "executive": EXECUTIVE} for am, mgr in MANAGERS.items()]
    return pd.DataFrame(rows)


def build_renewal_opportunities(contracts: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    merged = contracts.merge(accounts[["account_id", "account_name", "am_owner", "tier"]], on="account_id")
    rows = []
    for i, row in merged.iterrows():
        renewal_date = datetime.strptime(row["renewal_date"], "%Y-%m-%d")
        target_close_date = renewal_date - timedelta(days=90)
        rows.append({
            "renewal_id": f"REN-{i + 1:03d}",
            "account_id": row["account_id"],
            "account_name": row["account_name"],
            "am_owner": row["am_owner"],
            "tier": row["tier"],
            "product_bundle": row["product_bundle"],
            "term_months": row["term_months"],
            "expected_value": row["arr"],
            "renewal_date": row["renewal_date"],
            "target_close_date": target_close_date.date().isoformat(),
            "trigger_event": "deal_closed_won",
            "trigger_timestamp": row["start_date"],
            "created_timestamp": row["start_date"],  # auto-created same instant the deal closed
            "status": "open",
        })
    return pd.DataFrame(rows)


def build_activity_log(renewals: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random("agent4-renewal-activity")
    rows = []
    log_id = 1
    for _, r in renewals.iterrows():
        renewal_date = datetime.strptime(r["renewal_date"], "%Y-%m-%d")
        days_to_renewal = (renewal_date - TODAY).days
        # Renewals far out or already past get a mix; near-term ones are the
        # interesting cases so bias more of them toward "dormant".
        if days_to_renewal > 240:
            has_activity, staleness = rng.random() < 0.5, rng.randint(5, 60)
        elif days_to_renewal > 90:
            has_activity, staleness = rng.random() < 0.4, rng.randint(20, 90)
        else:
            has_activity, staleness = rng.random() < 0.25, rng.randint(45, 120)

        if has_activity:
            activity_date = TODAY - timedelta(days=staleness)
            rows.append({
                "log_id": f"RACT-{log_id:03d}",
                "renewal_id": r["renewal_id"],
                "activity_date": activity_date.date().isoformat(),
                "actor": r["am_owner"],
                "note": rng.choice([
                    "Sent renewal check-in email to customer.",
                    "Had a call with the customer about renewal terms.",
                    "Updated renewal notes after QBR discussion.",
                    "Confirmed budget owner and renewal timeline with customer.",
                ]),
            })
            log_id += 1
    return pd.DataFrame(rows, columns=["log_id", "renewal_id", "activity_date", "actor", "note"])


def main():
    contracts = pd.read_csv(AM_DATA_DIR / "contracts.csv")
    accounts = pd.read_csv(AM_DATA_DIR / "accounts.csv")

    for table in SHARED_TABLES:
        pd.read_csv(AM_DATA_DIR / table).to_csv(DATA_DIR / table, index=False)

    build_hierarchy().to_csv(DATA_DIR / "rep_hierarchy.csv", index=False)

    renewals = build_renewal_opportunities(contracts, accounts)
    renewals.to_csv(DATA_DIR / "renewal_opportunities.csv", index=False)

    activity = build_activity_log(renewals)
    activity.to_csv(DATA_DIR / "renewal_activity_log.csv", index=False)

    (DATA_DIR / "renewal_adjustments_log.csv").write_text(
        "adjustment_id,renewal_id,field,new_value,adjusted_by,adjusted_at\n"
    )
    (DATA_DIR / "renewal_escalation_log.csv").write_text(
        "escalation_id,renewal_id,level,notified,action,triggered_at\n"
    )

    n_with_activity = activity["renewal_id"].nunique()
    print(f"Built {len(renewals)} renewal opportunities across {renewals['am_owner'].nunique()} AMs; "
          f"{n_with_activity} have at least one logged activity, "
          f"{len(renewals) - n_with_activity} have none (dormant candidates).")


if __name__ == "__main__":
    main()
