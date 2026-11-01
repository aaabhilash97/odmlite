from typing import Any


class BaseEngineException(Exception):
    """Base class for engine errors."""


class DocumentNotFoundError(BaseEngineException):
    """The targeted document was not found in the database."""

    def __init__(self, instance: Any):
        self.instance = instance
        super().__init__(
            f"Document not found for: {type(instance).__name__}. "
            f"Instance: {instance!r}"
        )


class DuplicateKeyError(BaseEngineException):
    """The operation violated a unique index."""

    def __init__(self, instance: Any, driver_error: Exception):
        self.instance = instance
        self.model = type(instance)
        self.driver_error = driver_error
        super().__init__(
            f"Duplicate key error on: {self.model.__name__}. Instance: {instance!r}"
        )


class DocumentParsingError(ValueError):
    """A document read from the database doesn't match the model."""

    def __init__(self, model: type, errors: Any):
        self.model = model
        self.errors = errors
        super().__init__(f"{model.__name__}: failed to parse document: {errors}")
