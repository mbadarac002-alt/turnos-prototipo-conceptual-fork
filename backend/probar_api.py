"""Prueba de humo del backend SIN frontend. Requiere el servidor corriendo.

    python probar_api.py                       # contra http://localhost:8000
    python probar_api.py http://localhost:8765

Crea turnos en el servidor (años 2031+ para no chocar con datos reales) y los deja cancelados.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
fallos = 0


def llamar(metodo, path, cuerpo=None):
    data = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or "null"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "null"), e.headers


def verificar(nombre, ok, detalle=""):
    global fallos
    fallos += 0 if ok else 1
    print(f"[{'OK ' if ok else 'FALLA'}] {nombre} {detalle}")


def turno(fecha, email="t@x.com"):
    return {"cliente_nombre": "Prueba", "cliente_email": email, "servicio": "Corte", "fecha_hora": fecha}


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


ahora = datetime.now(timezone.utc)
lejos = datetime(2031, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(seconds=int(ahora.timestamp()) % 10_000_000)

s, b, _ = llamar("GET", "/api/turnos")
verificar("GET /api/turnos -> 200 y lista", s == 200 and isinstance(b, list), f"({len(b)} turnos)")

s, t, h = llamar("POST", "/api/turnos", turno(iso(lejos)))
verificar("crear -> 201 CONFIRMADO + Location", s == 201 and t["estado"] == "CONFIRMADO" and "location" in h)

s, b, _ = llamar("POST", "/api/turnos", turno(iso(lejos), "otro@x.com"))
verificar("mismo horario -> 409 HORARIO_NO_DISPONIBLE", s == 409 and b["detail"]["code"] == "HORARIO_NO_DISPONIBLE")

s, b, _ = llamar("POST", "/api/turnos", turno("2031-01-01T10:00:00"))
verificar("fecha sin zona -> 422 FECHA_INVALIDA", s == 422 and b["detail"]["code"] == "FECHA_INVALIDA")

s, b, _ = llamar("POST", "/api/turnos", turno("2020-01-01T10:00:00Z"))
verificar("fecha pasada -> 422 FECHA_INVALIDA", s == 422 and b["detail"]["code"] == "FECHA_INVALIDA")

s, _, _ = llamar("POST", "/api/turnos", turno(iso(lejos + timedelta(days=1)), "no-es-email"))
verificar("email malo -> 422", s == 422)

s, b, _ = llamar("POST", f"/api/turnos/{t['id']}/cancelar")
verificar("cancelar (lejano) -> 200 CANCELADO_CLIENTE", s == 200 and b["estado"] == "CANCELADO_CLIENTE")

s, b, _ = llamar("POST", f"/api/turnos/{t['id']}/cancelar")
verificar("cancelar de nuevo -> 409 TURNO_NO_CANCELABLE", s == 409 and b["detail"]["code"] == "TURNO_NO_CANCELABLE")

s, b, _ = llamar("POST", "/api/turnos/no-existe/cancelar")
verificar("id inexistente -> 404 TURNO_NO_ENCONTRADO", s == 404 and b["detail"]["code"] == "TURNO_NO_ENCONTRADO")

s, t2, _ = llamar("POST", "/api/turnos", turno(iso(lejos), "libre@x.com"))
verificar("horario liberado se puede reservar -> 201", s == 201)
llamar("POST", f"/api/turnos/{t2['id']}/cancelar")

cerca = ahora + timedelta(minutes=119)
s, t3, _ = llamar("POST", "/api/turnos", turno(iso(cerca), "cerca@x.com"))
if s == 201:
    s, b, _ = llamar("POST", f"/api/turnos/{t3['id']}/cancelar")
    verificar("cancelar a 1 h 59 -> 409 CANCELACION_FUERA_DE_VENTANA", s == 409 and b["detail"]["code"] == "CANCELACION_FUERA_DE_VENTANA")
    print("      (el turno a 1 h 59 queda CONFIRMADO: no se puede cancelar por diseño)")
else:
    verificar("crear turno a 1 h 59", False, f"-> {s} (¿ya hay uno en ese minuto?)")

print("\nTODO OK" if fallos == 0 else f"\n{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)
