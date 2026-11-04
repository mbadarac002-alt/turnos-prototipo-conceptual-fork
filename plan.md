# plan.md — Plan técnico del Sistema de Turnos

| Campo | Valor |
|---|---|
| Versión | 0.3.0 |
| Base normativa | [spec.md](spec.md) v0.3.0 · [historias-de-usuario.md](historias-de-usuario.md) |
| Fecha | 2026-11-03 |
| Estado | Pendiente de aprobación |

| Versión | Fecha | Cambios |
|---|---|---|
| 0.1.0 | 2026-10-26 | Plan del prototipo interactivo en memoria (Fase 1). |
| 0.2.0 | 2026-11-03 | Se agrega la Fase 2: arquitectura desacoplada de 3 capas (§8 a §14). La Fase 1 (§1 a §7) se conserva como referencia; la decisión 5 de §7 queda reemplazada por INV-03. |
| 0.3.0 | 2026-11-03 | La Fase 2 (§8 a §14) se reescribe para el modelo simplificado de una tabla `turnos`, un único `backend/main.py` y los códigos de error de spec §11.6. El backend del modelo completo de 6 tablas se archiva en `backend-v0.2-archivado/`. |

> **Alcance de este documento.** §1 a §7 describen el prototipo de la Fase 1 (hoy en `index.html`, todo en memoria). §8 a §14 describen la Fase 2, que lo reemplaza como sistema real.

# Fase 1 — Prototipo interactivo (Claude Artifact)

## 1. Formato de entrega

- Un único archivo HTML publicado como Artifact. Dentro va un solo componente React con Tailwind (`cdn.tailwindcss.com`) y Lucide Icons.
- React, Babel y Lucide se cargan desde CDN con versión fija. No hay build ni dependencias locales.
- Antes de escribirlo se carga la guía de diseño de Artifacts: tokens de color, modo oscuro y layout responsive.
- El componente es modular dentro del mismo archivo, con una sección lógica por responsabilidad:

| Módulo | Contenido |
|---|---|
| `domain/` | Funciones puras del spec: solapamiento, ventana de cancelación, validación de contacto, cálculo de slots, transiciones de estado |
| `store` | Estado único con `useReducer` y un `Context`; un reducer centralizado donde se aplican todas las reglas |
| `ClientView` | Servicio, grilla de slots, formulario, "Mis turnos" |
| `AdminView` | Agenda, métricas, bloqueos, acciones sobre turnos |
| `ui/` | Componentes compartidos: toasts, modales, badges de estado, barra superior |

## 2. Decisión de diseño clave

Toda regla vive en `domain/` y el reducer la ejecuta. La UI nunca decide si algo está permitido: solo muestra el error que devuelve el dominio, con los mismos códigos del spec (`SLOT_UNAVAILABLE`, `CANCELLATION_WINDOW_EXPIRED`, etc.). Esto simula el principio RBAC-01 de que la UI no es la barrera de seguridad.

## 3. Reglas que se implementan

- **RN-01:** cancelación del cliente bloqueada a menos de 2 h del inicio. El Administrador la salta, pero con motivo obligatorio.
- **RN-02:** sin solapamiento con intervalos `[inicio, fin)`, contigüidad válida, y sin solapar con bloqueos ni con turnos propios del cliente.
- **RN-03:** nombre, email y teléfono válidos y email verificado antes de reservar.
- **RN-04:** grilla de 15 min, antelación mínima de 1 h, horizonte de 60 días, y `fin` calculado por el sistema.
- **RN-05:** bloquear un rango con turnos activos lista los conflictos y exige confirmar la cancelación.
- **RN-06:** estados terminales, sin borrado físico.
- **RN-08:** panel de auditoría visible para el Administrador.
- **RBAC:** el cliente solo ve sus turnos. Con el cambio de rol se ve en vivo qué aparece y qué desaparece.

## 4. Datos mock en memoria

- 3 profesionales, 5 a 6 servicios con duraciones distintas (30, 45, 60 min).
- 2 clientes. Uno de ellos tiene el email sin verificar, para poder probar `EMAIL_NOT_VERIFIED`.
- Unos 12 turnos distribuidos en los próximos días: confirmados, cancelados, completados y ausentes. Incluye uno que empieza dentro de 1 h 59 min y otro a las 3 h, para probar RN-01 sin esperar.
- 1 o 2 bloqueos y horario laboral de lunes a viernes.
- Las fechas son relativas a "hoy" real, así que el prototipo no envejece.
- Una sola fuente de datos alimenta ambas vistas, así que cualquier acción en una se refleja de inmediato en la otra.

## 5. Vistas

- **Barra superior:** el selector Cliente/Administrador, el usuario activo (con selector entre los 2 clientes mock) y un reloj simulado con botones para avanzar tiempo (+1 h, +1 día). El reloj sirve para auditar RN-01 y los estados `COMPLETADO`/`AUSENTE`.
- **Cliente:**
  - Elige servicio, profesional y fecha.
  - Ve la grilla de slots y un modal de confirmación con los datos de contacto.
  - Ve "Mis turnos", con el botón de cancelar deshabilitado y con tooltip explicativo dentro de las 2 h.
- **Administrador:**
  - Vista de agenda día/semana y vista de lista.
  - Métricas: turnos por período, tasas de cancelación y ausentismo, ocupación y top servicios.
  - Acciones sobre turnos: cancelar con motivo, completar y marcar ausente.
  - Gestión de bloqueos.
  - Un filtro de profesional para el rol `ADMIN`.

## 6. Verificación

- Probar en el navegador integrado los 8 escenarios de aceptación del spec §8, incluyendo el doble clic y la reserva del mismo slot desde dos clientes (concurrencia simulada en el reducer).
- Revisar la consola, el ancho móvil y el modo oscuro antes de publicar.
- Entregar el link del Artifact y una tabla que cruza cada escenario con el resultado observado.

## 7. Decisiones tomadas (por defecto, salvo indicación contraria)

| # | Tema | Decisión |
|---|---|---|
| 1 | Reloj simulado con botones para avanzar tiempo | **Sí** |
| 2 | Selector "Profesional / ADMIN" en la vista Administrador | **Sí** |
| 3 | Emails como "bandeja simulada" (F-13) | **Sí**, panel lateral colapsable |
| 4 | Reducir el horario laboral con turnos reservados (Q-01) | **Fuera** del prototipo; solo se implementa el bloqueo (RN-05) |
| 5 | Persistencia entre recargas | **No**: todo en memoria, con botón "Reiniciar datos". **Reemplazada en la Fase 2 por INV-03** (ver §9). |

---

# Fase 2 — Arquitectura desacoplada y software real

## 8. Objetivo y alcance

Pasar del prototipo monolítico en memoria a un sistema de 3 capas independientes que cumpla INV-01, INV-02 e INV-03 sobre datos persistidos, y exponga el contrato REST de [spec.md §11](spec.md) (v0.3.0).

Alcance de la Fase 2: **solo los tres endpoints de spec §11** (`GET /api/turnos`, `POST /api/turnos`, `POST /api/turnos/{id}/cancelar`) sobre el **modelo simplificado de una tabla `turnos`**. Catálogo, disponibilidad, usuarios, roles, horario laboral, bloqueos y auditoría quedan fuera (spec §9, D-06 a D-08).

## 9. Justificación del desacoplamiento

El prototipo guarda todo en el estado de React (`useReducer`) dentro de `index.html`. Eso viola la integridad del sistema por estas razones:

| # | Problema del almacenamiento en memoria volátil de JS | Regla que rompe |
|---|---|---|
| 1 | Al recargar la pestaña o cerrar el navegador se pierden todos los turnos. Una reserva confirmada deja de existir. | INV-03 (durabilidad) |
| 2 | Cada navegador tiene su propia copia. Dos clientes en dos dispositivos reservan el mismo slot y ambos reciben confirmación. La "concurrencia" del prototipo es simulada dentro de un único reducer. | INV-02 / RN-02 (atomicidad ante concurrencia) |
| 3 | Las reglas viven en JavaScript que el usuario puede inspeccionar y alterar desde la consola del navegador. La UI termina siendo la barrera de seguridad. | RBAC-01, INV-01 |
| 4 | El reloj es el del cliente (`s.now`, además adelantable por botones). La ventana de 2 h se evalúa contra una hora que el usuario controla. | INV-01 |
| 5 | No hay transacción: un fallo a mitad de `bookAppointment` puede dejar el turno sin su auditoría o el email sin su turno. | INV-03 (atomicidad), RN-08 |
| 6 | El botón "Reiniciar datos" borra el historial, que la spec declara inmutable. | RN-06 |

Con el desacoplamiento, la **única** fuente de verdad es la base de datos, la **única** autoridad que evalúa las reglas es el backend, y el frontend queda como un cliente que presenta JSON y muestra los errores de dominio.

## 10. Arquitectura de 3 capas

```
┌──────────────────────────┐   JSON / HTTP    ┌──────────────────────────────┐   SQL    ┌─────────────────────┐
│ Capa 1 · Frontend        │ ───────────────▶ │ Capa 2 · Backend             │ ───────▶ │ Capa 3 · Persistencia│
│ index.html               │ ◀─────────────── │ Python + FastAPI · :8000     │ ◀─────── │ SQLite · turnos.db   │
│ (React, sin reglas)      │   CORS "*"       │ Reglas INV-01 / INV-02       │          │ Índice único parcial │
└──────────────────────────┘                  └──────────────────────────────┘          └─────────────────────┘
```

### Capa 1 — Frontend

- Archivo: `index.html`. Se adapta en un paso posterior para consumir la API; **no forma parte de esta entrega**.
- Consume la API de spec §11 vía `fetch` con JSON. Base URL configurable (default `http://localhost:8000`).
- Se eliminan de él el reducer de reglas, la copia local de turnos y el reloj simulado como fuente de decisión. Muestra el `detail.code` y `detail.message` que devuelve el backend.

### Capa 2 — Backend

- Python + FastAPI, servido en el puerto **8000**, en un único archivo `backend/main.py` con tipado estricto (verificable con `mypy --strict`).
- CORS permisivo: `allow_origins=["*"]`.
- Reglas: **INV-02** (turno `CONFIRMADO` existente en el mismo `fecha_hora` → `409 HORARIO_NO_DISPONIBLE`) e **INV-01** (menos de 2 h hasta `fecha_hora` → `409 CANCELACION_FUERA_DE_VENTANA`; 2 h o más → `CANCELADO_CLIENTE`).
- Validación de entrada con modelos Pydantic; errores de dominio con el formato `{"detail": {"code", "message"}}` de spec §11.1.
- Reloj del servidor en UTC, aislado en una función (`ahora()`) para poder fijarlo en tests.

### Capa 3 — Persistencia

- SQLite (`sqlite3` nativo) en `turnos.db`. La tabla `turnos` se crea automáticamente al iniciar el servidor (lifespan).
- Una sola tabla, la de spec §11.7. INV-02 se refuerza en la base con un **índice único parcial** `(fecha_hora) WHERE estado = 'CONFIRMADO'`: dos solicitudes simultáneas por el mismo horario no pueden confirmarse a la vez.
- SQLite no ofrece `EXCLUDE USING gist` (D-04): el índice único es la alternativa admitida por RN-02. PostgreSQL queda como destino de producción.

## 11. Directiva de abstención (grounding)

Prohibido introducir cualquier elemento que no figure en spec §11.

| Permitido | Fuente |
|---|---|
| Tabla `turnos` con columnas `id, cliente_nombre, cliente_email, servicio, fecha_hora, estado` | spec §11.2, §11.7 |
| Índice único parcial sobre `fecha_hora` | spec §11.7 |
| Los tres endpoints de §11 y los códigos de error de §11.4 a §11.6 | spec §11 |
| Estados `CONFIRMADO` y `CANCELADO_CLIENTE` | spec §11.2 |

| Prohibido (ejemplos) | Motivo |
|---|---|
| Tablas `usuario`, `servicio`, `horario_laboral`, `bloqueo`, `auditoria_evento`, `sesion`, `token` | Fuera de la Fase 2 (spec §11, nota de alcance). |
| Endpoints distintos de los tres de spec §11 (borrar, editar, reiniciar datos) | Fuera de contrato; el historial es inmutable (RN-06). |
| Nombres de campo o de error distintos de los del spec (`SLOT_UNAVAILABLE`, `inicio`, `CANCELADO`) | En la API de la Fase 2 mandan los de spec §11. |

Si una necesidad técnica exige algo fuera de esa lista, se detiene el trabajo y se modifica primero la spec.

## 12. Estructura de archivos

```
turnos-prototipo-conceptual/
├── spec.md · plan.md · tareas.md · ...
├── index.html            # Capa 1 (se adapta después)
├── backend/
│   ├── main.py           # Capas 2 y 3: FastAPI, CORS, SQLite, reglas INV-01/INV-02
│   ├── test_main.py      # Tests de la API contra SQLite real
│   └── requirements.txt
├── backend-v0.2-archivado/   # Backend del modelo completo (6 tablas); no se usa en la Fase 2
└── turnos.db             # generado, no versionado
```

## 13. Orden de implementación

1. Actualizar spec.md, plan.md y tareas.md al modelo simplificado (hecho).
2. `main.py`: modelos Pydantic, base SQLite, reloj, endpoints.
3. Tests de INV-01 (límites 2 h y 1 h 59 min) e INV-02 (mismo horario, horario liberado tras cancelar).
4. Test de concurrencia: varias solicitudes simultáneas por el mismo `fecha_hora`, una sola gana.
5. Verificación de INV-03 con servidor real: crear, reiniciar uvicorn, listar.
6. Adaptar `index.html` para consumir la API y quitar la persistencia local.

## 14. Verificación de la Fase 2

| Criterio (spec §8) | Cómo se comprueba |
|---|---|
| 1, 2 (INV-02) | Tests contra la API con SQLite real, incluida concurrencia con hilos. |
| 5 (INV-01) | Tests con turnos a 3 h, a 2 h exactas y a 1 h 59 min. |
| 9 (persistencia) | Crear turno, detener y reiniciar `uvicorn`, `GET /api/turnos`. |
| 10 (atomicidad) | Forzar `HORARIO_NO_DISPONIBLE` y comprobar que no queda una segunda fila. |
| 11 | Cancelar vía API, reiniciar, comprobar estado y slot libre. |
| Grounding | Revisar el DDL de `main.py` contra spec §11.7. |
| Tipado | `mypy --strict main.py` sin errores. |

**Reloj.** INV-01 usa la hora del servidor (UTC). Para auditarlo sin esperar, los tests fijan `ahora()`; en ejecución real los turnos se crean con `fecha_hora` relativa a la hora actual.
