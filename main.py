"""Punto de entrada de Turnos Pro (Fase 2) — backend en 3 capas, FastAPI + SQLite.

Fuente de verdad: spec.md v0.2.1 y plan.md v2. La arquitectura está en el paquete `app/`:

    app/api/       capa 1 · Presentación (endpoints, esquemas Pydantic, errores HTTP)
    app/negocio/   capa 2 · Lógica de negocio (reglas RN-xx / INV-xx)
    app/datos/     capa 3 · Datos (SQLite, esquema, semilla, consultas)

Levantar:  uvicorn main:app --reload --port 8000      Swagger UI: http://localhost:8000/docs
Probar:    python -m pytest

La versión monolítica (todo en este archivo) vive en la rama `monolitico`.
"""
from app.api.aplicacion import app

__all__ = ["app"]
