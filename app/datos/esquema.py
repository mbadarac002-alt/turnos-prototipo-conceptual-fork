"""Esquema SQLite (idéntico a spec §4.1), semilla e inicialización de la base."""
from app import tiempo
from app.datos.conexion import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuario (
    id               TEXT PRIMARY KEY,
    email            TEXT NOT NULL UNIQUE,
    email_verificado INTEGER NOT NULL DEFAULT 0,
    password_hash    TEXT NOT NULL,
    nombre_completo  TEXT NOT NULL,
    telefono         TEXT NOT NULL,
    rol              TEXT NOT NULL CHECK (rol IN ('CLIENTE','PROFESIONAL','ADMIN')),
    activo           INTEGER NOT NULL DEFAULT 1,
    creado_en        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS servicio (
    id                TEXT PRIMARY KEY,
    profesional_id    TEXT NOT NULL REFERENCES usuario(id),
    nombre            TEXT NOT NULL,
    descripcion       TEXT,
    duracion_min      INTEGER NOT NULL CHECK (duracion_min BETWEEN 15 AND 480),
    precio_referencia REAL NOT NULL CHECK (precio_referencia >= 0),
    activo            INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS turno (
    id                 TEXT PRIMARY KEY,
    cliente_id         TEXT NOT NULL REFERENCES usuario(id),
    profesional_id     TEXT NOT NULL REFERENCES usuario(id),
    servicio_id        TEXT NOT NULL REFERENCES servicio(id),
    inicio             TEXT NOT NULL,
    fin                TEXT NOT NULL,
    estado             TEXT NOT NULL CHECK (estado IN ('CONFIRMADO','CANCELADO','COMPLETADO','AUSENTE')),
    motivo_cancelacion TEXT,
    cancelado_por_id   TEXT REFERENCES usuario(id),
    creado_en          TEXT NOT NULL,
    actualizado_en     TEXT NOT NULL,
    CHECK (cliente_id <> profesional_id),
    CHECK (inicio < fin)
);
CREATE INDEX IF NOT EXISTS idx_turno_prof_inicio ON turno(profesional_id, inicio);
"""

# Semilla tomada de los datos mock de index.html (sin turnos: los crea la API).
SEED_USERS = [
    ("admin", "ADMIN", "Admin General", "admin@turnospro.test", "+5491100000000", 1),
    ("p1", "PROFESIONAL", "Dra. Ana Martínez", "ana@turnospro.test", "+5491100000001", 1),
    ("p2", "PROFESIONAL", "Dr. Bruno Salas", "bruno@turnospro.test", "+5491100000002", 1),
    ("p3", "PROFESIONAL", "Lic. Carla Ibáñez", "carla@turnospro.test", "+5491100000003", 1),
    ("c1", "CLIENTE", "Lucía Fernández", "lucia@mail.test", "+5491155550101", 1),
    ("c2", "CLIENTE", "Martín Gómez", "martin@mail.test", "+5491155550102", 0),
    ("c3", "CLIENTE", "Sofía Ruiz", "sofia@mail.test", "+5491155550103", 1),
]
SEED_SERVICES = [
    ("s1", "p1", "Consulta general", "Evaluación clínica y orientación.", 30, 18000),
    ("s2", "p1", "Control anual", "Chequeo completo con estudios básicos.", 60, 32000),
    ("s3", "p2", "Sesión de terapia", "Sesión individual.", 45, 25000),
    ("s4", "p2", "Evaluación inicial", "Primera entrevista y plan de trabajo.", 60, 30000),
    ("s5", "p3", "Asesoría nutricional", "Seguimiento y ajustes.", 30, 15000),
    ("s6", "p3", "Plan alimentario", "Diseño de plan personalizado.", 45, 22000),
]
NO_LOGIN_HASH = "!SIN_LOGIN_FASE_2"  # F-01 no existe todavía (spec D-06); no es un hash válido


def init_db() -> None:
    """Crea las tablas si no existen y carga la semilla solo si la base está vacía."""
    now = tiempo.fmt(tiempo.utcnow())
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM usuario").fetchone()[0] == 0:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO usuario (id, rol, nombre_completo, email, telefono, email_verificado,"
                " password_hash, activo, creado_en) VALUES (?,?,?,?,?,?,?,1,?)",
                [(i, r, n, e, t, v, NO_LOGIN_HASH, now) for (i, r, n, e, t, v) in SEED_USERS],
            )
            conn.executemany(
                "INSERT INTO servicio (id, profesional_id, nombre, descripcion, duracion_min,"
                " precio_referencia, activo) VALUES (?,?,?,?,?,?,1)",
                SEED_SERVICES,
            )
            conn.execute("COMMIT")
    finally:
        conn.close()
