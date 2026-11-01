"""The engine also works with a motor client, to allow switching drivers separately."""

import uuid

import pytest

from odmlite import AIOEngine, Model

motor_asyncio = pytest.importorskip("motor.motor_asyncio")

from tests.conftest import MONGO_URL  # noqa: E402


class Note(Model):
    model_config = {"collection": "notes"}
    text: str = ""


async def test_engine_with_motor_client():
    client = motor_asyncio.AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    name = f"odmlite_motor_{uuid.uuid4().hex[:12]}"
    engine = AIOEngine(client=client, database=name)
    try:
        await engine.save(Note(text="hi"))
        assert [n.text async for n in engine.find(Note)] == ["hi"]
        async with engine.transaction() as txn:
            await txn.save(Note(text="txn"))
        assert await engine.count(Note) == 2
    finally:
        await client.drop_database(name)
        client.close()
