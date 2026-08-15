import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")

DOMO_API_KEY = os.getenv("DOMO_API_KEY", "")
DOMO_BASE_URL = os.getenv("DOMO_BASE_URL", "").rstrip("/")
DOMO_MODEL = os.getenv("DOMO_MODEL", "")

# Gmail SMTP (App Password, not OAuth) for the "escalate to email" action.
# Optional - if unset, POST /deals/{id}/escalate-email returns 503 instead
# of failing the whole app at import time.
GMAIL_SENDER_ADDRESS = os.getenv("GMAIL_SENDER_ADDRESS") or None
GMAIL_APP_PASSWORD = (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "") or None
