"""Construcción de la aplicación FastAPI: metadatos, CORS, manejadores de error y arranque."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.rutas import router
from app.datos.esquema import init_db
from app.errores import DomainError

DESCRIPCION_API = """
API REST de **Turnos Pro**: reserva y cancelación de turnos con profesionales.

Reglas que hace cumplir el servidor (ver `spec.md`):

* **INV-01** — un cliente no puede cancelar con menos de 2 horas de anticipación.
* **INV-02** — no se solapan turnos `CONFIRMADO` del mismo profesional ni del mismo cliente.
* **INV-03** — los datos se guardan en SQLite y la verificación y la escritura son atómicas.

Todos los errores responden `{"error": CODIGO, "detalle": texto}` (catálogo spec §7).
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Al iniciar el servidor crea las tablas y la semilla (ver `init_db`)."""
    init_db()
    yield


def crear_app() -> FastAPI:
    app = FastAPI(
        title="Turnos Pro API",
        version="0.2.1",
        description=DESCRIPCION_API,
        openapi_tags=[{"name": "Turnos", "description": "Consulta, reserva y cancelación de turnos."}],
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        """Traduce una `DomainError` a su respuesta HTTP según el catálogo de la §7."""
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "detalle": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        """Errores de validación de Pydantic (campos faltantes, tipos o textos vacíos) → 422 INVALID_REQUEST."""
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=422, content={"error": "INVALID_REQUEST", "detalle": detail})

    app.include_router(router)
    return app


app = crear_app()
