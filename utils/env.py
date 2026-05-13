import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Desktop/ghostfix
ENV_PATH = PROJECT_ROOT / ".env"

if load_dotenv is not None and ENV_PATH.exists():
    load_dotenv(ENV_PATH)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
