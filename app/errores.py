"""Errores de dominio (catálogo spec §7)."""


class DomainError(Exception):
    """Violación de una regla de negocio; la capa API la responde como `{"error": code, "detalle": detail}`."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status, self.code, self.detail = status, code, detail


def slot_unavailable(detail: str) -> DomainError:
    """409 SLOT_UNAVAILABLE (RN-02)."""
    return DomainError(409, "SLOT_UNAVAILABLE", detail)


def not_found(detail: str = "Recurso no encontrado.") -> DomainError:
    """404 NOT_FOUND. También se usa para recursos ajenos (RBAC-02)."""
    return DomainError(404, "NOT_FOUND", detail)
