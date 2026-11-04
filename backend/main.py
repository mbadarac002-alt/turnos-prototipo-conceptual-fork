"""Backend de turnos (Fase 2) — contrato en spec.md §11 v0.3.0.

Capa 2 (FastAPI: reglas INV-01 e INV-02) y capa 3 (SQLite: turnos.db) en un único módulo.
Levantar con:  uvicorn main:app --reload   (desde la carpeta backend/)
"""
import os
import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Final, Literal

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, StringConstraints

# --------------------------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------------------------
DB_PATH: Path = Path(os.environ.get("TURNOS_DB", Path(__file__).resolve().parent.parent / "turnos.db"))
CANCELLATION_WINDOW: Final[timedelta] = timedelta(hours=2)  # INV-01
FORMATO_UTC: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
EMAIL_PATTERN: Final[str] = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # RN-03, RFC 5322 simplificado

Estado = Literal["CONFIRMADO", "CANCELADO_CLIENTE"]

# DDL de spec §11.7. El índice único parcial es lo que garantiza INV-02 ante concurrencia.
DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS turnos (
    id             TEXT PRIMARY KEY,
    cliente_nombre TEXT NOT NULL,
    cliente_email  TEXT NOT NULL,
    servicio       TEXT NOT NULL,
    fecha_hora     TEXT NOT NULL,
    estado         TEXT NOT NULL CHECK (estado IN ('CONFIRMADO', 'CANCELADO_CLIENTE'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_turnos_slot_confirmado
    ON turnos (fecha_hora) WHERE estado = 'CONFIRMADO';
"""


def ahora() -> datetime:
    """Reloj del servidor en UTC. Único punto de lectura de la hora: los tests lo reemplazan."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------------------------
# Modelos (campos exactos de spec §11.2)
# --------------------------------------------------------------------------------------------
class TurnoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # el cliente no envía id ni estado

    cliente_nombre: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
    cliente_email: Annotated[
        str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=EMAIL_PATTERN)
    ]
    servicio: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    fecha_hora: str


class TurnoOut(BaseModel):
    id: str
    cliente_nombre: str
    cliente_email: str
    servicio: str
    fecha_hora: str
    estado: Estado


def _a_turno(row: sqlite3.Row) -> TurnoOut:
    return TurnoOut(
        id=str(row["id"]),
        cliente_nombre=str(row["cliente_nombre"]),
        cliente_email=str(row["cliente_email"]),
        servicio=str(row["servicio"]),
        fecha_hora=str(row["fecha_hora"]),
        estado="CONFIRMADO" if row["estado"] == "CONFIRMADO" else "CANCELADO_CLIENTE",
    )


def _error(status: int, code: str, message: str) -> HTTPException:
    """Error de dominio con el formato de spec §11.1: {"detail": {"code", "message"}}."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _parsear_fecha(texto: str) -> datetime:
    """ISO 8601 con zona horaria -> UTC. Cualquier otra cosa es FECHA_INVALIDA (RN-04)."""
    try:
        fecha = datetime.fromisoformat(texto.strip())
    except ValueError:
        raise _error(422, "FECHA_INVALIDA", "fecha_hora debe ser ISO 8601, por ejemplo 2026-11-04T13:00:00Z.") from None
    if fecha.tzinfo is None:
        raise _error(422, "FECHA_INVALIDA", "fecha_hora debe incluir zona horaria (Z o un offset).")
    return fecha.astimezone(timezone.utc).replace(microsecond=0)


# --------------------------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------------------------
def init_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db(DB_PATH)  # crea la tabla `turnos` si no existe
    yield


# --------------------------------------------------------------------------------------------
# Aplicación
# --------------------------------------------------------------------------------------------
app = FastAPI(title="API de Turnos", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/turnos", response_model=list[TurnoOut])
def listar_turnos(db: Db) -> list[TurnoOut]:
    """Todos los turnos, de cualquier estado, ordenados por fecha_hora."""
    rows = db.execute("SELECT * FROM turnos ORDER BY fecha_hora ASC, id ASC").fetchall()
    return [_a_turno(r) for r in rows]


@app.post(
    "/api/turnos",
    status_code=201,
    response_model=TurnoOut,
    responses={409: {"description": "HORARIO_NO_DISPONIBLE (INV-02)"}, 422: {"description": "FECHA_INVALIDA o datos inválidos"}},
)
def crear_turno(datos: TurnoIn, response: Response, db: Db) -> TurnoOut:
    fecha = _parsear_fecha(datos.fecha_hora)
    if fecha <= ahora():
        raise _error(422, "FECHA_INVALIDA", "fecha_hora debe ser estrictamente futura.")

    turno_id = str(uuid.uuid4())
    try:
        with db:  # una sola sentencia atómica: confirma o revierte (INV-03)
            db.execute(
                "INSERT INTO turnos (id, cliente_nombre, cliente_email, servicio, fecha_hora, estado)"
                " VALUES (?, ?, ?, ?, ?, 'CONFIRMADO')",
                (turno_id, datos.cliente_nombre, datos.cliente_email, datos.servicio, fecha.strftime(FORMATO_UTC)),
            )
    except sqlite3.IntegrityError as e:
        # INV-02: el índice único parcial rechaza un segundo CONFIRMADO en el mismo horario,
        # incluso si dos solicitudes llegan a la vez.
        if "UNIQUE" in str(e):
            raise _error(409, "HORARIO_NO_DISPONIBLE", "Ya existe un turno confirmado en ese horario.") from None
        raise

    row = db.execute("SELECT * FROM turnos WHERE id = ?", (turno_id,)).fetchone()
    response.headers["Location"] = f"/api/turnos/{turno_id}"
    return _a_turno(row)


@app.post(
    "/api/turnos/{turno_id}/cancelar",
    response_model=TurnoOut,
    responses={
        404: {"description": "TURNO_NO_ENCONTRADO"},
        409: {"description": "CANCELACION_FUERA_DE_VENTANA (INV-01) o TURNO_NO_CANCELABLE"},
    },
)
def cancelar_turno(turno_id: str, db: Db) -> TurnoOut:
    row = db.execute("SELECT * FROM turnos WHERE id = ?", (turno_id,)).fetchone()
    if row is None:
        raise _error(404, "TURNO_NO_ENCONTRADO", "No existe un turno con ese id.")
    if row["estado"] != "CONFIRMADO":
        raise _error(409, "TURNO_NO_CANCELABLE", "El turno ya no está confirmado.")

    # INV-01: con menos de 2 h hasta el inicio no se puede cancelar; con 2 h exactas sí.
    inicio = datetime.strptime(str(row["fecha_hora"]), FORMATO_UTC).replace(tzinfo=timezone.utc)
    if inicio - ahora() < CANCELLATION_WINDOW:
        raise _error(409, "CANCELACION_FUERA_DE_VENTANA", "Solo se puede cancelar con al menos 2 horas de anticipación.")

    with db:
        cur = db.execute("UPDATE turnos SET estado = 'CANCELADO_CLIENTE' WHERE id = ? AND estado = 'CONFIRMADO'", (turno_id,))
    if cur.rowcount == 0:  # otra solicitud lo canceló entre la lectura y la escritura
        raise _error(409, "TURNO_NO_CANCELABLE", "El turno ya no está confirmado.")

    actualizado = db.execute("SELECT * FROM turnos WHERE id = ?", (turno_id,)).fetchone()
    return _a_turno(actualizado)
