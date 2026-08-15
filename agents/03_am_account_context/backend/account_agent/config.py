import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")

DOMO_API_KEY = os.getenv("DOMO_API_KEY", "")
DOMO_BASE_URL = os.getenv("DOMO_BASE_URL", "").rstrip("/")
DOMO_MODEL = os.getenv("DOMO_MODEL", "")

# Domo's AI Gateway (as used in this project) only does text generation, not
# speech-to-text - so voice-to-text on Screen 2 still uses Groq Whisper.
GROQ_API_KEYS = [
    os.getenv(name) for name in ("GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3")
    if os.getenv(name)
]
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
