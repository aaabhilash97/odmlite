"""``AIOEngine``: async persistence of odmlite models.

Works with pymongo's native async client (``pymongo.AsyncMongoClient``, preferred)
and, for gradual migrations, with a motor ``AsyncIOMotorClient``.
"""

from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Generator,
    Generic,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import pymongo.errors

from odmlite.exceptions import DocumentNotFoundError, DuplicateKeyError
from odmlite.field import FieldProxy
from odmlite.model import Model
from odmlite.query import QueryExpression, SortExpression

ModelType = TypeVar("ModelType", bound=Model)

_FORBIDDEN_DATABASE_CHARACTERS = set('/\\. "$*<>:|?')


class AIOCursor(Generic[ModelType]):
    """Result of ``engine.find``: ``await`` it for a list, or ``async for`` over it."""

    def __init__(self, model: Type[ModelType], cursor: Any):
        self._model = model
        self._cursor = cursor
        self._results: Optional[List[ModelType]] = None

    def _parse(self, raw_doc: Dict[str, Any]) -> ModelType:
        return self._model.model_validate_doc(raw_doc)

    def __await__(self) -> Generator[Any, None, List[ModelType]]:
        if self._results is not None:
            return self._results
        raw_docs = yield from self._cursor.to_list(None).__await__()
        self._results = [self._parse(doc) for doc in raw_docs]
        return self._results

    async def __aiter__(self) -> AsyncGenerator[ModelType, None]:
        if self._results is not None:
            for result in self._results:
                yield result
            return
        results: List[ModelType] = []
        async for raw_doc in self._cursor:
            instance = self._parse(raw_doc)
            results.append(instance)
            yield instance
        self._results = results


def _sort_spec(sort: Any) -> Optional[List[Tuple[str, int]]]:
    if sort is None:
        return None
    items = sort if isinstance(sort, (tuple, list)) else (sort,)
    spec: Dict[str, int] = {}
    for item in items:
        if isinstance(item, FieldProxy):
            spec[+item] = 1
        elif isinstance(item, dict):  # SortExpression or a plain {key: dir}
            spec.update(item)
        elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
            spec[item[0]] = item[1]
        else:
            raise TypeError(
                "sort has to be a Model field, an asc()/desc() expression, "
                "a (key, direction) pair, or a tuple/list of these"
            )
    return list(spec.items())


class AIOEngine:
    """Database operations for odmlite models.

    ``engine = AIOEngine(client=AsyncMongoClient(url), database="mydb")``
    """

    def __init__(self, client: Any = None, database: str = "test"):
        bad = _FORBIDDEN_DATABASE_CHARACTERS.intersection(database)
        if bad:
            raise ValueError(f"database name cannot contain: {' '.join(sorted(bad))}")
        if client is None:
            from pymongo import AsyncMongoClient

            client = AsyncMongoClient()
        self.client = client
        self.database_name = database
        self.database = client[database]

    def get_collection(self, model: Type[Model]) -> Any:
        """The driver collection behind a model."""
        return self.database[model.__collection__]

    @staticmethod
    def _get_session(session: Any) -> Any:
        from odmlite.session import AIOSession, AIOTransaction

        if isinstance(session, (AIOSession, AIOTransaction)):
            return session.get_driver_session()
        return session

    @staticmethod
    def _build_query(*queries: Union[QueryExpression, Dict[str, Any], bool]) -> Dict[str, Any]:
        for q in queries:
            if isinstance(q, bool):
                raise TypeError("cannot build query using booleans")
        if not queries:
            return {}
        if len(queries) == 1:
            return dict(queries[0])  # type: ignore[arg-type]
        return {"$and": list(queries)}

    def session(self) -> "AIOSession":
        from odmlite.session import AIOSession

        return AIOSession(self)

    def transaction(self) -> "AIOTransaction":
        """``async with engine.transaction() as txn:`` commits on success, aborts on error.

        Transactions need a replica set or sharded cluster.
        """
        from odmlite.session import AIOTransaction

        return AIOTransaction(self)

    def find(
        self,
        model: Type[ModelType],
        *queries: Union[QueryExpression, Dict[str, Any], bool],
        sort: Any = None,
        skip: int = 0,
        limit: Optional[int] = None,
        session: Any = None,
    ) -> AIOCursor[ModelType]:
        if not (isinstance(model, type) and issubclass(model, Model)):
            raise TypeError("Can only call find with a Model class")
        if limit is not None and limit <= 0:
            raise ValueError("limit has to be a strict positive value or None")
        if skip < 0:
            raise ValueError("skip has to be a positive integer")
        kwargs: Dict[str, Any] = {}
        spec = _sort_spec(sort)
        if spec:
            kwargs["sort"] = spec
        if skip:
            kwargs["skip"] = skip
        if limit:
            kwargs["limit"] = limit
        driver_session = self._get_session(session)
        if driver_session is not None:
            kwargs["session"] = driver_session
        cursor = self.get_collection(model).find(self._build_query(*queries), **kwargs)
        return AIOCursor(model, cursor)

    async def find_one(
        self,
        model: Type[ModelType],
        *queries: Union[QueryExpression, Dict[str, Any], bool],
        sort: Any = None,
        session: Any = None,
    ) -> Optional[ModelType]:
        if not (isinstance(model, type) and issubclass(model, Model)):
            raise TypeError("Can only call find_one with a Model class")
        results = await self.find(model, *queries, sort=sort, limit=1, session=session)
        return results[0] if results else None

    async def _save(self, instance: ModelType, driver_session: Any) -> ModelType:
        fields = set(instance.__fields_modified__) | set(type(instance).__mutable_fields__)
        if fields:
            doc = instance.model_dump_doc(include=fields)
            kwargs: Dict[str, Any] = {"upsert": True}
            if driver_session is not None:
                kwargs["session"] = driver_session
            try:
                await self.get_collection(type(instance)).update_one(
                    {"_id": instance.id}, {"$set": doc}, **kwargs
                )
            except pymongo.errors.DuplicateKeyError as exc:
                raise DuplicateKeyError(instance, exc) from exc
            instance._odm_modified = set()
        return instance

    async def save(self, instance: ModelType, *, session: Any = None) -> ModelType:
        """Upsert ``instance``: ``$set`` its modified (and mutable) fields only."""
        if not isinstance(instance, Model):
            raise TypeError("Can only call save with a Model instance")
        return await self._save(instance, self._get_session(session))

    async def save_all(self, instances: Sequence[ModelType], *, session: Any = None) -> List[ModelType]:
        driver_session = self._get_session(session)
        return [await self._save(instance, driver_session) for instance in instances]

    async def delete(self, instance: Model, *, session: Any = None) -> None:
        kwargs: Dict[str, Any] = {}
        driver_session = self._get_session(session)
        if driver_session is not None:
            kwargs["session"] = driver_session
        result = await self.get_collection(type(instance)).delete_many({"_id": instance.id}, **kwargs)
        if int(result.deleted_count) == 0:
            raise DocumentNotFoundError(instance)

    async def remove(
        self,
        model: Type[Model],
        *queries: Union[QueryExpression, Dict[str, Any], bool],
        just_one: bool = False,
        session: Any = None,
    ) -> int:
        kwargs: Dict[str, Any] = {}
        driver_session = self._get_session(session)
        if driver_session is not None:
            kwargs["session"] = driver_session
        collection = self.get_collection(model)
        query = self._build_query(*queries)
        if just_one:
            result = await collection.delete_one(query, **kwargs)
        else:
            result = await collection.delete_many(query, **kwargs)
        return int(result.deleted_count)

    async def count(
        self,
        model: Type[Model],
        *queries: Union[QueryExpression, Dict[str, Any], bool],
        session: Any = None,
    ) -> int:
        if not (isinstance(model, type) and issubclass(model, Model)):
            raise TypeError("Can only call count with a Model class")
        kwargs: Dict[str, Any] = {}
        driver_session = self._get_session(session)
        if driver_session is not None:
            kwargs["session"] = driver_session
        return int(await self.get_collection(model).count_documents(self._build_query(*queries), **kwargs))


from odmlite.session import AIOSession, AIOTransaction  # noqa: E402  (re-export, avoids a cycle)
