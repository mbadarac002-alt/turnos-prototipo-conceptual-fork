"""Turnos Pro — backend en 3 capas.

    app.api      capa 1 · Presentación: HTTP, validación de entrada, serialización (FastAPI/Pydantic).
    app.negocio  capa 2 · Lógica de negocio: reglas RN-xx / INV-xx, sin HTTP ni SQL.
    app.datos    capa 3 · Datos: SQLite, esquema, semilla y consultas.

Dependencias permitidas: api → negocio → datos. Nunca al revés.
`config`, `errores` y `tiempo` son transversales a las tres capas.
"""
