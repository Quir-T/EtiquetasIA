"""Base domain exceptions used to classify validation, provider and persistence failures."""

class DomainException(Exception):
    pass


class ValidationError(DomainException):
    pass


class AnonymizationError(DomainException):
    pass


class ProviderError(DomainException):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class PersistenceError(DomainException):
    pass
