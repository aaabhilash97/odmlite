import os
import uuid

import pytest
from pymongo import AsyncMongoClient

from odmlite import AIOEngine

MONGO_URL = os.environ.get(
    "MONGO_URL", "mongodb://localhost:27017/?replicaSet=rs0&directConnection=true"
)


@pytest.fixture
async def client():
    c = AsyncMongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture
async def engine(client):
    name = f"odmlite_test_{uuid.uuid4().hex[:12]}"
    yield AIOEngine(client=client, database=name)
    await client.drop_database(name)
