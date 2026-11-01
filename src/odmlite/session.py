"""Sessions and transactions, shaped like odmantic's ``AIOSession`` / ``AIOTransaction``.

``transaction.session.session`` is the driver session, so raw driver calls can join
the transaction with ``session=txn.session.session``.

Note: ``transaction.engine`` is the plain engine and is *not* bound to the session
(as in odmantic). Use ``txn.find(...)`` / ``txn.save(...)``, or pass ``session=txn``,
to run an operation inside the transaction.
"""

import inspect
from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Type, Union

if TYPE_CHECKING:
    from odmlite.engine import AIOCursor, AIOEngine
    from odmlite.model import Model


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class _SessionOps:
    engine: "AIOEngine"

    def find(self, model: Type["Model"], *queries: Any, sort: Any = None, skip: int = 0, limit: Optional[int] = None) -> "AIOCursor[Any]":
        return self.engine.find(model, *queries, sort=sort, skip=skip, limit=limit, session=self)

    async def find_one(self, model: Type["Model"], *queries: Any, sort: Any = None) -> Any:
        return await self.engine.find_one(model, *queries, sort=sort, session=self)

    async def count(self, model: Type["Model"], *queries: Any) -> int:
        return await self.engine.count(model, *queries, session=self)

    async def save(self, instance: "Model") -> "Model":
        return await self.engine.save(instance, session=self)

    async def save_all(self, instances: Sequence["Model"]) -> List["Model"]:
        return await self.engine.save_all(instances, session=self)

    async def delete(self, instance: "Model") -> None:
        await self.engine.delete(instance, session=self)

    async def remove(self, model: Type["Model"], *queries: Any, just_one: bool = False) -> int:
        return await self.engine.remove(model, *queries, just_one=just_one, session=self)


class AIOSession(_SessionOps):
    def __init__(self, engine: "AIOEngine"):
        self.engine = engine
        self.session: Any = None

    @property
    def is_started(self) -> bool:
        return self.session is not None

    def get_driver_session(self) -> Any:
        if self.session is None:
            raise RuntimeError("session not started")
        return self.session

    async def start(self) -> None:
        if self.session is not None:
            raise RuntimeError("session already started")
        # pymongo async: start_session() is sync; motor: it's a coroutine.
        self.session = await _maybe_await(self.engine.client.start_session())

    async def end(self) -> None:
        if self.session is None:
            raise RuntimeError("session not started")
        await _maybe_await(self.session.end_session())
        self.session = None

    async def __aenter__(self) -> "AIOSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]) -> None:
        await self.end()

    def transaction(self) -> "AIOTransaction":
        return AIOTransaction(self)


class AIOTransaction(_SessionOps):
    def __init__(self, context: Union["AIOEngine", AIOSession]):
        if isinstance(context, AIOSession):
            self.session = context
            self.engine = context.engine
            self._owns_session = False
        else:
            self.session = AIOSession(context)
            self.engine = context
            self._owns_session = True
        self._transaction_context: Any = None

    @property
    def is_started(self) -> bool:
        return self._transaction_context is not None

    def get_driver_session(self) -> Any:
        return self.session.get_driver_session()

    async def start(self) -> None:
        if self.is_started:
            raise RuntimeError("transaction already started")
        if not self.session.is_started:
            await self.session.start()
        # pymongo async: start_transaction() is a coroutine returning the context;
        # motor: it returns the context directly.
        context = await _maybe_await(self.session.session.start_transaction())
        await context.__aenter__()
        self._transaction_context = context

    async def _finish(self) -> None:
        self._transaction_context = None
        if self._owns_session and self.session.is_started:
            await self.session.end()

    async def commit(self) -> None:
        if not self.is_started:
            raise RuntimeError("transaction not started")
        await self.session.session.commit_transaction()
        await self._finish()

    async def abort(self) -> None:
        if not self.is_started:
            raise RuntimeError("transaction not started")
        await self.session.session.abort_transaction()
        await self._finish()

    async def __aenter__(self) -> "AIOTransaction":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]) -> None:
        context = self._transaction_context
        if context is None:  # already committed or aborted explicitly
            return
        try:
            # Commits if the transaction is still active and no exception was raised;
            # aborts on exception.
            await context.__aexit__(exc_type, exc, tb)
        finally:
            await self._finish()
