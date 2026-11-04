import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["TURNOS_NO_AUTOAPP"] = "1"          # no crear turnos.db al importar main
os.environ["TURNOS_TZ"] = "America/Argentina/Buenos_Aires"   # UTC-3 fijo, sin horario de verano
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

import main
import seed
from seed import uid

# Lunes 2026-11-02 09:00 hora local (12:00Z). El jueves 10:00 local = 13:00Z del miércoles 04/11.
AHORA = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)


class Reloj:
    def __init__(self):
        self.now = AHORA

    def __call__(self):
        return self.now

    def set(self, texto):
        self.now = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Entorno:
    def __init__(self, path):
        self.path = path
        self.reloj = Reloj()
        seed.seed(path)
        self.reiniciar()

    def reiniciar(self):
        """Simula reiniciar el backend: nueva app sobre el mismo archivo de base."""
        self.app = main.create_app(self.path, now_fn=self.reloj)
        self.client = TestClient(self.app)

    def reservar(self, cliente="cli-marta", servicio="srv-consulta", inicio="2026-11-04T13:00:00Z"):
        return self.client.post("/api/turnos", json={
            "cliente_id": uid(cliente), "servicio_id": uid(servicio), "inicio": inicio})

    def cancelar(self, turno_id, actor="cli-marta", motivo=None):
        return self.client.post(f"/api/turnos/{turno_id}/cancelar", json={
            "cancelado_por_id": uid(actor), "motivo_cancelacion": motivo})


@pytest.fixture
def env(tmp_path):
    return Entorno(tmp_path / "turnos.db")
