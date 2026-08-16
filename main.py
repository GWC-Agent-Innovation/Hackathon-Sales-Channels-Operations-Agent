"""Single unified FastAPI app for all six built agents.

Mounts each agent's independent FastAPI app under its own path prefix, so each
agent's existing routes (e.g. /api/opportunities) work unchanged underneath it:

  /agent1/api/...   Sales Deal Guardrail & Order Validation Agent
  /agent2/api/...   NCA Lead-to-Order Conversion Assistant Agent
  /agent3/api/...   AM Account Context Assembly & Post-Call Action Agent
  /agent4/api/...   Renewal Opportunity Auto-Creation & Backlog Agent
  /agent5/api/...   Distributor & Reseller (MSP) Partner Onboarding Agent
  /agent6/api/...   AM Cross-Sell/Upsell Opportunity Creation Agent
  /agent7/api/...   Sales Rep Performance & Coaching Trigger Agent

Each agent's own package is imported one at a time and then evicted from
sys.modules before the next is loaded, since they're separate packages living
in separate directories but some of their submodule names could otherwise
collide.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_agent_app(backend_dir: str, package_name: str, has_backend_subdir: bool = True):
    backend_path = str(
        ROOT / "agents" / backend_dir / "backend" if has_backend_subdir else ROOT / "agents"
    )
    sys.path.insert(0, backend_path)
    try:
        module = __import__(f"{package_name}.main", fromlist=["app"])
        return module.app
    finally:
        sys.path.remove(backend_path)
        for name in list(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                del sys.modules[name]


deal_guardrail_app = _load_agent_app("01_deal_guardrail", "deal_guardrail")
nca_app = _load_agent_app("02-nca-lead-to-order", "nca_agent")
account_agent_app = _load_agent_app("03_am_account_context", "account_agent")
renewal_backlog_app = _load_agent_app("04_renewal_backlog", "renewal_backlog")
partner_app = _load_agent_app("05-partner-onboarding", "partner_agent")
cross_sell_app = _load_agent_app(
    "06_am_cross_sell_upsell", "06_am_cross_sell_upsell", has_backend_subdir=False
)
coaching_app = _load_agent_app("07-rep-performance-coaching", "coaching_agent")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Sales & Channel/Partner Operations - Agent Suite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/agent1", deal_guardrail_app)
app.mount("/agent2", nca_app)
app.mount("/agent3", account_agent_app)
app.mount("/agent4", renewal_backlog_app)
app.mount("/agent5", partner_app)
app.mount("/agent6", cross_sell_app)
app.mount("/agent7", coaching_app)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "agents": {
            "agent1": "Sales Deal Guardrail & Order Validation Agent - mounted at /agent1",
            "agent2": "NCA Lead-to-Order Conversion Assistant Agent - mounted at /agent2",
            "agent3": "AM Account Context Assembly & Post-Call Action Agent - mounted at /agent3",
            "agent4": "Renewal Opportunity Auto-Creation & Backlog Agent - mounted at /agent4",
            "agent5": "Distributor & Reseller (MSP) Partner Onboarding Agent - mounted at /agent5",
            "agent6": "AM Cross-Sell/Upsell Opportunity Creation Agent - mounted at /agent6",
            "agent7": "Sales Rep Performance & Coaching Trigger Agent - mounted at /agent7",
        },
    }
