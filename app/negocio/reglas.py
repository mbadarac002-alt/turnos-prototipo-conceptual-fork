"""Reglas de validación puras (sin acceso a la base)."""
from datetime import datetime

from app.config import EMAIL_RE, MAX_HORIZON, MIN_LEAD_TIME, PHONE_E164_RE, SLOT_GRID_MIN
from app.errores import DomainError


def validar_contacto(user: dict) -> None:
    """RN-03: nombre, email, teléfono válidos y email verificado."""
    name = (user["nombre_completo"] or "").strip()
    if not (2 <= len(name) <= 100):
        raise DomainError(422, "INVALID_CONTACT", "El nombre completo debe tener entre 2 y 100 caracteres.")
    if not EMAIL_RE.match((user["email"] or "").strip().lower()):
        raise DomainError(422, "INVALID_CONTACT", "El email no es válido.")
    if not PHONE_E164_RE.match((user["telefono"] or "").strip()):
        raise DomainError(422, "INVALID_CONTACT", "El teléfono debe estar en formato E.164 (ej. +5491155550101).")
    if not user["email_verificado"]:
        raise DomainError(403, "EMAIL_NOT_VERIFIED", "Verificá tu email antes de reservar.")


def validar_horario(inicio: datetime, now: datetime) -> None:
    """RN-04: futuro con antelación mínima, grilla de 15 min y horizonte máximo."""
    if inicio < now + MIN_LEAD_TIME:
        raise DomainError(422, "INVALID_TIME_RANGE", "El turno debe comenzar con al menos 1 hora de antelación.")
    if inicio > now + MAX_HORIZON:
        raise DomainError(422, "INVALID_TIME_RANGE", "No se puede reservar con más de 60 días de anticipación.")
    if inicio.second != 0 or inicio.minute % SLOT_GRID_MIN != 0:
        raise DomainError(422, "INVALID_TIME_RANGE", f"El inicio debe estar alineado a la grilla de {SLOT_GRID_MIN} minutos.")
