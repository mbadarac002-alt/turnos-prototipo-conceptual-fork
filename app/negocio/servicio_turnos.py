"""Casos de uso de turnos: orquestan reglas de negocio y repositorio dentro de una transacción.

Cada caso de uso (`listar_turnos`, `crear_turno`, `cancelar_turno`) es el único punto de entrada
que usa la capa de presentación (`app/api/rutas.py`). Las reglas puras viven en `reglas.py` y el
acceso a SQLite en `app/datos/repositorio.py`.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app import tiempo
from app.config import CANCELLATION_WINDOW
from app.datos import repositorio
from app.datos.conexion import read_conn, write_tx
from app.errores import DomainError, not_found, slot_unavailable
from app.negocio.reglas import validar_contacto, validar_horario


# --- Listado -----------------------------------------------------------------
def listar_turnos(cliente_id: Optional[str], profesional_id: Optional[str], estado: Optional[str]) -> list[dict]:
    """Devuelve los turnos ordenados por `inicio`, con filtros opcionales combinados con AND.

    Se leen siempre de la base (INV-03), nunca de una caché en memoria.
    """
    with read_conn() as conn:
        return repositorio.listar_turnos(conn, cliente_id, profesional_id, estado)


# --- Creación ----------------------------------------------------------------
def _verificar_sin_solapamiento(conn, columna: str, id_propietario: str, inicio: str, fin: str) -> None:
    """INV-02: sin solapamiento de [inicio, fin) entre turnos CONFIRMADO (los contiguos son válidos).

    `columna` indica a quién se le comprueba la agenda: `profesional_id` o `cliente_id`.
    """
    if repositorio.existe_solape_confirmado(conn, columna, id_propietario, inicio, fin):
        quien = "El profesional" if columna == "profesional_id" else "El cliente"
        raise slot_unavailable(f"{quien} ya tiene un turno confirmado que se solapa con ese horario.")


def crear_turno(cliente_id: str, servicio_id: str, inicio: datetime) -> dict:
    """Valida y crea un turno CONFIRMADO en una única transacción exclusiva (INV-03).

    El profesional y el `fin` se derivan del servicio. Orden de validación:
    existencia (404) → contacto (RN-03) → horario (RN-04) → solapamiento (INV-02).
    """
    ahora = tiempo.utcnow()
    with write_tx() as conn:
        cliente = repositorio.obtener_cliente_activo(conn, cliente_id)
        servicio = repositorio.obtener_servicio_activo(conn, servicio_id)
        if cliente is None:
            raise not_found("Cliente inexistente.")
        if servicio is None:
            raise not_found("Servicio inexistente o inactivo.")

        validar_contacto(cliente)
        inicio_utc = tiempo.to_utc(inicio)
        validar_horario(inicio_utc, ahora)

        inicio_txt = tiempo.fmt(inicio_utc)
        fin_txt = tiempo.fmt(inicio_utc + timedelta(minutes=servicio["duracion_min"]))
        _verificar_sin_solapamiento(conn, "profesional_id", servicio["profesional_id"], inicio_txt, fin_txt)
        _verificar_sin_solapamiento(conn, "cliente_id", cliente["id"], inicio_txt, fin_txt)

        return repositorio.insertar_turno_confirmado(
            conn, str(uuid.uuid4()), cliente["id"], servicio["profesional_id"], servicio["id"],
            inicio_txt, fin_txt, tiempo.fmt(ahora),
        )


# --- Cancelación -------------------------------------------------------------
def _es_turno_ajeno(turno: dict, actor: dict) -> bool:
    """RBAC-02: un CLIENTE solo ve sus turnos y un PROFESIONAL solo los suyos; el ADMIN ve todos."""
    if actor["rol"] == "CLIENTE":
        return turno["cliente_id"] != actor["id"]
    if actor["rol"] == "PROFESIONAL":
        return turno["profesional_id"] != actor["id"]
    return False


def _verificar_puede_cancelar(turno: dict, actor: dict, motivo: Optional[str], ahora: datetime) -> None:
    """Aplica RN-06 (estado), INV-01 (ventana de 2 h del cliente) y el motivo obligatorio del personal."""
    if turno["estado"] != "CONFIRMADO":  # RN-06: CANCELADO, COMPLETADO y AUSENTE son terminales
        raise DomainError(409, "INVALID_STATE_TRANSITION", f"El turno está {turno['estado']} y no puede cancelarse.")

    if actor["rol"] == "CLIENTE":
        # INV-01: el cliente no cancela con menos de 2 h (exactamente 2 h sí se permite).
        if tiempo.parse(turno["inicio"]) - ahora < CANCELLATION_WINDOW:
            raise DomainError(409, "CANCELLATION_WINDOW_EXPIRED",
                              "Solo se puede cancelar hasta 2 horas antes del inicio del turno.")
    elif motivo is None:
        raise DomainError(422, "INVALID_REQUEST", "El motivo de cancelación es obligatorio para Profesional/Administrador.")


def cancelar_turno(turno_id: str, cancelado_por_id: str, motivo_cancelacion: Optional[str]) -> dict:
    """Cancela un turno CONFIRMADO en una única transacción exclusiva (INV-03).

    El turno nunca se elimina físicamente (RN-06). Orden de validación:
    existencia y pertenencia (404) → estado terminal (409) → ventana de 2 h solo para CLIENTE (409)
    o motivo obligatorio para PROFESIONAL/ADMIN (422).
    """
    ahora = tiempo.utcnow()
    with write_tx() as conn:
        turno = repositorio.obtener_turno(conn, turno_id)
        actor = repositorio.obtener_usuario_activo(conn, cancelado_por_id)
        if turno is None or actor is None or _es_turno_ajeno(turno, actor):
            raise not_found("Turno inexistente.")  # un recurso ajeno responde 404, no 403 (RBAC-02)

        motivo = (motivo_cancelacion or "").strip() or None
        _verificar_puede_cancelar(turno, actor, motivo, ahora)
        return repositorio.marcar_turno_cancelado(conn, turno_id, motivo, actor["id"], tiempo.fmt(ahora))
