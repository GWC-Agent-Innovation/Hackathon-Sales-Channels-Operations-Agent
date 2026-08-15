"""
Agent 3 enrichment: two small synthetic feeds that don't exist anywhere in
the source workbook (no email or meeting-history integration was ever
provided), but are needed to match the reference UI's "recent interaction"
and "recent signal" (subsidiary acquisition, expansion, etc.) elements on
the pre-call briefing.

    account_last_interaction.csv  -> stands in for calendar/meeting history
                                      (last QBR/call/email, and when)
    account_signals.csv            -> stands in for a lightweight CRM notes/
                                       email-signal feed - a notable recent
                                       event worth mentioning on the call,
                                       for about half the accounts (some
                                       accounts genuinely have nothing new)

Run once (or re-run to reshuffle):
    python data/build_account_signals.py
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"  # agents/agent3_am_account_context/backend/data
TODAY = datetime(2026, 8, 15)

INTERACTION_TYPES = ["QBR", "Discovery call", "Check-in call", "Email thread", "Renewal discussion"]

SIGNAL_POOL = [
    "Recent email suggests a subsidiary acquisition — confirm and ask about licensing needs.",
    "Customer mentioned opening a second office location in an email thread.",
    "Contact mentioned a recent reduction in headcount during the last call.",
    "Customer's IT director moved to a new role — relationship may need rebuilding.",
    "Customer flagged interest in a competitor's product during a support ticket exchange.",
    "Recent email thread mentions an upcoming compliance audit that may affect renewal timing.",
    "Customer mentioned budget planning for next fiscal year is already underway.",
    "A new stakeholder was CC'd on recent emails — may indicate a champion change.",
]


def main():
    accounts = pd.read_csv(DATA_DIR / "accounts.csv")
    rng = random.Random("agent3-signals")

    interaction_rows = []
    for _, a in accounts.iterrows():
        days_ago = rng.randint(5, 95)
        interaction_rows.append({
            "account_id": a["account_id"],
            "interaction_type": rng.choice(INTERACTION_TYPES),
            "interaction_date": (TODAY - timedelta(days=days_ago)).date().isoformat(),
        })
    pd.DataFrame(interaction_rows).to_csv(DATA_DIR / "account_last_interaction.csv", index=False)

    signal_rows = []
    signal_accounts = rng.sample(list(accounts["account_id"]), k=len(accounts) // 2)
    for account_id in signal_accounts:
        days_ago = rng.randint(1, 20)
        signal_rows.append({
            "account_id": account_id,
            "signal_date": (TODAY - timedelta(days=days_ago)).date().isoformat(),
            "signal_text": rng.choice(SIGNAL_POOL),
        })
    pd.DataFrame(signal_rows, columns=["account_id", "signal_date", "signal_text"]).to_csv(
        DATA_DIR / "account_signals.csv", index=False
    )

    print(f"Built last-interaction records for {len(interaction_rows)} accounts, "
          f"signals for {len(signal_rows)} of them.")


if __name__ == "__main__":
    main()
