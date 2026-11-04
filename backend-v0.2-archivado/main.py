"""API REST de spec §11: GET /api/turnos, POST /api/turnos, POST /api/turnos/{id}/cancelar."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import dominio
from db import connect, init_db, transaction

DEFAULT_DB = Path(__file__).resolve().parent.parent / "turnos.db"
OPERATION_TZ = os.environ.get("TURNOS_TZ", "America/Argentina/Buenos_Aires")

# Catálogo de errores (spec §7).
HTTP = {
    "SLOT_UNAVAILABLE": 409, "CANCELLATION_WINDOW_EXPIRED": 409, "INVALID_CONTACT": 422,
    "EMAIL_NOT_VERIFIED": 403, "INVALID_TIME_RANGE": 422, "INVALID_STATE_TRANSITION": 409,
    "SERVICE_UNAVAILABLE": 409, "FORBIDDEN": 403, "NOT_FOUND": 404, "REASON_REQUIRED": 422,
}


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code, self.message, self.details = code, message, details


class CrearTurno(BaseModel):
    cliente_id: str | None = None
    servicio_id: str | None = None
    inicio: str | None = None


class CancelarTurno(BaseModel):
    cancelado_por_id: str | None = None
    motivo_cancelacion: str | None = None


def _error(code: str, message: str, details: dict | None = None, status: int | None = None):
    body = {"code": code, "message": message}
    if details:
        body["details"] = details
    return JSONResponse(status_code=status or HTTP[code], content={"error": body})


def _turno(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in (
        "id", "cliente_id", "profesional_id", "servicio_id", "inicio", "fin", "estado",
        "motivo_cancelacion", "cancelado_por_id", "creado_en", "actualizado_en")}


def _auditar(conn, accion, turno_id, actor, ahora, detalle):
    conn.execute(
        "INSERT INTO auditoria_evento (id, entidad, entidad_id, accion, actor_id, rol, ocurrido_en, detalle)"
        " VALUES (?, 'turno', ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), turno_id, accion, actor["id"], actor["rol"], dominio.fmt_utc(ahora), json.dumps(detalle)))


def create_app(db_path=DEFAULT_DB, now_fn=None) -> FastAPI:
    """`now_fn` permite inyectar el reloj solo en tests (plan §14, riesgo abierto)."""
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    tz = ZoneInfo(OPERATION_TZ)
    init_db(db_path)

    app = FastAPI(title="Turnos API", version="0.2.0")
    origins = [o.strip() for o in os.environ.get("TURNOS_CORS_ORIGINS", "*").split(",")]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DomainError)
    async def _domain(_: Request, e: DomainError):
        return _error(e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        # Cuerpo que no es un objeto JSON válido. El catálogo §7 no tiene código genérico (ver informe).
        return _error("VALIDATION_ERROR", "El cuerpo de la solicitud no es válido.", status=422)

    def abrir():
        return connect(db_path)

    @app.get("/api/turnos")
    def listar():
        conn = abrir()
        try:
            rows = conn.execute("SELECT * FROM turno ORDER BY inicio ASC, id ASC").fetchall()
            return [_turno(r) for r in rows]
        finally:
            conn.close()

    @app.post("/api/turnos", status_code=201)
    def crear(body: CrearTurno):
        ahora = now_fn()
        conn = abrir()
        try:
            cliente = _buscar(conn, "usuario", body.cliente_id)
            servicio = _buscar(conn, "servicio", body.servicio_id)
            if cliente is None or servicio is None:
                raise DomainError("NOT_FOUND", "Cliente o servicio inexistente.")
            if cliente["rol"] != "CLIENTE" or cliente["id"] == servicio["profesional_id"]:
                raise DomainError("FORBIDDEN", "El usuario informado no puede reservar turnos.")
            if not servicio["activo"]:
                raise DomainError("SERVICE_UNAVAILABLE", "El servicio no admite nuevas reservas.")
            if not dominio.contacto_valido(cliente):
                raise DomainError("INVALID_CONTACT", "Los datos de contacto del cliente faltan o son inválidos.")
            if not cliente["email_verificado"]:
                raise DomainError("EMAIL_NOT_VERIFIED", "El email del cliente no está verificado.")

            inicio = dominio.parse_utc(body.inicio)
            if inicio is None or not dominio.inicio_valido(inicio, ahora):
                raise DomainError("INVALID_TIME_RANGE", "El inicio no respeta la grilla, la antelación o el horizonte.")
            fin = inicio + timedelta(minutes=servicio["duracion_min"])
            ini_s, fin_s, ahora_s = dominio.fmt_utc(inicio), dominio.fmt_utc(fin), dominio.fmt_utc(ahora)
            prof_id = servicio["profesional_id"]
            turno_id = str(uuid.uuid4())

            try:
                with transaction(conn):  # INV-03: turno + auditoría en una sola transacción
                    franjas = conn.execute(
                        "SELECT dia_semana, hora_inicio, hora_fin FROM horario_laboral WHERE profesional_id = ?",
                        (prof_id,)).fetchall()
                    if not dominio.dentro_de_horario(inicio, fin, franjas, tz):
                        raise DomainError("SLOT_UNAVAILABLE", "El horario está fuera de la jornada del profesional.")
                    if conn.execute(
                            "SELECT 1 FROM bloqueo WHERE profesional_id = ? AND inicio < ? AND ? < fin",
                            (prof_id, fin_s, ini_s)).fetchone():
                        raise DomainError("SLOT_UNAVAILABLE", "El profesional bloqueó ese horario.")
                    if conn.execute(
                            "SELECT 1 FROM turno WHERE cliente_id = ? AND estado = 'CONFIRMADO'"
                            " AND inicio < ? AND ? < fin", (cliente["id"], fin_s, ini_s)).fetchone():
                        raise DomainError("SLOT_UNAVAILABLE", "El cliente ya tiene un turno en ese horario.")
                    # El solapamiento del profesional lo aborta el trigger de la base (INV-02).
                    conn.execute(
                        "INSERT INTO turno (id, cliente_id, profesional_id, servicio_id, inicio, fin, estado,"
                        " creado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, 'CONFIRMADO', ?, ?)",
                        (turno_id, cliente["id"], prof_id, servicio["id"], ini_s, fin_s, ahora_s, ahora_s))
                    _auditar(conn, "CREAR_TURNO", turno_id, cliente, ahora,
                             {"servicio_id": servicio["id"], "inicio": ini_s, "fin": fin_s})
                    row = conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()
            except sqlite3.IntegrityError as e:
                if "SLOT_UNAVAILABLE" in str(e):
                    raise DomainError("SLOT_UNAVAILABLE", "El horario ya está ocupado.") from None
                raise
            return JSONResponse(status_code=201, content=_turno(row), headers={"Location": f"/api/turnos/{turno_id}"})
        finally:
            conn.close()

    @app.post("/api/turnos/{turno_id}/cancelar")
    def cancelar(turno_id: str, body: CancelarTurno):
        ahora = now_fn()
        conn = abrir()
        try:
            with transaction(conn):
                actor = _buscar(conn, "usuario", body.cancelado_por_id)
                turno = _buscar(conn, "turno", turno_id)
                # RBAC-02: un recurso ajeno responde 404, nunca 403.
                if actor is None or turno is None or not _es_visible(actor, turno):
                    raise DomainError("NOT_FOUND", "El turno no existe.")
                motivo = (body.motivo_cancelacion or "").strip() or None
                if actor["rol"] != "CLIENTE" and motivo is None:
                    raise DomainError("REASON_REQUIRED", "El motivo de cancelación es obligatorio.")
                inicio = dominio.parse_utc(turno["inicio"])
                if turno["estado"] != "CONFIRMADO" or ahora >= inicio:
                    raise DomainError("INVALID_STATE_TRANSITION", "El turno no se puede cancelar en su estado actual.")
                if actor["rol"] == "CLIENTE" and not dominio.cliente_puede_cancelar(inicio, ahora):
                    raise DomainError("CANCELLATION_WINDOW_EXPIRED",
                                      f"Solo se puede cancelar con {dominio.CANCELLATION_WINDOW_HOURS} h de anticipación.")
                ahora_s = dominio.fmt_utc(ahora)
                conn.execute(
                    "UPDATE turno SET estado = 'CANCELADO', motivo_cancelacion = ?, cancelado_por_id = ?,"
                    " actualizado_en = ? WHERE id = ?", (motivo, actor["id"], ahora_s, turno_id))
                _auditar(conn, "CANCELAR_TURNO", turno_id, actor, ahora, {"motivo_cancelacion": motivo})
                row = conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)).fetchone()
            return _turno(row)
        finally:
            conn.close()

    return app


def _buscar(conn, tabla: str, id_):
    if not isinstance(id_, str):
        return None
    return conn.execute(f"SELECT * FROM {tabla} WHERE id = ?", (id_,)).fetchone()  # tabla es constante interna


def _es_visible(actor, turno) -> bool:
    if actor["rol"] == "ADMIN":
        return True
    if actor["rol"] == "PROFESIONAL":
        return turno["profesional_id"] == actor["id"]
    return turno["cliente_id"] == actor["id"]


app = create_app() if os.environ.get("TURNOS_NO_AUTOAPP") != "1" else None
