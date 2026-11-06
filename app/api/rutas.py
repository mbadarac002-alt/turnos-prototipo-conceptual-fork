"""Endpoints REST de turnos (contrato spec §11). Solo traducen HTTP ↔ capa de negocio."""
from typing import Optional

from fastapi import APIRouter, Path as RutaParam, Query
from fastapi.responses import FileResponse

from app import config
from app.api.esquemas import CancelarIn, ErrorOut, Estado, TurnoCreate, TurnoOut, fila_a_turno_out
from app.negocio import servicio_turnos

router = APIRouter()


@router.get("/", include_in_schema=False)
def servir_frontend() -> FileResponse:
    """Sirve la interfaz web (`prototipo-turnos.html`), que consume esta misma API."""
    return FileResponse(config.FRONTEND_HTML, media_type="text/html")


@router.get(
    "/api/turnos",
    response_model=list[TurnoOut],
    tags=["Turnos"],
    summary="Listar turnos",
    responses={422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: filtro con formato o valor inválido."}},
)
def listar_turnos(
    cliente_id: Optional[str] = Query(default=None, description="Solo los turnos de este cliente."),
    profesional_id: Optional[str] = Query(default=None, description="Solo los turnos de este profesional."),
    estado: Optional[Estado] = Query(default=None, description="Solo los turnos en este estado."),
) -> list[TurnoOut]:
    """Devuelve los turnos ordenados por `inicio`. Los filtros son opcionales y se combinan con AND.

    Los datos se leen siempre de la base (INV-03), nunca de una caché en memoria.
    """
    filas = servicio_turnos.listar_turnos(cliente_id, profesional_id, estado.value if estado else None)
    return [fila_a_turno_out(f) for f in filas]


@router.post(
    "/api/turnos",
    response_model=TurnoOut,
    status_code=201,
    tags=["Turnos"],
    summary="Crear una reserva",
    responses={
        403: {"model": ErrorOut, "description": "`EMAIL_NOT_VERIFIED`: el cliente no verificó su email (RN-03)."},
        404: {"model": ErrorOut, "description": "`NOT_FOUND`: cliente o servicio inexistente o inactivo."},
        409: {"model": ErrorOut, "description": "`SLOT_UNAVAILABLE`: se solapa con otro turno confirmado (INV-02)."},
        422: {"model": ErrorOut, "description": "`INVALID_REQUEST` (cuerpo mal formado o textos vacíos), "
                                                "`INVALID_TIME_RANGE` (RN-04) o `INVALID_CONTACT` (RN-03)."},
    },
)
def crear_turno(data: TurnoCreate) -> TurnoOut:
    """Crea un turno `CONFIRMADO` para el cliente y servicio indicados.

    El profesional y el `fin` se calculan a partir del servicio. La validación y la inserción
    ocurren en una única transacción exclusiva (INV-03), por lo que dos pedidos simultáneos
    por el mismo horario no pueden confirmarse ambos.
    """
    return fila_a_turno_out(servicio_turnos.crear_turno(data.cliente_id, data.servicio_id, data.inicio))


@router.post(
    "/api/turnos/{turno_id}/cancelar",
    response_model=TurnoOut,
    tags=["Turnos"],
    summary="Cancelar un turno",
    responses={
        404: {"model": ErrorOut, "description": "`NOT_FOUND`: el turno no existe o es de otro usuario (RBAC-02)."},
        409: {"model": ErrorOut, "description": "`CANCELLATION_WINDOW_EXPIRED` (faltan menos de 2 h, INV-01) "
                                                "o `INVALID_STATE_TRANSITION` (el turno ya no está `CONFIRMADO`, RN-06)."},
        422: {"model": ErrorOut, "description": "`INVALID_REQUEST`: cuerpo mal formado o motivo ausente "
                                                "cuando cancela un PROFESIONAL/ADMIN."},
    },
)
def cancelar_turno(data: CancelarIn, turno_id: str = RutaParam(description="Id del turno a cancelar.")) -> TurnoOut:
    """Pasa el turno a `CANCELADO`. El turno nunca se elimina físicamente (RN-06).

    Un `CLIENTE` solo puede cancelar sus propios turnos y con al menos 2 horas de anticipación
    (exactamente 2 h se permite). `PROFESIONAL` y `ADMIN` pueden cancelar fuera de esa ventana
    siempre que indiquen un motivo.
    """
    return fila_a_turno_out(servicio_turnos.cancelar_turno(turno_id, data.cancelado_por_id, data.motivo_cancelacion))
