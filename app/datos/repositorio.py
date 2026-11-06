"""Consultas SQL. La capa de negocio accede a la base solo a través de estas funciones.

Devuelven `dict` (no `sqlite3.Row`) para que las capas superiores no dependan de SQLite.
"""
import sqlite3
from typing import Optional

Fila = dict


def _uno(cursor: sqlite3.Cursor) -> Optional[Fila]:
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def obtener_cliente_activo(conn: sqlite3.Connection, cliente_id: str) -> Optional[Fila]:
    return _uno(conn.execute("SELECT * FROM usuario WHERE id = ? AND rol = 'CLIENTE' AND activo = 1", (cliente_id,)))


def obtener_usuario_activo(conn: sqlite3.Connection, usuario_id: str) -> Optional[Fila]:
    return _uno(conn.execute("SELECT * FROM usuario WHERE id = ? AND activo = 1", (usuario_id,)))


def obtener_servicio_activo(conn: sqlite3.Connection, servicio_id: str) -> Optional[Fila]:
    return _uno(conn.execute("SELECT * FROM servicio WHERE id = ? AND activo = 1", (servicio_id,)))


def obtener_turno(conn: sqlite3.Connection, turno_id: str) -> Optional[Fila]:
    return _uno(conn.execute("SELECT * FROM turno WHERE id = ?", (turno_id,)))


def existe_solape_confirmado(conn: sqlite3.Connection, column: str, owner_id: str, inicio: str, fin: str) -> bool:
    """¿Hay un turno CONFIRMADO de `owner_id` que se solape con [inicio, fin)? `column`: profesional_id o cliente_id."""
    if column not in ("profesional_id", "cliente_id"):
        raise ValueError(column)
    row = conn.execute(
        f"SELECT 1 FROM turno WHERE {column} = ? AND estado = 'CONFIRMADO' AND inicio < ? AND ? < fin LIMIT 1",
        (owner_id, fin, inicio),
    ).fetchone()
    return row is not None


def insertar_turno_confirmado(conn: sqlite3.Connection, turno_id: str, cliente_id: str, profesional_id: str,
                              servicio_id: str, inicio: str, fin: str, ts: str) -> Fila:
    conn.execute(
        "INSERT INTO turno (id, cliente_id, profesional_id, servicio_id, inicio, fin, estado, creado_en, actualizado_en)"
        " VALUES (?,?,?,?,?,?,'CONFIRMADO',?,?)",
        (turno_id, cliente_id, profesional_id, servicio_id, inicio, fin, ts, ts),
    )
    return obtener_turno(conn, turno_id)


def marcar_turno_cancelado(conn: sqlite3.Connection, turno_id: str, motivo: Optional[str], actor_id: str, ts: str) -> Fila:
    conn.execute(
        "UPDATE turno SET estado = 'CANCELADO', motivo_cancelacion = ?, cancelado_por_id = ?, actualizado_en = ? WHERE id = ?",
        (motivo, actor_id, ts, turno_id),
    )
    return obtener_turno(conn, turno_id)


def listar_turnos(conn: sqlite3.Connection, cliente_id: Optional[str], profesional_id: Optional[str],
                  estado: Optional[str]) -> list[Fila]:
    """Turnos ordenados por `inicio`; los filtros presentes se combinan con AND."""
    where, params = [], []
    for column, value in (("cliente_id", cliente_id), ("profesional_id", profesional_id), ("estado", estado)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    sql = "SELECT * FROM turno" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY inicio"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
