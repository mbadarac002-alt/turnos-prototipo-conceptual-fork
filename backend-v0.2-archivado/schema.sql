-- schema.sql — DDL de spec §11.5 (SQLite). Solo las entidades y atributos de spec §4.1.
-- Instantes: TEXT ISO 8601 UTC con formato fijo YYYY-MM-DDTHH:MM:SSZ (comparable como texto).
-- Convención de HorarioLaboral.dia_semana: 0 = lunes ... 6 = domingo; horas locales "HH:MM".

CREATE TABLE IF NOT EXISTS usuario (
    id               TEXT PRIMARY KEY,
    email            TEXT NOT NULL UNIQUE,
    email_verificado INTEGER NOT NULL DEFAULT 0 CHECK (email_verificado IN (0, 1)),
    password_hash    TEXT NOT NULL,
    nombre_completo  TEXT NOT NULL CHECK (length(nombre_completo) BETWEEN 2 AND 100),
    telefono         TEXT NOT NULL,
    rol              TEXT NOT NULL CHECK (rol IN ('CLIENTE', 'PROFESIONAL', 'ADMIN')),
    activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servicio (
    id                TEXT PRIMARY KEY,
    profesional_id    TEXT NOT NULL REFERENCES usuario (id),
    nombre            TEXT NOT NULL,
    descripcion       TEXT,
    duracion_min      INTEGER NOT NULL CHECK (duracion_min BETWEEN 15 AND 480 AND duracion_min % 15 = 0),
    precio_referencia NUMERIC NOT NULL CHECK (precio_referencia >= 0),
    activo            INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE IF NOT EXISTS turno (
    id                 TEXT PRIMARY KEY,
    cliente_id         TEXT NOT NULL REFERENCES usuario (id),
    profesional_id     TEXT NOT NULL REFERENCES usuario (id),
    servicio_id        TEXT NOT NULL REFERENCES servicio (id),
    inicio             TEXT NOT NULL CHECK (inicio GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    fin                TEXT NOT NULL CHECK (fin GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
    estado             TEXT NOT NULL CHECK (estado IN ('CONFIRMADO', 'CANCELADO', 'COMPLETADO', 'AUSENTE')),
    motivo_cancelacion TEXT,
    cancelado_por_id   TEXT REFERENCES usuario (id),
    creado_en          TEXT NOT NULL,
    actualizado_en     TEXT NOT NULL,
    CHECK (fin > inicio),
    CHECK (cliente_id <> profesional_id)                        -- spec §4.3
);

CREATE TABLE IF NOT EXISTS horario_laboral (
    id             TEXT PRIMARY KEY,
    profesional_id TEXT NOT NULL REFERENCES usuario (id),
    dia_semana     INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_inicio    TEXT NOT NULL,
    hora_fin       TEXT NOT NULL,
    CHECK (hora_fin > hora_inicio)
);

CREATE TABLE IF NOT EXISTS bloqueo (
    id             TEXT PRIMARY KEY,
    profesional_id TEXT NOT NULL REFERENCES usuario (id),
    inicio         TEXT NOT NULL,
    fin            TEXT NOT NULL,
    motivo         TEXT,
    CHECK (fin > inicio)
);

CREATE TABLE IF NOT EXISTS auditoria_evento (
    id          TEXT PRIMARY KEY,
    entidad     TEXT NOT NULL,
    entidad_id  TEXT NOT NULL,
    accion      TEXT NOT NULL,
    actor_id    TEXT NOT NULL REFERENCES usuario (id),
    rol         TEXT NOT NULL,
    ocurrido_en TEXT NOT NULL,
    detalle     TEXT
);

-- ---- Refuerzo de INV-02 / RN-02 en la base (spec §11.5) ----------------------------------
-- Intervalos semiabiertos [inicio, fin): A.inicio < B.fin AND B.inicio < A.fin.
CREATE TRIGGER IF NOT EXISTS turno_sin_solapamiento_ins
BEFORE INSERT ON turno
WHEN NEW.estado = 'CONFIRMADO'
BEGIN
    SELECT RAISE(ABORT, 'SLOT_UNAVAILABLE')
    WHERE EXISTS (
        SELECT 1 FROM turno t
        WHERE t.profesional_id = NEW.profesional_id
          AND t.estado = 'CONFIRMADO'
          AND t.id <> NEW.id
          AND t.inicio < NEW.fin
          AND NEW.inicio < t.fin
    );
END;

CREATE TRIGGER IF NOT EXISTS turno_sin_solapamiento_upd
BEFORE UPDATE ON turno
WHEN NEW.estado = 'CONFIRMADO'
BEGIN
    SELECT RAISE(ABORT, 'SLOT_UNAVAILABLE')
    WHERE EXISTS (
        SELECT 1 FROM turno t
        WHERE t.profesional_id = NEW.profesional_id
          AND t.estado = 'CONFIRMADO'
          AND t.id <> NEW.id
          AND t.inicio < NEW.fin
          AND NEW.inicio < t.fin
    );
END;

-- ---- Integridad (spec §4.3, RN-06, RN-08) ------------------------------------------------
CREATE TRIGGER IF NOT EXISTS turno_profesional_coincide_con_servicio
BEFORE INSERT ON turno
BEGIN
    SELECT RAISE(ABORT, 'INTEGRITY_SERVICIO_PROFESIONAL')
    WHERE NOT EXISTS (
        SELECT 1 FROM servicio s WHERE s.id = NEW.servicio_id AND s.profesional_id = NEW.profesional_id
    );
END;

-- Estados terminales (RN-06): ninguna transición sale de CANCELADO/COMPLETADO/AUSENTE.
CREATE TRIGGER IF NOT EXISTS turno_estado_terminal
BEFORE UPDATE OF estado ON turno
WHEN OLD.estado <> 'CONFIRMADO' AND NEW.estado <> OLD.estado
BEGIN
    SELECT RAISE(ABORT, 'INVALID_STATE_TRANSITION');
END;

-- Sin borrado físico del historial (RN-06).
CREATE TRIGGER IF NOT EXISTS turno_sin_borrado
BEFORE DELETE ON turno
BEGIN
    SELECT RAISE(ABORT, 'TURNO_INMUTABLE');
END;

-- Auditoría inmutable (RN-08).
CREATE TRIGGER IF NOT EXISTS auditoria_sin_update
BEFORE UPDATE ON auditoria_evento
BEGIN
    SELECT RAISE(ABORT, 'AUDITORIA_INMUTABLE');
END;

CREATE TRIGGER IF NOT EXISTS auditoria_sin_delete
BEFORE DELETE ON auditoria_evento
BEGIN
    SELECT RAISE(ABORT, 'AUDITORIA_INMUTABLE');
END;
