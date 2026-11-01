"""Field proxies: what ``Model.field`` evaluates to on a model *class*.

``+Model.field`` gives the stored key name, ``Model.a.b`` walks into embedded
models (``"a.b"``), and comparison operators build query expressions.
"""

from typing import TYPE_CHECKING, Any, Iterable, Optional, Pattern, Type, Union

import pydantic

from odmlite import query

if TYPE_CHECKING:
    from odmlite.model import _BaseODMModel


class KeyName(str):
    """The dotted key of a field, as used in raw MongoDB filters and updates."""


class FieldProxy:
    __slots__ = ("_parent", "_name", "_model", "_key_name")

    def __init__(
        self,
        parent: Optional["FieldProxy"],
        name: str,
        model: Optional[Type["_BaseODMModel"]],
        key_name: Optional[str] = None,
    ) -> None:
        object.__setattr__(self, "_parent", parent)
        object.__setattr__(self, "_name", name)
        # Stored key when it differs from the attribute name (Model.id -> "_id").
        object.__setattr__(self, "_key_name", key_name or name)
        # Set when the field holds an odmlite model, so Model.a.b can resolve "a.b".
        object.__setattr__(self, "_model", model)

    def _key(self) -> str:
        parent = object.__getattribute__(self, "_parent")
        key_name = object.__getattribute__(self, "_key_name")
        return key_name if parent is None else f"{parent._key()}.{key_name}"

    def __getattribute__(self, name: str) -> Any:
        # Sub-fields of an embedded model take precedence over the operator methods.
        model = object.__getattribute__(self, "_model")
        if model is not None and not name.startswith("__"):
            fields = model.model_fields
            if name in fields:
                return FieldProxy(self, name, _odm_model_of(fields[name].annotation))
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("FieldProxy is read-only")

    def __repr__(self) -> str:
        return f"FieldProxy({self._key()!r})"

    def __pos__(self) -> KeyName:
        return KeyName(self._key())

    def __eq__(self, value: Any) -> query.QueryExpression:  # type: ignore[override]
        return query.eq(self, value)

    def __ne__(self, value: Any) -> query.QueryExpression:  # type: ignore[override]
        return query.ne(self, value)

    def __gt__(self, value: Any) -> query.QueryExpression:
        return query.gt(self, value)

    def __ge__(self, value: Any) -> query.QueryExpression:
        return query.gte(self, value)

    def __lt__(self, value: Any) -> query.QueryExpression:
        return query.lt(self, value)

    def __le__(self, value: Any) -> query.QueryExpression:
        return query.lte(self, value)

    __hash__ = None  # type: ignore[assignment]

    def eq(self, value: Any) -> query.QueryExpression:
        return query.eq(self, value)

    def ne(self, value: Any) -> query.QueryExpression:
        return query.ne(self, value)

    def gt(self, value: Any) -> query.QueryExpression:
        return query.gt(self, value)

    def gte(self, value: Any) -> query.QueryExpression:
        return query.gte(self, value)

    def lt(self, value: Any) -> query.QueryExpression:
        return query.lt(self, value)

    def lte(self, value: Any) -> query.QueryExpression:
        return query.lte(self, value)

    def in_(self, values: Iterable[Any]) -> query.QueryExpression:
        return query.in_(self, values)

    def not_in(self, values: Iterable[Any]) -> query.QueryExpression:
        return query.not_in(self, values)

    def match(self, pattern: Union[Pattern[str], str]) -> query.QueryExpression:
        return query.match(self, pattern)

    def asc(self) -> query.SortExpression:
        return query.asc(self)

    def desc(self) -> query.SortExpression:
        return query.desc(self)


def _odm_model_of(annotation: Any) -> Optional[Type["_BaseODMModel"]]:
    """The odmlite model class held by a field, unwrapping Optional/Annotated."""
    from typing import Annotated, Union, get_args, get_origin
    import types

    from odmlite.model import _BaseODMModel

    origin = get_origin(annotation)
    if origin is Annotated:
        return _odm_model_of(get_args(annotation)[0])
    if origin is Union or origin is types.UnionType:
        candidates = [a for a in get_args(annotation) if a is not type(None)]
        if len(candidates) == 1:
            return _odm_model_of(candidates[0])
        return None
    if isinstance(annotation, type) and issubclass(annotation, _BaseODMModel):
        return annotation
    return None


_UNSUPPORTED_FIELD_ARGS = ("primary_field", "key_name", "index", "unique")


def Field(default: Any = ..., **kwargs: Any) -> Any:
    """``pydantic.Field``. odmantic-only options aren't supported by odmlite."""
    unsupported = [k for k in _UNSUPPORTED_FIELD_ARGS if k in kwargs]
    if unsupported:
        raise NotImplementedError(
            f"odmlite.Field does not support {', '.join(unsupported)}"
        )
    return pydantic.Field(default, **kwargs)
