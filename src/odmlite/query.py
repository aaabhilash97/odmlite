"""Query and sort expressions built from field proxies (``Model.field == value``)."""

import re
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterable, Literal, Pattern, Union

if TYPE_CHECKING:
    from odmlite.field import FieldProxy


class QueryExpression(Dict[str, Any]):
    """A MongoDB filter. ``|`` and ``&`` combine expressions with ``$or`` / ``$and``."""

    def __repr__(self) -> str:
        return f"QueryExpression({super().__repr__()})"

    def __or__(self, other: Any) -> "QueryExpression":  # type: ignore[override]
        return or_(self, other)

    def __and__(self, other: Any) -> "QueryExpression":
        return and_(self, other)


def and_(*elements: Any) -> QueryExpression:
    return QueryExpression({"$and": list(elements)})


def or_(*elements: Any) -> QueryExpression:
    return QueryExpression({"$or": list(elements)})


def nor_(*elements: Any) -> QueryExpression:
    return QueryExpression({"$nor": list(elements)})


def _query_value(value: Any) -> Any:
    from odmlite.model import EmbeddedModel

    if isinstance(value, EmbeddedModel):
        return value.model_dump_doc()
    if isinstance(value, Enum):
        return value.value
    return value


def _cmp(field: "FieldProxy", op: str, value: Any) -> QueryExpression:
    return QueryExpression({+field: {op: _query_value(value)}})


def eq(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$eq", value)


def ne(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$ne", value)


def gt(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$gt", value)


def gte(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$gte", value)


def lt(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$lt", value)


def lte(field: "FieldProxy", value: Any) -> QueryExpression:
    return _cmp(field, "$lte", value)


def in_(field: "FieldProxy", values: Iterable[Any]) -> QueryExpression:
    return _cmp(field, "$in", [_query_value(v) for v in values])


def not_in(field: "FieldProxy", values: Iterable[Any]) -> QueryExpression:
    return _cmp(field, "$nin", [_query_value(v) for v in values])


def match(field: "FieldProxy", pattern: Union[Pattern[str], str]) -> QueryExpression:
    return QueryExpression({+field: re.compile(pattern) if isinstance(pattern, str) else pattern})


class SortExpression(Dict[str, Literal[-1, 1]]):
    """Ordered ``{key: 1 | -1}`` sort specification."""

    def __repr__(self) -> str:
        return f"SortExpression({super().__repr__()})"


def asc(field: "FieldProxy") -> SortExpression:
    return SortExpression({+field: 1})


def desc(field: "FieldProxy") -> SortExpression:
    return SortExpression({+field: -1})
