"""Configuracion central del respaldo C90."""
import os
from pathlib import Path

# --- Cuenta de archive.org ---
UPLOADER = "cumbianoventera@gmail.com"
ACCOUNT = "@cumbia_noventera"

# --- Telegram (rellenar en .env) ---
API_ID = int(os.environ.get("TG_API_ID", "0") or 0)
API_HASH = os.environ.get("TG_API_HASH", "")
CHANNEL_NAME = "C90"
SESSION_NAME = "c90_session"

# --- Rutas ---
ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = ROOT / "work"          # descargas temporales
STATE_DB = ROOT / "state.sqlite"  # progreso reanudable
LOG_FILE = ROOT / "c90.log"

# --- Comportamiento ---
# Telethon sube hasta 2GB (4GB con Premium). Partimos por debajo por seguridad.
SPLIT_SIZE = 1900 * 1024 * 1024
# Los .mp3/.png/_spectrogram.png son derivados regenerables por archive.org.
# True = ZIP solo con archivos "original" (mucho mas liviano).
ORIGINALS_ONLY = os.environ.get("C90_ORIGINALS_ONLY", "0") == "1"
# Borrar del disco tras subir con exito.
CLEANUP = os.environ.get("C90_CLEANUP", "1") == "1"
DOWNLOAD_TIMEOUT = 1800
MAX_RETRIES = 4
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
