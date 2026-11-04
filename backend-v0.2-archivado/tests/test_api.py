"""Criterios de aceptación de spec §8 contra la API con SQLite real."""
import sqlite3
import threading
import uuid

import pytest

from db import connect
from seed import uid

INI = "2026-11-04T13:00:00Z"      # miércoles 10:00 local, servicio de 30 min -> fin 13:30Z


def codigo(r):
    return r.json()["error"]["code"]


def contar(env, tabla):
    c = connect(env.path)
    try:
        return c.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
    finally:
        c.close()


def test_listar_vacio(env):
    r = env.client.get("/api/turnos")
    assert r.status_code == 200 and r.json() == []


def test_crear_devuelve_201_con_contrato(env):
    r = env.reservar()
    assert r.status_code == 201
    t = r.json()
    assert r.headers["location"] == f"/api/turnos/{t['id']}"
    assert t["estado"] == "CONFIRMADO" and t["fin"] == "2026-11-04T13:30:00Z"
    assert t["profesional_id"] == uid("prof-ana")
    assert t["motivo_cancelacion"] is None and t["cancelado_por_id"] is None
    assert set(t) == {"id", "cliente_id", "profesional_id", "servicio_id", "inicio", "fin", "estado",
                      "motivo_cancelacion", "cancelado_por_id", "creado_en", "actualizado_en"}


# --- Criterio 1: doble reserva / solapamiento parcial -------------------------------------
def test_c1_solapamiento_parcial(env):
    assert env.reservar().status_code == 201
    _crear_cliente(env, "cli-3")
    r = env.reservar(cliente="cli-3", inicio="2026-11-04T13:15:00Z")
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"
    assert len(env.client.get("/api/turnos").json()) == 1


# --- Criterio 3: contigüidad ---------------------------------------------------------------
def test_c3_contiguo_se_confirma(env):
    assert env.reservar().status_code == 201
    _crear_cliente(env, "cli-3")
    assert env.reservar(cliente="cli-3", inicio="2026-11-04T13:30:00Z").status_code == 201


# --- Criterio 2: concurrencia --------------------------------------------------------------
def test_c2_concurrencia_una_sola_gana(env):
    n = 8
    for i in range(n):
        _crear_cliente(env, f"cli-c{i}")
    barrera, resultados = threading.Barrier(n), []

    def worker(i):
        barrera.wait()
        resultados.append(env.reservar(cliente=f"cli-c{i}").status_code)

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(resultados) == [201] + [409] * (n - 1)
    assert len(env.client.get("/api/turnos").json()) == 1
    assert contar(env, "auditoria_evento") == 1


# --- Criterios 4 y 5: INV-01 ---------------------------------------------------------------
def test_c4_cancelar_a_3h(env):
    t = env.reservar().json()
    env.reloj.set("2026-11-04T10:00:00Z")
    r = env.cancelar(t["id"])
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADO"
    assert r.json()["cancelado_por_id"] == uid("cli-marta")


def test_c5_cancelar_a_1h59(env):
    t = env.reservar().json()
    env.reloj.set("2026-11-04T11:01:00Z")
    r = env.cancelar(t["id"])
    assert r.status_code == 409 and codigo(r) == "CANCELLATION_WINDOW_EXPIRED"
    assert env.client.get("/api/turnos").json()[0]["estado"] == "CONFIRMADO"


def test_cancelar_exactamente_a_2h_se_permite(env):
    t = env.reservar().json()
    env.reloj.set("2026-11-04T11:00:00Z")
    assert env.cancelar(t["id"]).status_code == 200


def test_cancelar_libera_el_slot(env):
    t = env.reservar().json()
    assert env.cancelar(t["id"]).status_code == 200
    _crear_cliente(env, "cli-3")
    assert env.reservar(cliente="cli-3").status_code == 201


# --- Criterio 6 y validaciones de reserva --------------------------------------------------
def test_c6_contacto_invalido(env):
    _crear_cliente(env, "cli-sin-tel", telefono="123")
    r = env.reservar(cliente="cli-sin-tel")
    assert r.status_code == 422 and codigo(r) == "INVALID_CONTACT"
    assert contar(env, "turno") == 0


def test_email_no_verificado(env):
    r = env.reservar(cliente="cli-pablo")
    assert r.status_code == 403 and codigo(r) == "EMAIL_NOT_VERIFIED"


@pytest.mark.parametrize("inicio", [
    "2026-11-04T13:10:00Z",     # fuera de la grilla de 15 min
    "2026-11-02T12:30:00Z",     # menos de 1 h de antelación
    "2027-02-01T13:00:00Z",     # más allá de 60 días
    "no-es-una-fecha",
    "2026-11-04T13:00:00-03:00",  # el contrato exige UTC con Z
    None,
])
def test_inicio_invalido(env, inicio):
    r = env.reservar(inicio=inicio)
    assert r.status_code == 422 and codigo(r) == "INVALID_TIME_RANGE"


def test_fuera_de_horario_laboral(env):
    r = env.reservar(inicio="2026-11-04T21:00:00Z")   # 18:00 local, ya cerró
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"
    r = env.reservar(inicio="2026-11-07T13:00:00Z")   # sábado
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"


def test_turno_no_cruza_el_almuerzo(env):
    # Consulta de 45 min desde 12:30 local (15:30Z) terminaría 13:15, fuera de la franja 09–13.
    r = env.reservar(servicio="srv-seguimiento", inicio="2026-11-04T15:30:00Z")
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"


def test_bloqueo_impide_reservar(env):
    c = connect(env.path)
    c.execute("INSERT INTO bloqueo VALUES (?, ?, ?, ?, ?)",
              (str(uuid.uuid4()), uid("prof-ana"), "2026-11-04T13:00:00Z", "2026-11-04T14:00:00Z", "x"))
    c.close()
    r = env.reservar(inicio="2026-11-04T13:30:00Z")
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"


def test_cliente_no_puede_tener_dos_turnos_solapados(env):
    assert env.reservar().status_code == 201
    r = env.reservar(servicio="srv-corte")    # otro profesional, mismo horario
    assert r.status_code == 409 and codigo(r) == "SLOT_UNAVAILABLE"


def test_servicio_inactivo(env):
    c = connect(env.path)
    c.execute("UPDATE servicio SET activo = 0 WHERE id = ?", (uid("srv-consulta"),))
    c.close()
    r = env.reservar()
    assert r.status_code == 409 and codigo(r) == "SERVICE_UNAVAILABLE"


def test_ids_inexistentes_o_rol_incorrecto(env):
    r = env.client.post("/api/turnos", json={"cliente_id": str(uuid.uuid4()), "servicio_id": uid("srv-consulta"), "inicio": INI})
    assert r.status_code == 404 and codigo(r) == "NOT_FOUND"
    r = env.reservar(cliente="prof-bruno")
    assert r.status_code == 403 and codigo(r) == "FORBIDDEN"


# --- Criterio 7 y cancelación por profesional/admin ----------------------------------------
def test_c7_aislamiento_devuelve_404(env):
    t = env.reservar().json()
    _crear_cliente(env, "cli-3")
    r = env.cancelar(t["id"], actor="cli-3")
    assert r.status_code == 404 and codigo(r) == "NOT_FOUND"
    r = env.cancelar(t["id"], actor="prof-bruno", motivo="x")     # profesional ajeno
    assert r.status_code == 404


def test_profesional_cancela_fuera_de_ventana_con_motivo(env):
    t = env.reservar().json()
    env.reloj.set("2026-11-04T12:00:00Z")   # faltan 60 min
    r = env.cancelar(t["id"], actor="prof-ana")
    assert r.status_code == 422 and codigo(r) == "REASON_REQUIRED"
    r = env.cancelar(t["id"], actor="prof-ana", motivo="Imprevisto")
    assert r.status_code == 200
    assert r.json()["motivo_cancelacion"] == "Imprevisto" and r.json()["cancelado_por_id"] == uid("prof-ana")


def test_admin_cancela_cualquier_turno(env):
    t = env.reservar().json()
    assert env.cancelar(t["id"], actor="admin", motivo="Cierre").status_code == 200


def test_no_se_cancela_dos_veces_ni_uno_iniciado(env):
    t = env.reservar().json()
    assert env.cancelar(t["id"]).status_code == 200
    r = env.cancelar(t["id"])
    assert r.status_code == 409 and codigo(r) == "INVALID_STATE_TRANSITION"
    t2 = env.reservar(inicio="2026-11-04T14:00:00Z").json()
    env.reloj.set("2026-11-04T14:10:00Z")
    r = env.cancelar(t2["id"], actor="prof-ana", motivo="tarde")
    assert r.status_code == 409 and codigo(r) == "INVALID_STATE_TRANSITION"


def test_cancelar_turno_inexistente(env):
    r = env.cancelar(str(uuid.uuid4()))
    assert r.status_code == 404


# --- Criterios 9, 10, 11: INV-03 -----------------------------------------------------------
def test_c9_persistencia_tras_reinicio(env):
    t = env.reservar().json()
    env.reiniciar()
    lista = env.client.get("/api/turnos").json()
    assert lista == [t]


def test_c10_atomicidad_rechazo_no_deja_rastro(env):
    env.reservar()
    _crear_cliente(env, "cli-3")
    turnos, auditoria = contar(env, "turno"), contar(env, "auditoria_evento")
    assert env.reservar(cliente="cli-3").status_code == 409
    assert (contar(env, "turno"), contar(env, "auditoria_evento")) == (turnos, auditoria)


def test_c11_cancelacion_persistida(env):
    a = env.reservar().json()
    b = env.reservar(inicio="2026-11-04T14:00:00Z").json()
    env.reloj.set("2026-11-04T10:00:00Z")
    assert env.cancelar(a["id"]).status_code == 200
    env.reiniciar()
    estados = {t["id"]: t["estado"] for t in env.client.get("/api/turnos").json()}
    assert estados == {a["id"]: "CANCELADO", b["id"]: "CONFIRMADO"}
    env.reloj.set("2026-11-04T12:01:00Z")   # a 1 h 59 del segundo turno (14:00Z)
    r = env.cancelar(b["id"])
    assert codigo(r) == "CANCELLATION_WINDOW_EXPIRED"
    assert env.client.get("/api/turnos").json()[1]["estado"] == "CONFIRMADO"


def test_auditoria_de_creacion_y_cancelacion(env):
    t = env.reservar().json()
    env.cancelar(t["id"])
    c = connect(env.path)
    acciones = [r["accion"] for r in c.execute("SELECT accion FROM auditoria_evento ORDER BY ocurrido_en, rowid")]
    c.close()
    assert acciones == ["CREAR_TURNO", "CANCELAR_TURNO"]


def test_orden_por_inicio_ascendente(env):
    env.reservar(inicio="2026-11-04T15:00:00Z")
    env.reservar(inicio="2026-11-04T13:00:00Z")
    inicios = [t["inicio"] for t in env.client.get("/api/turnos").json()]
    assert inicios == sorted(inicios)


# --- Base de datos: refuerzos independientes de la aplicación ------------------------------
def test_db_rechaza_solapamiento_sin_pasar_por_la_api(env):
    t = env.reservar().json()
    c = connect(env.path)
    with pytest.raises(sqlite3.IntegrityError, match="SLOT_UNAVAILABLE"):
        c.execute(
            "INSERT INTO turno VALUES (?, ?, ?, ?, ?, ?, 'CONFIRMADO', NULL, NULL,"
            " '2026-11-02T12:00:00Z', '2026-11-02T12:00:00Z')",
            (str(uuid.uuid4()), uid("cli-pablo"), t["profesional_id"], t["servicio_id"], "2026-11-04T13:10:00Z", "2026-11-04T13:40:00Z"))
    c.close()


def test_db_no_permite_borrar_turnos_ni_editar_auditoria(env):
    env.reservar()
    c = connect(env.path)
    with pytest.raises(sqlite3.IntegrityError, match="TURNO_INMUTABLE"):
        c.execute("DELETE FROM turno")
    with pytest.raises(sqlite3.IntegrityError, match="AUDITORIA_INMUTABLE"):
        c.execute("DELETE FROM auditoria_evento")
    c.close()


def test_db_estado_terminal(env):
    t = env.reservar().json()
    env.cancelar(t["id"])
    c = connect(env.path)
    with pytest.raises(sqlite3.IntegrityError, match="INVALID_STATE_TRANSITION"):
        c.execute("UPDATE turno SET estado = 'CONFIRMADO' WHERE id = ?", (t["id"],))
    c.close()


def test_cuerpo_invalido(env):
    r = env.client.post("/api/turnos", content="no json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_cors(env):
    r = env.client.options("/api/turnos", headers={"origin": "http://localhost:5500",
                                                    "access-control-request-method": "POST"})
    assert r.headers["access-control-allow-origin"] in ("*", "http://localhost:5500")


def _crear_cliente(env, clave, telefono="+5491100009999"):
    c = connect(env.path)
    c.execute("INSERT INTO usuario VALUES (?, ?, 1, '!', ?, ?, 'CLIENTE', 1, '2026-11-01T00:00:00Z')",
              (uid(clave), f"{clave}@turnos.test", f"Cliente {clave}", telefono))
    c.close()
