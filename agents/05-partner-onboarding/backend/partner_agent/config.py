import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")

DOMO_API_KEY = os.getenv("DOMO_API_KEY", "")
DOMO_BASE_URL = os.getenv("DOMO_BASE_URL", "").rstrip("/")
DOMO_MODEL = os.getenv("DOMO_MODEL", "")

DATA_DIR = BASE_DIR / "data"
APPLICATIONS_CSV = DATA_DIR / "applications.csv"
PROGRAM_CRITERIA_CSV = DATA_DIR / "program_criteria.csv"
CHANNEL_CONFLICTS_CSV = DATA_DIR / "channel_conflicts.csv"
