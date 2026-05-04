"""Structured exception hierarchy for STAR-ASN.

Provides domain-specific exceptions with proper error classification
for better error handling and observability.
"""

from __future__ import annotations

from typing import Any


class StarAsnError(Exception):
    """Base exception for all STAR-ASN domain errors."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


# === Configuration Errors ===


class ConfigurationError(StarAsnError):
    """Raised when there's a configuration-related error."""

    pass


class MissingEnvironmentVariableError(ConfigurationError):
    """Raised when a required environment variable is missing."""

    def __init__(self, var_name: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"Missing required environment variable: {var_name}", details=details)
        self.var_name = var_name


# === Authentication & Security Errors ===


class AuthenticationError(StarAsnError):
    """Raised when authentication fails."""

    pass


class InvalidCredentialsError(AuthenticationError):
    """Raised when provided credentials are invalid."""

    pass


class TokenValidationError(AuthenticationError):
    """Raised when token validation fails."""

    pass


class SecurityError(StarAsnError):
    """Raised for general security violations."""

    pass


# === Database Errors ===


class DatabaseError(StarAsnError):
    """Raised for database-related errors."""

    pass


class ConnectionError(DatabaseError):
    """Raised when database connection fails."""

    pass


class QueryError(DatabaseError):
    """Raised when a database query fails."""

    def __init__(self, message: str, *, query: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.query = query


class SchemaError(DatabaseError):
    """Raised when database schema validation fails."""

    pass


# === External Service Errors ===


class ExternalServiceError(StarAsnError):
    """Raised when an external service call fails."""

    def __init__(self, message: str, *, service: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.service = service


class PortalError(ExternalServiceError):
    """Raised when STAR portal interaction fails."""

    def __init__(self, message: str, *, status_code: int | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, service="star_portal", details=details)
        self.status_code = status_code


class CaptchaError(ExternalServiceError):
    """Raised when CAPTCHA solving fails."""

    def __init__(self, message: str, *, attempts: int | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, service="captcha_solver", details=details)
        self.attempts = attempts


class TelegramError(ExternalServiceError):
    """Raised when Telegram API call fails."""

    def __init__(self, message: str, *, chat_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, service="telegram", details=details)
        self.chat_id = chat_id


# === Business Logic Errors ===


class BusinessLogicError(StarAsnError):
    """Raised for business logic violations."""

    pass


class UserNotFoundError(BusinessLogicError):
    """Raised when a user is not found in the database."""

    def __init__(self, nip: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(f"User with NIP {nip} not found", details=details)
        self.nip = nip


class InvalidScheduleError(BusinessLogicError):
    """Raised when a schedule configuration is invalid."""

    pass


class AttendanceError(BusinessLogicError):
    """Raised when attendance processing fails."""

    def __init__(
        self, message: str, *, nip: str | None = None, action: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, details=details)
        self.nip = nip
        self.action = action


# === Validation Errors ===


class ValidationError(StarAsnError):
    """Raised when input validation fails."""

    def __init__(self, message: str, *, field: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.field = field


# === Worker/Queue Errors ===


class WorkerError(StarAsnError):
    """Raised when worker processing fails."""

    pass


class QueueError(StarAsnError):
    """Raised when queue operation fails."""

    pass


# === Circuit Breaker Errors ===


class CircuitBreakerError(StarAsnError):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, *, service: str, cooldown_remaining: float | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.cooldown_remaining = cooldown_remaining
