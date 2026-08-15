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
REPS_CSV = DATA_DIR / "reps.csv"
TARGETS_CSV = DATA_DIR / "targets.csv"
PERFORMANCE_HISTORY_CSV = DATA_DIR / "performance_history.csv"
COACHING_TASKS_CSV = DATA_DIR / "coaching_tasks.csv"
RECOGNITION_NOMINATIONS_CSV = DATA_DIR / "recognition_nominations.csv"
