"""Engine behaviour against a real MongoDB replica set."""

from typing import List, Optional

import bson
import pytest
from pymongo import ReturnDocument

from odmlite import AIOTransaction, DocumentNotFoundError, EmbeddedModel, Model
from odmlite.query import desc


class Limits(EmbeddedModel):
    max_amount: float = 0


class Partner(Model):
    model_config = {"collection": "partners"}

    name: str
    priority: int = 0
    enabled: bool = True
    limits: Limits = Limits()
    nbfc_ids: List[bson.ObjectId] = []
    note: Optional[str] = None


async def _raw(engine, model, _id):
    return await engine.get_collection(model).find_one({"_id": _id})


async def test_save_new_instance_writes_all_fields(engine):
    p = Partner(name="acme", priority=2)
    await engine.save(p)
    raw = await _raw(engine, Partner, p.id)
    assert raw == {
        "_id": p.id,
        "name": "acme",
        "priority": 2,
        "enabled": True,
        "limits": {"max_amount": 0},
        "nbfc_ids": [],
        "note": None,
    }
    assert p.__fields_modified__ == set()


async def test_save_preserves_undeclared_fields(engine):
    # Shared collections hold keys other services own; save must never drop them.
    _id = bson.ObjectId()
    await engine.get_collection(Partner).insert_one(
        {"_id": _id, "name": "acme", "priority": 1, "owned_by_go_service": {"x": 1}}
    )
    p = await engine.find_one(Partner, {+Partner.id: _id})
    p.priority = 5
    await engine.save(p)
    raw = await _raw(engine, Partner, _id)
    assert raw["owned_by_go_service"] == {"x": 1}
    assert raw["priority"] == 5


async def test_save_only_sets_modified_and_mutable_fields(engine):
    p = Partner(name="acme", priority=1)
    await engine.save(p)
    loaded = await engine.find_one(Partner, Partner.id == p.id)
    # Another writer changes an immutable field we didn't touch...
    await engine.get_collection(Partner).update_one({"_id": p.id}, {"$set": {"name": "renamed"}})
    loaded.priority = 9
    await engine.save(loaded)
    raw = await _raw(engine, Partner, p.id)
    # ...so our save must not clobber it.
    assert raw["name"] == "renamed"
    assert raw["priority"] == 9


async def test_in_place_mutation_of_mutable_fields_is_saved(engine):
    p = Partner(name="acme")
    await engine.save(p)
    loaded = await engine.find_one(Partner, {+Partner.id: p.id})
    loaded.limits.max_amount = 500
    loaded.nbfc_ids.append(bson.ObjectId())
    await engine.save(loaded)
    raw = await _raw(engine, Partner, p.id)
    assert raw["limits"]["max_amount"] == 500
    assert len(raw["nbfc_ids"]) == 1


async def test_find_dict_queries_sort_skip_limit(engine):
    await engine.save_all([Partner(name=f"p{i}", priority=i, enabled=i % 2 == 0) for i in range(6)])
    enabled = await engine.find(Partner, {+Partner.enabled: True}, sort=Partner.priority)
    assert [p.priority for p in enabled] == [0, 2, 4]
    top = await engine.find(Partner, {}, sort=(Partner.priority.desc(),), limit=2)
    assert [p.priority for p in top] == [5, 4]
    page = await engine.find(Partner, sort=desc(Partner.priority), skip=1, limit=2)
    assert [p.priority for p in page] == [4, 3]
    mixed = await engine.find(Partner, {+Partner.priority: {"$in": [1, 3, 5]}}, Partner.priority > 1)
    assert sorted(p.priority for p in mixed) == [3, 5]
    nested = await engine.find(Partner, {+Partner.limits.max_amount: 0})
    assert len(nested) == 6


async def test_cursor_async_iteration(engine):
    await engine.save_all([Partner(name=f"p{i}", priority=i) for i in range(3)])
    seen = [p.priority async for p in engine.find(Partner, sort=Partner.priority)]
    assert seen == [0, 1, 2]


async def test_find_one_count_remove_delete(engine):
    await engine.save_all([Partner(name="a", priority=1), Partner(name="b", priority=2)])
    assert await engine.find_one(Partner, {+Partner.name: "missing"}) is None
    best = await engine.find_one(Partner, {}, sort=Partner.priority.desc())
    assert best.name == "b"
    assert await engine.count(Partner) == 2
    assert await engine.count(Partner, Partner.priority >= 2) == 1
    await engine.delete(best)
    with pytest.raises(DocumentNotFoundError):
        await engine.delete(best)
    assert await engine.remove(Partner, {+Partner.name: "a"}) == 1
    assert await engine.count(Partner) == 0


async def test_raw_collection_and_parse_doc(engine):
    p = Partner(name="acme")
    await engine.save(p)
    doc = await engine.get_collection(Partner).find_one_and_update(
        {"_id": p.id},
        {"$set": {"priority": 7}},
        return_document=ReturnDocument.AFTER,
    )
    parsed = Partner.parse_doc(doc)
    assert parsed.priority == 7 and parsed.id == p.id


async def test_transaction_commits(engine):
    await engine.get_collection(Partner).insert_one({"_id": bson.ObjectId(), "name": "seed"})
    async with engine.transaction() as txn:
        assert isinstance(txn, AIOTransaction)
        await txn.save(Partner(name="in-txn"))
        # Raw driver calls join the transaction through txn.session.session.
        await engine.get_collection(Partner).insert_one(
            {"_id": bson.ObjectId(), "name": "raw-in-txn"}, session=txn.session.session
        )
    names = sorted(p.name for p in await engine.find(Partner))
    assert names == ["in-txn", "raw-in-txn", "seed"]


async def test_transaction_aborts_on_error(engine):
    await engine.get_collection(Partner).insert_one({"_id": bson.ObjectId(), "name": "seed"})
    with pytest.raises(RuntimeError):
        async with engine.transaction() as txn:
            await txn.save(Partner(name="rolled-back"))
            raise RuntimeError("boom")
    assert [p.name for p in await engine.find(Partner)] == ["seed"]


async def test_transaction_explicit_commit_and_session_kwarg(engine):
    await engine.get_collection(Partner).insert_one({"_id": bson.ObjectId(), "name": "seed"})
    async with engine.transaction() as txn:
        p = Partner(name="explicit")
        await engine.save(p, session=txn)
        found = await txn.find_one(Partner, {+Partner.name: "explicit"})
        assert found is not None
        await txn.commit()
    assert await engine.count(Partner) == 2


async def test_transaction_engine_attribute_is_unbound(engine):
    # odmantic parity: txn.engine is the plain engine, so its reads don't see
    # uncommitted writes from the transaction.
    async with engine.transaction() as txn:
        await txn.save(Partner(name="pending"))
        outside = await txn.engine.find(Partner)
        inside = await txn.find(Partner)
        assert outside == []
        assert [p.name for p in inside] == ["pending"]
