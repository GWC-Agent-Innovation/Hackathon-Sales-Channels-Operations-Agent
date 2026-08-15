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
OPPORTUNITIES_CSV = DATA_DIR / "opportunities.csv"
ACTIVITIES_CSV = DATA_DIR / "activities.csv"
PRODUCT_CATALOG_CSV = DATA_DIR / "product_catalog.csv"
HISTORICAL_PATTERNS_CSV = DATA_DIR / "historical_patterns.csv"
