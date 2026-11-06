"""Conexiones y transacciones SQLite."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app import config


def connect() -> sqlite3.Connection:
    """Abre una conexión nueva a `config.DB_PATH` (se lee en cada llamada, por eso los tests pueden cambiarla)."""
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)  # transacciones manuales
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def write_tx() -> Iterator[sqlite3.Connection]:
    """Transacción de escritura exclusiva: verificación + escritura atómicas (INV-03, RN-02)."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def read_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
