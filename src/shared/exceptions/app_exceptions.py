"""Typed application exceptions that map business and infrastructure failures to API error codes."""

class AppException(Exception):
    http_status: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None, process_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.process_id = process_id


class TextTooShortError(AppException):
    http_status = 400
    error_code = "TEXT_TOO_SHORT"


class TextTooLongError(AppException):
    http_status = 400
    error_code = "TEXT_TOO_LONG"


class InvalidAPIKeyError(AppException):
    http_status = 401
    error_code = "INVALID_API_KEY"


class AnonymizationValidationError(AppException):
    http_status = 400
    error_code = "ANONYMIZATION_ERROR"


class ProcessNotFoundError(AppException):
    http_status = 404
    error_code = "PROCESS_NOT_FOUND"


class ProcessingTimeoutError(AppException):
    http_status = 408
    error_code = "PROCESSING_TIMEOUT"


class NLPProviderError(AppException):
    http_status = 502
    error_code = "NLP_PROVIDER_ERROR"


class ServiceUnavailableError(AppException):
    http_status = 503
    error_code = "SERVICE_UNAVAILABLE"
