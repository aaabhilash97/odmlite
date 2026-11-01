"""odmlite: a small async MongoDB ODM on pydantic v2 and pymongo.

It implements the commonly used subset of odmantic's API, so code written for
odmantic usually only needs its imports changed.
"""

from odmlite import query, session
from odmlite._bson import ObjectId
from odmlite.engine import AIOCursor, AIOEngine
from odmlite.exceptions import (
    DocumentNotFoundError,
    DocumentParsingError,
    DuplicateKeyError,
)
from odmlite.field import Field, FieldProxy
from odmlite.model import EmbeddedModel, Model
from odmlite.session import AIOSession, AIOTransaction

__version__ = "0.1.0"

__all__ = [
    "AIOCursor",
    "AIOEngine",
    "AIOSession",
    "AIOTransaction",
    "DocumentNotFoundError",
    "DocumentParsingError",
    "DuplicateKeyError",
    "EmbeddedModel",
    "Field",
    "FieldProxy",
    "Model",
    "ObjectId",
    "query",
    "session",
]
