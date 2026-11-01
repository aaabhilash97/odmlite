# Changelog

## 0.1.0

First release.

- `Model` / `EmbeddedModel` on pydantic v2, with `id` stored as `_id`.
- `bson.ObjectId` validation for fields annotated with plain `bson.ObjectId`.
- Field proxies (`+Model.field`, `+Model.a.b`), query and sort expressions.
- `AIOEngine`: `find` (awaitable or async-iterable cursor), `find_one`, `count`, `save` (partial `$set` with change tracking), `save_all`, `delete`, `remove`, `get_collection`.
- `AIOSession` / `AIOTransaction`.
- Works with `pymongo.AsyncMongoClient` and motor's `AsyncIOMotorClient`.
- Tested on Python 3.11–3.14 against MongoDB 8.
