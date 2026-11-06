"""Utilidades de tiempo UTC."""
from datetime import datetime, timezone

from app.config import TS_FORMAT


def utcnow() -> datetime:
    """Hora actual en UTC. Único punto de lectura del reloj: los tests lo reemplazan para simular el tiempo."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Normaliza a UTC sin microsegundos; un datetime sin zona horaria se asume UTC."""
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).replace(microsecond=0)


def fmt(dt: datetime) -> str:
    """datetime → texto UTC de ancho fijo (`TS_FORMAT`), tal como se guarda en la base."""
    return to_utc(dt).strftime(TS_FORMAT)


def parse(ts: str) -> datetime:
    """Texto UTC de la base (`TS_FORMAT`) → datetime con zona horaria."""
    return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)
