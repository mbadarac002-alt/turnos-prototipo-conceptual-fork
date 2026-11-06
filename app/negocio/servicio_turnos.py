"""Casos de uso de turnos: orquestan reglas de negocio y repositorio dentro de una transacción."""
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app import tiempo
from app.config import CANCELLATION_WINDOW
from app.datos import repositorio
from app.datos.conexion import read_conn, write_tx
from app.errores import DomainError, not_found, slot_unavailable
from app.negocio.reglas import validar_contacto, validar_horario


def listar_turnos(cliente_id: Optional[str], profesional_id: Optional[str], estado: Optional[str]) -> list[dict]:
    """Turnos ordenados por `inicio`. Se leen siempre de la base (INV-03), nunca de una caché."""
    with read_conn() as conn:
        return repositorio.listar_turnos(conn, cliente_id, profesional_id, estado)


def _verificar_sin_solapamiento(conn, column: str, owner_id: str, inicio: str, fin: str) -> None:
    """INV-02: sin solapamiento de [inicio, fin) entre turnos CONFIRMADO (contiguos son válidos)."""
    if repositorio.existe_solape_confirmado(conn, column, owner_id, inicio, fin):
        who = "El profesional" if column == "profesional_id" else "El cliente"
        raise slot_unavailable(f"{who} ya tiene un turno confirmado que se solapa con ese horario.")


def crear_turno(cliente_id: str, servicio_id: str, inicio: datetime) -> dict:
    """Valida y crea un turno CONFIRMADO en una única transacción exclusiva (INV-03).

    Orden de validación: existencia (404) → contacto (RN-03) → horario (RN-04) → solapamiento (INV-02).
    """
    now = tiempo.utcnow()
    with write_tx() as conn:
        cliente = repositorio.obtener_cliente_activo(conn, cliente_id)
        servicio = repositorio.obtener_servicio_activo(conn, servicio_id)
        if cliente is None:
            raise not_found("Cliente inexistente.")
        if servicio is None:
            raise not_found("Servicio inexistente o inactivo.")
        validar_contacto(cliente)
        inicio_dt = tiempo.to_utc(inicio)
        validar_horario(inicio_dt, now)
        ini, fin = tiempo.fmt(inicio_dt), tiempo.fmt(inicio_dt + timedelta(minutes=servicio["duracion_min"]))
        _verificar_sin_solapamiento(conn, "profesional_id", servicio["profesional_id"], ini, fin)
        _verificar_sin_solapamiento(conn, "cliente_id", cliente["id"], ini, fin)
        return repositorio.insertar_turno_confirmado(
            conn, str(uuid.uuid4()), cliente["id"], servicio["profesional_id"], servicio["id"], ini, fin, tiempo.fmt(now)
        )


def cancelar_turno(turno_id: str, cancelado_por_id: str, motivo_cancelacion: Optional[str]) -> dict:
    """Cancela un turno CONFIRMADO en una única transacción exclusiva (INV-03).

    Orden de validación: existencia y pertenencia (404) → estado terminal (409, RN-06)
    → ventana de 2 h solo para CLIENTE (409, INV-01) o motivo obligatorio para PROFESIONAL/ADMIN (422).
    """
    now = tiempo.utcnow()
    with write_tx() as conn:
        turno = repositorio.obtener_turno(conn, turno_id)
        actor = repositorio.obtener_usuario_activo(conn, cancelado_por_id)
        if turno is None or actor is None:
            raise not_found("Turno inexistente.")
        # RBAC-02: un recurso ajeno responde 404, no 403.
        if actor["rol"] == "CLIENTE" and turno["cliente_id"] != actor["id"]:
            raise not_found("Turno inexistente.")
        if actor["rol"] == "PROFESIONAL" and turno["profesional_id"] != actor["id"]:
            raise not_found("Turno inexistente.")
        if turno["estado"] != "CONFIRMADO":  # RN-06: estados terminales
            raise DomainError(409, "INVALID_STATE_TRANSITION", f"El turno está {turno['estado']} y no puede cancelarse.")
        motivo = (motivo_cancelacion or "").strip() or None
        if actor["rol"] == "CLIENTE":
            # INV-01: el cliente no cancela con menos de 2 h (exactamente 2 h sí se permite).
            if tiempo.parse(turno["inicio"]) - now < CANCELLATION_WINDOW:
                raise DomainError(409, "CANCELLATION_WINDOW_EXPIRED",
                                  "Solo se puede cancelar hasta 2 horas antes del inicio del turno.")
        elif motivo is None:
            raise DomainError(422, "INVALID_REQUEST", "El motivo de cancelación es obligatorio para Profesional/Administrador.")
        return repositorio.marcar_turno_cancelado(conn, turno_id, motivo, actor["id"], tiempo.fmt(now))
