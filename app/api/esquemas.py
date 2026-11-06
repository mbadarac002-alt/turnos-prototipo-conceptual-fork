"""Esquemas de la API (Pydantic)."""
from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, StringConstraints


class Estado(str, Enum):
    """Ciclo de vida de un turno (RN-06). CANCELADO, COMPLETADO y AUSENTE son estados terminales."""

    CONFIRMADO = "CONFIRMADO"
    CANCELADO = "CANCELADO"
    COMPLETADO = "COMPLETADO"
    AUSENTE = "AUSENTE"


# Identificador de texto: se recortan los espacios y se rechaza el vacío ("" o "   " → 422 INVALID_REQUEST).
IdTexto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TurnoCreate(BaseModel):
    """Cuerpo de `POST /api/turnos`. El profesional y el `fin` los calcula el servidor."""

    cliente_id: IdTexto = Field(description="Id del cliente que reserva (rol CLIENTE, activo).", examples=["c1"])
    servicio_id: IdTexto = Field(description="Id del servicio a reservar; determina profesional y duración.", examples=["s1"])
    inicio: datetime = Field(
        description="Inicio del turno (ISO 8601; sin zona horaria se asume UTC). "
                    "Debe ser ≥ 1 h en el futuro, ≤ 60 días y múltiplo de 15 min (RN-04).",
        examples=["2026-11-10T14:30:00Z"],
    )


class CancelarIn(BaseModel):
    """Cuerpo de `POST /api/turnos/{id}/cancelar`."""

    cancelado_por_id: IdTexto = Field(description="Id del usuario que cancela (provisorio hasta tener login, D-06).", examples=["c1"])
    motivo_cancelacion: Optional[str] = Field(
        default=None,
        description="Motivo de la cancelación. Obligatorio si cancela un PROFESIONAL o ADMIN (RN-01).",
        examples=["El profesional no puede atender ese día."],
    )


class TurnoOut(BaseModel):
    """Turno tal como se guarda en la base (fechas en UTC, formato `YYYY-MM-DDTHH:MM:SSZ`)."""

    id: str
    cliente_id: str
    profesional_id: str
    servicio_id: str
    inicio: str
    fin: str
    estado: Estado
    motivo_cancelacion: Optional[str]
    cancelado_por_id: Optional[str]
    creado_en: str
    actualizado_en: str


class ErrorOut(BaseModel):
    """Cuerpo de toda respuesta de error (catálogo spec §7)."""

    error: str = Field(description="Código de error del catálogo, p. ej. `SLOT_UNAVAILABLE`.")
    detalle: str = Field(description="Explicación legible para mostrar al usuario.")


def fila_a_turno_out(fila: dict) -> TurnoOut:
    """Convierte un turno de la capa de negocio en el esquema de salida."""
    return TurnoOut(**{k: fila[k] for k in TurnoOut.model_fields})
