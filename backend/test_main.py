"""Tests de la API (spec §8, criterios 1, 2, 5, 9, 10, 11) contra SQLite real."""
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

BASE = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)  # "ahora" fijo de los tests


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Reloj:
    def __init__(self) -> None:
        self.now = BASE

    def __call__(self) -> datetime:
        return self.now


class Entorno:
    def __init__(self, path: Path, reloj: Reloj) -> None:
        self.path, self.reloj = path, reloj

    def cliente(self) -> TestClient:
        """Un cliente HTTP nuevo ejecuta el lifespan: equivale a (re)iniciar el servidor."""
        return TestClient(main.app)

    def reservar(self, c: TestClient, fecha: str, email: str = "ana@mail.com", servicio: str = "Corte"):  # type: ignore[no-untyped-def]
        return c.post("/api/turnos", json={
            "cliente_nombre": "Ana Pérez", "cliente_email": email, "servicio": servicio, "fecha_hora": fecha})

    def filas(self) -> int:
        conn = sqlite3.connect(self.path)
        try:
            return int(conn.execute("SELECT count(*) FROM turnos").fetchone()[0])
        finally:
            conn.close()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Entorno]:
    reloj = Reloj()
    db = tmp_path / "turnos.db"
    monkeypatch.setattr(main, "DB_PATH", db)
    monkeypatch.setattr(main, "ahora", reloj)
    yield Entorno(db, reloj)


def code(r) -> str:  # type: ignore[no-untyped-def]
    return str(r.json()["detail"]["code"])


# ---- Arranque y GET -----------------------------------------------------------------------
def test_la_tabla_se_crea_al_iniciar(env: Entorno) -> None:
    with env.cliente() as c:
        assert c.get("/api/turnos").json() == []
    conn = sqlite3.connect(env.path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(turnos)")]
    conn.close()
    assert cols == ["id", "cliente_nombre", "cliente_email", "servicio", "fecha_hora", "estado"]


def test_cors_permisivo(env: Entorno) -> None:
    with env.cliente() as c:
        r = c.options("/api/turnos", headers={"origin": "http://localhost:5500", "access-control-request-method": "POST"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_crear_devuelve_201_y_contrato(env: Entorno) -> None:
    with env.cliente() as c:
        r = env.reservar(c, "2026-11-04T13:00:00Z", email="  ANA@Mail.com ")
    t = r.json()
    assert r.status_code == 201 and r.headers["location"] == f"/api/turnos/{t['id']}"
    assert set(t) == {"id", "cliente_nombre", "cliente_email", "servicio", "fecha_hora", "estado"}
    assert t["estado"] == "CONFIRMADO" and t["cliente_email"] == "ana@mail.com"
    assert t["fecha_hora"] == "2026-11-04T13:00:00Z"


def test_offset_se_normaliza_a_utc(env: Entorno) -> None:
    with env.cliente() as c:
        r = env.reservar(c, "2026-11-04T10:00:00-03:00")
    assert r.json()["fecha_hora"] == "2026-11-04T13:00:00Z"


def test_listado_ordenado_por_fecha(env: Entorno) -> None:
    with env.cliente() as c:
        env.reservar(c, "2026-11-04T15:00:00Z")
        env.reservar(c, "2026-11-04T13:00:00Z")
        fechas = [t["fecha_hora"] for t in c.get("/api/turnos").json()]
    assert fechas == sorted(fechas) and len(fechas) == 2


# ---- Criterio 1: INV-02 ------------------------------------------------------------------
def test_c1_mismo_horario_devuelve_409(env: Entorno) -> None:
    with env.cliente() as c:
        assert env.reservar(c, "2026-11-04T13:00:00Z").status_code == 201
        r = env.reservar(c, "2026-11-04T10:00:00-03:00", email="otro@mail.com")  # mismo instante
        assert r.status_code == 409 and code(r) == "HORARIO_NO_DISPONIBLE"
        assert len(c.get("/api/turnos").json()) == 1


def test_horario_distinto_se_acepta(env: Entorno) -> None:
    with env.cliente() as c:
        assert env.reservar(c, "2026-11-04T13:00:00Z").status_code == 201
        assert env.reservar(c, "2026-11-04T13:30:00Z", email="b@mail.com").status_code == 201


def test_cancelar_libera_el_horario(env: Entorno) -> None:
    with env.cliente() as c:
        t = env.reservar(c, "2026-11-04T13:00:00Z").json()
        assert c.post(f"/api/turnos/{t['id']}/cancelar").status_code == 200
        assert env.reservar(c, "2026-11-04T13:00:00Z", email="b@mail.com").status_code == 201


# ---- Criterio 2: concurrencia ------------------------------------------------------------
def test_c2_concurrencia_una_sola_gana(env: Entorno) -> None:
    n = 10
    with env.cliente():  # inicializa la base
        pass
    barrera, estados = threading.Barrier(n), []

    def worker(i: int) -> None:
        with TestClient(main.app) as c:
            barrera.wait()
            estados.append(env.reservar(c, "2026-11-04T13:00:00Z", email=f"u{i}@mail.com").status_code)

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert sorted(estados) == [201] + [409] * (n - 1)
    assert env.filas() == 1


# ---- Criterio 5: INV-01 ------------------------------------------------------------------
def _cancelar_con_anticipacion(env: Entorno, anticipacion: timedelta):  # type: ignore[no-untyped-def]
    with env.cliente() as c:
        t = env.reservar(c, "2026-11-04T13:00:00Z").json()
        env.reloj.now = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc) - anticipacion
        return t, c.post(f"/api/turnos/{t['id']}/cancelar"), c


def test_cancelar_con_3h(env: Entorno) -> None:
    t, r, _ = _cancelar_con_anticipacion(env, timedelta(hours=3))
    assert r.status_code == 200 and r.json()["estado"] == "CANCELADO_CLIENTE" and r.json()["id"] == t["id"]


def test_cancelar_con_exactamente_2h_se_permite(env: Entorno) -> None:
    _, r, _ = _cancelar_con_anticipacion(env, timedelta(hours=2))
    assert r.status_code == 200


def test_c5_cancelar_con_1h59_devuelve_409(env: Entorno) -> None:
    _, r, c = _cancelar_con_anticipacion(env, timedelta(hours=1, minutes=59))
    assert r.status_code == 409 and code(r) == "CANCELACION_FUERA_DE_VENTANA"
    with env.cliente() as c2:
        assert c2.get("/api/turnos").json()[0]["estado"] == "CONFIRMADO"


def test_cancelar_turno_ya_pasado(env: Entorno) -> None:
    _, r, _ = _cancelar_con_anticipacion(env, timedelta(hours=-1))
    assert r.status_code == 409 and code(r) == "CANCELACION_FUERA_DE_VENTANA"


def test_cancelar_dos_veces(env: Entorno) -> None:
    with env.cliente() as c:
        t = env.reservar(c, "2026-11-04T13:00:00Z").json()
        assert c.post(f"/api/turnos/{t['id']}/cancelar").status_code == 200
        r = c.post(f"/api/turnos/{t['id']}/cancelar")
    assert r.status_code == 409 and code(r) == "TURNO_NO_CANCELABLE"


def test_cancelar_inexistente(env: Entorno) -> None:
    with env.cliente() as c:
        r = c.post(f"/api/turnos/{uuid.uuid4()}/cancelar")
    assert r.status_code == 404 and code(r) == "TURNO_NO_ENCONTRADO"


# ---- Validaciones de entrada --------------------------------------------------------------
@pytest.mark.parametrize("fecha", ["no-es-fecha", "2026-11-04T13:00:00", "2026-11-02T11:00:00Z", "2026-11-02T12:00:00Z"])
def test_fecha_invalida(env: Entorno, fecha: str) -> None:
    with env.cliente() as c:
        r = env.reservar(c, fecha)
    assert r.status_code == 422 and code(r) == "FECHA_INVALIDA"
    assert env.filas() == 0


@pytest.mark.parametrize("cuerpo", [
    {"cliente_nombre": "A", "cliente_email": "a@b.com", "servicio": "x", "fecha_hora": "2026-11-04T13:00:00Z"},
    {"cliente_nombre": "Ana", "cliente_email": "sin-arroba", "servicio": "x", "fecha_hora": "2026-11-04T13:00:00Z"},
    {"cliente_nombre": "Ana", "cliente_email": "a@b.com", "servicio": "  ", "fecha_hora": "2026-11-04T13:00:00Z"},
    {"cliente_nombre": "Ana", "cliente_email": "a@b.com", "servicio": "x"},
    {"cliente_nombre": "Ana", "cliente_email": "a@b.com", "servicio": "x", "fecha_hora": "2026-11-04T13:00:00Z", "estado": "CANCELADO_CLIENTE"},
])
def test_validacion_pydantic(env: Entorno, cuerpo: dict[str, str]) -> None:
    with env.cliente() as c:
        assert c.post("/api/turnos", json=cuerpo).status_code == 422
    assert env.filas() == 0


# ---- Criterios 9, 10 y 11: INV-03 ---------------------------------------------------------
def test_c9_persistencia_tras_reinicio(env: Entorno) -> None:
    with env.cliente() as c:
        t = env.reservar(c, "2026-11-04T13:00:00Z").json()
    with env.cliente() as c2:  # "reinicio"
        assert c2.get("/api/turnos").json() == [t]


def test_c10_rechazo_no_deja_rastro(env: Entorno) -> None:
    with env.cliente() as c:
        env.reservar(c, "2026-11-04T13:00:00Z")
        antes = c.get("/api/turnos").json()
        assert env.reservar(c, "2026-11-04T13:00:00Z", email="b@mail.com").status_code == 409
        assert c.get("/api/turnos").json() == antes


def test_c11_cancelacion_persistida(env: Entorno) -> None:
    with env.cliente() as c:
        a = env.reservar(c, "2026-11-04T13:00:00Z").json()
        b = env.reservar(c, "2026-11-04T15:00:00Z", email="b@mail.com").json()
        env.reloj.now = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)  # a 3 h de a
        assert c.post(f"/api/turnos/{a['id']}/cancelar").status_code == 200
    with env.cliente() as c2:
        estados = {t["id"]: t["estado"] for t in c2.get("/api/turnos").json()}
        assert estados == {a["id"]: "CANCELADO_CLIENTE", b["id"]: "CONFIRMADO"}
        assert env.reservar(c2, "2026-11-04T13:00:00Z", email="c@mail.com").status_code == 201  # slot libre
        env.reloj.now = datetime(2026, 11, 4, 13, 1, tzinfo=timezone.utc)  # b a 1 h 59
        r = c2.post(f"/api/turnos/{b['id']}/cancelar")
        assert r.status_code == 409 and code(r) == "CANCELACION_FUERA_DE_VENTANA"
        assert {t["id"]: t["estado"] for t in c2.get("/api/turnos").json()}[b["id"]] == "CONFIRMADO"
