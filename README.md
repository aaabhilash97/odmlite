# odmlite

A small async MongoDB ODM built on **pydantic v2** and **pymongo's native async API**.

odmlite implements the commonly used subset of [odmantic](https://github.com/art049/odmantic)'s API. Code written for odmantic usually only needs its imports changed. It runs on Python 3.11–3.14, including 3.14's deferred annotations (PEP 649), where odmantic currently fails at import time.

```python
from pymongo import AsyncMongoClient
from odmlite import AIOEngine, EmbeddedModel, Model


class Address(EmbeddedModel):
    city: str = ""


class User(Model):
    model_config = {"collection": "users"}

    name: str
    age: int = 0
    address: Address = Address()


engine = AIOEngine(client=AsyncMongoClient("mongodb://localhost:27017"), database="app")

user = User(name="Asha", age=30)
await engine.save(user)

adults = await engine.find(User, User.age >= 18, sort=User.name)
asha = await engine.find_one(User, {+User.name: "Asha"})
in_kochi = await engine.find(User, {+User.address.city: "Kochi"})
```

## What's supported

| Feature | Notes |
|---|---|
| `Model`, `EmbeddedModel` | pydantic v2 models. `Model` has `id: ObjectId`, stored as `_id`. |
| Collection name | `model_config = {"collection": ...}`, legacy `class Config: collection = ...`, or the class name in snake_case (a trailing `Model` is dropped). |
| `bson.ObjectId` fields | Validated, and converted from 24-char hex strings. Serialized as hex in JSON mode. |
| `+Model.field`, `+Model.a.b` | Stored key names (`"field"`, `"a.b"`; `+Model.id` is `"_id"`), for raw filters and updates. |
| `Model.f == x`, `!=`, `<`, `<=`, `>`, `>=`, `.in_()`, `.not_in()`, `.match()`, `&`, `\|` | Query expressions. Raw dict filters work as-is. |
| `Model.f.desc()` / `.asc()`, `odmlite.query.asc/desc` | Sort expressions. `sort=` also takes a field, a tuple of these, or `(key, direction)` pairs. |
| `engine.find` | Returns a cursor: `await` it for a list, or `async for` over it. Supports `sort`, `skip`, `limit`. |
| `engine.find_one`, `count`, `save`, `save_all`, `delete`, `remove` | Each takes an optional `session=`. |
| `engine.get_collection(Model)` | The underlying driver collection, for raw operations. |
| `Model.parse_doc(doc)` / `model_validate_doc`, `model_dump_doc()` / `doc()` | Conversion to and from raw documents. |
| `engine.session()`, `engine.transaction()` | `async with` support. `txn.session.session` is the driver session. |
| Driver | `pymongo.AsyncMongoClient` (recommended), or motor's `AsyncIOMotorClient` during a migration. |

### Save semantics (same as odmantic)

`engine.save(instance)` is an upsert that `$set`s only:

- the fields assigned since the instance was loaded or last saved, and
- fields whose types can change in place (lists, dicts, embedded models, `Any`).

Keys present in MongoDB but not declared on the model are never removed or overwritten. That makes it safe to use models that declare only part of a document shared with other services.

### Not supported

The parts of odmantic that odmlite deliberately leaves out:

- `Reference()` and cascading `$lookup`;
- custom primary keys (`Field(primary_field=True)`) and `key_name`;
- index declarations and `configure_database`;
- `SyncEngine`.

`odmlite.Field` is `pydantic.Field`, and raises if odmantic-only options are passed.

## Migrating from odmantic

1. `pip install odmlite`, then remove `odmantic` (and `motor`, if you switch drivers).
2. Replace imports: `from odmantic import ...` becomes `from odmlite import ...`, and `odmantic.session` becomes `odmlite.session`.
3. Create the engine with `pymongo.AsyncMongoClient` instead of motor's client. The raw collection API is almost identical. One difference: `await collection.aggregate(...)` must be awaited with pymongo's async client.
4. odmantic 0.x / pydantic v1 models also need these changes:
   - `Optional[X]` fields without a default are required in pydantic v2, so add `= None`.
   - `class Config` is still accepted for the collection name.

`validate_assignment` and `validate_default` are on by default, as in odmantic. Override them in `model_config` if needed.

## Development

Tests need a MongoDB replica set, because transactions require one:

```bash
docker run -d --name mongo -p 27017:27017 mongo:8 --replSet rs0 --bind_ip_all
docker exec mongo mongosh --quiet --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"localhost:27017"}]})'
pip install -e '.[test]'
pytest
```

## License

MIT
