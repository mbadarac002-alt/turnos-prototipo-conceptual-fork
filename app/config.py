"""Configuración transversal (constantes del spec)."""
import os
import re
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Se lee en cada conexión (`config.DB_PATH`), por eso los tests pueden cambiarla.
DB_PATH = Path(os.environ.get("TURNOS_DB", RAIZ / "turnos.db"))
FRONTEND_HTML = RAIZ / "prototipo-turnos.html"

CANCELLATION_WINDOW = timedelta(hours=2)   # RN-01
MIN_LEAD_TIME = timedelta(hours=1)         # RN-04 antelación mínima
MAX_HORIZON = timedelta(days=60)           # RN-04 horizonte máximo
SLOT_GRID_MIN = 15                         # RN-04 grilla de slots
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"           # UTC, ancho fijo: el orden de texto = orden temporal

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
