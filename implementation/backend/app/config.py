import os
from pathlib import Path

DATA_DIR = Path(os.getenv('DATA_DIR', './data')).resolve()
DB_PATH = DATA_DIR / 'kuku.sqlite3'
MODEL = os.getenv('LLM_MODEL', 'gemini-3.1-flash-lite')
BASE_URL = os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
API_KEY = os.getenv('LLM_API_KEY', '')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 200
PROMO_MIN_SECONDS = 20
PROMO_MAX_SECONDS = 60
