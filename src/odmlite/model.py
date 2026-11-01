"""``Model`` / ``EmbeddedModel``: pydantic v2 models that map to MongoDB documents.

Compatibility notes (odmantic semantics this module keeps):

- ``Model`` gets an ``id: ObjectId`` primary key stored as ``_id``.
- The collection comes from ``model_config = {"collection": ...}`` (odmantic 1.x) or
  a legacy ``class Config: collection = ...`` (odmantic 0.x); otherwise the class
  name in snake_case, minus a trailing ``Model``.
- ``Model.field`` on the class is a ``FieldProxy`` (``+Model.field`` → key name).
- Assignments are tracked; ``engine.save`` only ``$set``s modified fields plus fields
  of mutable types, so keys the model doesn't declare are never touched.
- ``validate_assignment`` and ``validate_default`` are on by default, as in odmantic.

Field discovery happens through pydantic itself, after the class is built, so it
works with Python 3.14's deferred annotations (PEP 649).
"""

import datetime
import decimal
import enum
import pathlib
import re
import types
import uuid
from typing import (
    Annotated,
    Any,
    ClassVar,
    Dict,
    FrozenSet,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

import bson
import pydantic
from pydantic import PrivateAttr, ValidationError, model_validator

from odmlite._bson import install_object_id_schema
from odmlite.exceptions import DocumentParsingError
from odmlite.field import FieldProxy, _odm_model_of

install_object_id_schema()

_PydanticModelMetaclass = type(pydantic.BaseModel)

# odmantic-only config keys we accept and drop (they aren't pydantic options).
_ODM_ONLY_CONFIG_KEYS = ("collection", "parse_doc_with_default_factories", "indexes")

_IMMUTABLE_TYPES: Tuple[type, ...] = (
    type(None),
    bool,
    int,
    float,
    str,
    bytes,
    tuple,
    frozenset,
    datetime.date,
    datetime.time,
    datetime.datetime,
    datetime.timedelta,
    enum.Enum,
    decimal.Decimal,
    pathlib.Path,
    uuid.UUID,
    bson.ObjectId,
    bson.Decimal128,
)


def _is_mutable_type(type_: Any) -> bool:
    """Whether values of this type can change in place (and so are always saved)."""
    if type_ is None:
        return False
    origin = get_origin(type_)
    if origin is Annotated:
        return _is_mutable_type(get_args(type_)[0])
    if origin is Literal:
        return False
    if origin is not None:
        if any(_is_mutable_type(arg) for arg in get_args(type_) if arg is not ...):
            return True
        if origin is Union or origin is types.UnionType:
            return False
        return not (isinstance(origin, type) and issubclass(origin, _IMMUTABLE_TYPES))
    if isinstance(type_, type):
        if issubclass(type_, EmbeddedModel):
            return True
        if issubclass(type_, pydantic.BaseModel):
            return False
        return not issubclass(type_, _IMMUTABLE_TYPES)
    # Any, object-like annotations, TypeVars...
    return True


def _to_snake_case(name: str) -> str:
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


_ENFORCED_DEFAULTS = {"validate_assignment": True, "validate_default": True}


class _ODMModelMetaclass(_PydanticModelMetaclass):
    def __new__(mcs, name: str, bases: Tuple[type, ...], namespace: Dict[str, Any], **kwargs: Any):  # noqa: N804
        is_library_base = namespace.get("__module__") == __name__
        collection: Optional[str] = None

        if not is_library_base:
            config: Dict[str, Any] = {}
            # odmantic 0.x / pydantic v1 style: class Config: collection = "..."
            legacy = namespace.pop("Config", None)
            if isinstance(legacy, type):
                for key, value in vars(legacy).items():
                    if not key.startswith("__"):
                        config[key] = value
            declared = namespace.get("model_config")
            if isinstance(declared, dict):
                config.update(declared)
            collection = config.get("collection")
            for key in _ODM_ONLY_CONFIG_KEYS:
                config.pop(key, None)
            for key, value in _ENFORCED_DEFAULTS.items():
                config.setdefault(key, value)
            namespace["model_config"] = pydantic.ConfigDict(**config)  # type: ignore[typeddict-item]
            # A ClassVar annotation on model_config (common with odmantic) is redundant.
            annotations = namespace.get("__annotations__")
            if isinstance(annotations, dict):
                annotations.pop("model_config", None)

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        if not is_library_base:
            if issubclass(cls, Model):
                if collection is None:
                    inherited = next(
                        (getattr(b, "__odm_declared_collection__", None) for b in bases),
                        None,
                    )
                    collection = inherited
                cls.__odm_declared_collection__ = collection
                if collection is None:
                    base_name = name[:-5] if name.endswith("Model") and name != "Model" else name
                    collection = _to_snake_case(base_name)
                if not collection or "$" in collection or collection.startswith("system."):
                    raise TypeError(f"{name}: invalid collection name {collection!r}")
                cls.__collection__ = collection
            cls.__mutable_fields__ = frozenset(
                field_name
                for field_name, field in cls.model_fields.items()
                if _is_mutable_type(field.annotation)
            )
            # Only now may Model.field resolve to a FieldProxy: while pydantic builds the
            # class it probes getattr(cls, field) for defaults and must get AttributeError.
            cls.__odm_ready__ = True
        return cls

    def __getattr__(cls, item: str) -> Any:
        # Model.field on the class -> FieldProxy. Pydantic doesn't keep field defaults
        # as class attributes, so this only runs for fields (and genuinely missing names).
        if not item.startswith("__") and type.__getattribute__(cls, "__dict__").get("__odm_ready__"):
            try:
                fields = type.__getattribute__(cls, "__pydantic_fields__")
            except AttributeError:
                fields = None
            if fields and item in fields:
                key_name = "_id" if item == "id" and issubclass(cls, Model) else item
                return FieldProxy(None, item, _odm_model_of(fields[item].annotation), key_name)
        return super().__getattr__(item)  # type: ignore[misc]

    def __pos__(cls) -> str:
        """``+Model`` -> collection name."""
        return getattr(cls, "__collection__", "")


BaseT = TypeVar("BaseT", bound="_BaseODMModel")


class _BaseODMModel(pydantic.BaseModel, metaclass=_ODMModelMetaclass):
    if False:  # pragma: no cover - typing only
        __mutable_fields__: ClassVar[FrozenSet[str]] = frozenset()

    _odm_modified: Set[str] = PrivateAttr(default_factory=set)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # A freshly constructed instance has every field to persist.
        self._odm_modified = set(type(self).model_fields)

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name in type(self).model_fields:
            self._odm_modified.add(name)

    @property
    def __fields_modified__(self) -> Set[str]:
        return self._odm_modified

    def __eq__(self, other: Any) -> bool:
        # Compare data only: change tracking is bookkeeping, so a new instance equals
        # the same document loaded back from the database (pydantic's default __eq__
        # would also compare private attributes).
        if not isinstance(other, pydantic.BaseModel):
            return NotImplemented
        return (
            type(self) is type(other)
            and self.__dict__ == other.__dict__
            and self.__pydantic_extra__ == other.__pydantic_extra__
        )

    __hash__ = None  # type: ignore[assignment]

    def model_copy(self: BaseT, *, update: Optional[Dict[str, Any]] = None, deep: bool = False) -> BaseT:
        copied = super().model_copy(update=update, deep=deep)
        copied._odm_modified = set(type(self).model_fields)
        return copied

    def model_dump_doc(self, include: Optional[Set[str]] = None) -> Dict[str, Any]:
        """The BSON document for this instance (``id`` stored as ``_id`` on Models)."""
        doc = self.model_dump(include=include)
        if isinstance(self, Model) and "id" in doc:
            doc["_id"] = doc.pop("id")
        return doc

    def doc(self, include: Optional[Set[str]] = None) -> Dict[str, Any]:
        """Alias of ``model_dump_doc`` (odmantic compatibility)."""
        return self.model_dump_doc(include=include)

    @classmethod
    def model_validate_doc(cls: Type[BaseT], raw_doc: Dict[str, Any]) -> BaseT:
        """Build an instance from a raw MongoDB document."""
        try:
            instance = cls.model_validate(raw_doc)
        except ValidationError as exc:
            raise DocumentParsingError(cls, exc.errors()) from exc
        instance._odm_modified = set()
        return instance

    @classmethod
    def parse_doc(cls: Type[BaseT], raw_doc: Dict[str, Any]) -> BaseT:
        """Alias of ``model_validate_doc`` (odmantic compatibility)."""
        return cls.model_validate_doc(raw_doc)


class EmbeddedModel(_BaseODMModel):
    """A model stored inside another document."""


class Model(_BaseODMModel):
    """A model stored in its own collection, keyed by ``id`` (``_id``)."""

    if False:  # pragma: no cover - typing only
        __collection__: ClassVar[str] = ""

    id: bson.ObjectId = pydantic.Field(default_factory=bson.ObjectId)

    @model_validator(mode="before")
    @classmethod
    def _map_mongo_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "_id" in data and "id" not in data:
            data = dict(data)
            data["id"] = data.pop("_id")
        return data

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "id":
            raise NotImplementedError("Reassigning a new primary key is not supported")
        super().__setattr__(name, value)
