"""Carga inicial (D-08): Usuario, Servicio, HorarioLaboral y Bloqueo equivalentes al prototipo.

Uso: python seed.py [ruta/turnos.db]
Idempotente: si ya hay usuarios, no hace nada. Los UUID son deterministas (uuid5) para que sean
estables entre cargas. No crea turnos: esos entran solo por la API (INV-03).
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import connect, init_db

NS = uuid.UUID("6f1d3a52-0000-4000-8000-000000000001")
DEFAULT_DB = Path(__file__).resolve().parent.parent / "turnos.db"


def uid(nombre: str) -> str:
    return str(uuid.uuid5(NS, nombre))


# (clave, email, verificado, nombre, telefono, rol)
USUARIOS = [
    ("admin", "admin@turnos.test", 1, "Administración General", "+5491100000000", "ADMIN"),
    ("prof-ana", "ana.lopez@turnos.test", 1, "Ana López", "+5491100000001", "PROFESIONAL"),
    ("prof-bruno", "bruno.diaz@turnos.test", 1, "Bruno Díaz", "+5491100000002", "PROFESIONAL"),
    ("prof-carla", "carla.ruiz@turnos.test", 1, "Carla Ruiz", "+5491100000003", "PROFESIONAL"),
    ("cli-marta", "marta.gomez@turnos.test", 1, "Marta Gómez", "+5491100000011", "CLIENTE"),
    # Email sin verificar: permite probar EMAIL_NOT_VERIFIED.
    ("cli-pablo", "pablo.rey@turnos.test", 0, "Pablo Rey", "+5491100000012", "CLIENTE"),
]

# (clave, profesional, nombre, descripción, duración, precio)
SERVICIOS = [
    ("srv-consulta", "prof-ana", "Consulta general", "Primera consulta o control.", 30, 8000),
    ("srv-seguimiento", "prof-ana", "Seguimiento", "Consulta de seguimiento.", 45, 10000),
    ("srv-corte", "prof-bruno", "Corte de pelo", "Corte y peinado.", 30, 6000),
    ("srv-color", "prof-bruno", "Coloración", "Coloración completa.", 60, 15000),
    ("srv-masaje", "prof-carla", "Masaje descontracturante", "Sesión de masaje.", 60, 12000),
    ("srv-masaje-corto", "prof-carla", "Masaje express", "Sesión corta.", 30, 7000),
]


def seed(path=DEFAULT_DB) -> bool:
    init_db(path)
    conn = connect(path)
    try:
        if conn.execute("SELECT 1 FROM usuario LIMIT 1").fetchone():
            return False
        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("BEGIN IMMEDIATE")
        for k, email, ver, nombre, tel, rol in USUARIOS:
            # password_hash: marcador no utilizable; el login (F-01) no está implementado (D-06).
            conn.execute("INSERT INTO usuario VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                         (uid(k), email, ver, "!sin-login", nombre, tel, rol, ahora))
        for k, prof, nombre, desc, dur, precio in SERVICIOS:
            conn.execute("INSERT INTO servicio VALUES (?, ?, ?, ?, ?, ?, 1)",
                         (uid(k), uid(prof), nombre, desc, dur, precio))
        for prof in ("prof-ana", "prof-bruno", "prof-carla"):
            for dia in range(5):  # lunes a viernes, 09:00–13:00 y 14:00–18:00 (hora local)
                for ini, fin in (("09:00", "13:00"), ("14:00", "18:00")):
                    conn.execute("INSERT INTO horario_laboral VALUES (?, ?, ?, ?, ?)",
                                 (uid(f"hl-{prof}-{dia}-{ini}"), uid(prof), dia, ini, fin))
        # Un bloqueo de ejemplo: Bruno, dentro de 3 días, 3 h.
        b_ini = (datetime.now(timezone.utc) + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
        conn.execute("INSERT INTO bloqueo VALUES (?, ?, ?, ?, ?)",
                     (uid("bloqueo-1"), uid("prof-bruno"), b_ini.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      (b_ini + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"), "Trámite personal"))
        conn.execute("COMMIT")
        return True
    finally:
        conn.close()


if __name__ == "__main__":
    destino = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    print(f"Seed aplicado en {destino}" if seed(destino) else f"{destino} ya tiene datos; sin cambios.")
    for k, *_ in USUARIOS + SERVICIOS:
        print(f"  {k:18} {uid(k)}")
