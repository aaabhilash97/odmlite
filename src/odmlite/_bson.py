"""Pydantic support for ``bson.ObjectId``.

Models annotate fields with plain ``bson.ObjectId``. Rather than rewriting class
annotations (which breaks under Python 3.14's deferred annotations, PEP 649), we
teach pydantic how to validate ``bson.ObjectId`` directly: ObjectId instances pass
through, 24-char hex strings / 12-byte values are converted, anything else is
rejected. In JSON mode it serializes to its hex string; in python mode it stays an
ObjectId so documents written to MongoDB keep the native type.
"""

from typing import Any

import bson
import bson.errors
from pydantic_core import core_schema


def _validate_object_id(value: Any) -> bson.ObjectId:
    if isinstance(value, bson.ObjectId):
        return value
    if isinstance(value, (str, bytes)):
        try:
            return bson.ObjectId(value)
        except (bson.errors.InvalidId, TypeError) as exc:
            raise ValueError("Invalid ObjectId") from exc
    raise ValueError("Invalid ObjectId")


def _object_id_core_schema(cls: type, source: Any, handler: Any) -> core_schema.CoreSchema:
    return core_schema.no_info_plain_validator_function(
        _validate_object_id,
        serialization=core_schema.plain_serializer_function_ser_schema(
            str, when_used="json"
        ),
        json_schema_input_schema=core_schema.str_schema(),
    )


def install_object_id_schema() -> None:
    """Register the schema hook on ``bson.ObjectId`` unless something already did."""
    if "__get_pydantic_core_schema__" not in vars(bson.ObjectId):
        bson.ObjectId.__get_pydantic_core_schema__ = classmethod(_object_id_core_schema)  # type: ignore[attr-defined]


ObjectId = bson.ObjectId
