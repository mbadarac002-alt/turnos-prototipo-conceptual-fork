"""Reglas puras del dominio (sin I/O): INV-01, INV-02, RN-03, RN-04. Ver spec §3."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CANCELLATION_WINDOW_HOURS = 2     # RN-01
MIN_LEAD_HOURS = 1                # RN-04, antelación mínima
HORIZON_DAYS = 60                 # RN-04, horizonte máximo
GRID_MIN = 15                     # RN-04, grilla de slots
FMT = "%Y-%m-%dT%H:%M:%SZ"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def parse_utc(texto) -> datetime | None:
    """ISO 8601 UTC con sufijo Z (formato del contrato §11.1). None si es inválido."""
    if not isinstance(texto, str):
        return None
    try:
        return datetime.strptime(texto, FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(FMT)


def solapan(a_ini: datetime, a_fin: datetime, b_ini: datetime, b_fin: datetime) -> bool:
    """RN-02: intervalos semiabiertos [inicio, fin); los contiguos no se solapan."""
    return a_ini < b_fin and b_ini < a_fin


def contacto_valido(usuario) -> bool:
    """RN-03: nombre 2–100, email válido y teléfono E.164 (datos ya normalizados al guardarse)."""
    nombre = (usuario["nombre_completo"] or "").strip()
    return (
        2 <= len(nombre) <= 100
        and bool(_EMAIL.match(usuario["email"] or ""))
        and bool(_E164.match(usuario["telefono"] or ""))
    )


def inicio_valido(inicio: datetime, ahora: datetime) -> bool:
    """RN-04: alineado a la grilla, con antelación mínima y dentro del horizonte."""
    alineado = inicio.second == 0 and inicio.minute % GRID_MIN == 0
    return (
        alineado
        and inicio >= ahora + timedelta(hours=MIN_LEAD_HOURS)
        and inicio <= ahora + timedelta(days=HORIZON_DAYS)
    )


def cliente_puede_cancelar(inicio: datetime, ahora: datetime) -> bool:
    """INV-01: bloqueado si faltan menos de 2 h. Con exactamente 2 h todavía se permite."""
    return inicio - ahora >= timedelta(hours=CANCELLATION_WINDOW_HOURS)


def dentro_de_horario(inicio: datetime, fin: datetime, franjas, tz: ZoneInfo) -> bool:
    """RN-02: [inicio, fin) debe caber en una franja de HorarioLaboral del mismo día local."""
    li, lf = inicio.astimezone(tz), fin.astimezone(tz)
    if li.date() != lf.date():
        return False
    ini, fi = li.strftime("%H:%M"), lf.strftime("%H:%M")
    return any(f["dia_semana"] == li.weekday() and f["hora_inicio"] <= ini and fi <= f["hora_fin"] for f in franjas)
