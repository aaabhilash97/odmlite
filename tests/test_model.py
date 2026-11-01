"""Model behaviour that doesn't need a database."""

import datetime
from enum import Enum
from typing import ClassVar, List, Optional

import bson
import pytest

from odmlite import DocumentParsingError, EmbeddedModel, Field, Model
from odmlite.query import QueryExpression, SortExpression


class Status(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class Address(EmbeddedModel):
    city: str = ""
    pin: Optional[str] = None


class Account(Model):
    model_config = {"collection": "loan_accounts"}

    user_id: bson.ObjectId
    partner_ids: Optional[List[bson.ObjectId]] = None
    status: Status = Status.ACTIVE
    amount: float = 0.0
    address: Address = Address()
    tags: List[str] = []
    created_at: Optional[datetime.datetime] = None
    REGISTRY: ClassVar[List[str]] = ["not", "a", "field"]

    def label(self) -> str:
        return f"{self.status.value}:{self.amount}"


class LegacyConfigModel(Model):
    class Config:
        collection = "legacy_things"

    name: str = ""


class UserProfileModel(Model):
    name: str = ""


OID = "64b7f0c2a1b2c3d4e5f60718"


def test_collection_names():
    assert Account.__collection__ == "loan_accounts"
    assert LegacyConfigModel.__collection__ == "legacy_things"
    assert UserProfileModel.__collection__ == "user_profile"
    assert +Account == "loan_accounts"


def test_field_proxies_give_key_names():
    assert +Account.user_id == "user_id"
    assert +Account.address.city == "address.city"
    assert {+Account.status: "x"} == {"status": "x"}


def test_id_proxy_is_mongo_key():
    # odmantic stores the primary key as _id; queries on +Model.id must target _id.
    assert +Account.id == "_id"


def test_query_expressions():
    assert (Account.amount == 5) == {"amount": {"$eq": 5}}
    assert (Account.status == Status.CLOSED) == {"status": {"$eq": "closed"}}
    assert Account.amount.gte(1) == {"amount": {"$gte": 1}}
    assert Account.user_id.in_([1, 2]) == {"user_id": {"$in": [1, 2]}}
    combined = (Account.amount > 1) & (Account.amount < 9)
    assert isinstance(combined, QueryExpression)
    assert combined == {"$and": [{"amount": {"$gt": 1}}, {"amount": {"$lt": 9}}]}
    assert ((Account.amount > 1) | (Account.amount < 0))["$or"][1] == {"amount": {"$lt": 0}}
    assert (Account.address == Address(city="X")) == {"address": {"$eq": {"city": "X", "pin": None}}}


def test_sort_expressions():
    assert Account.amount.desc() == SortExpression({"amount": -1})
    assert Account.amount.asc() == {"amount": 1}


def test_object_id_coercion_and_validation():
    acc = Account(user_id=OID, partner_ids=[OID])
    assert isinstance(acc.user_id, bson.ObjectId)
    assert isinstance(acc.partner_ids[0], bson.ObjectId)
    assert isinstance(acc.id, bson.ObjectId)
    with pytest.raises(ValueError):
        Account(user_id="not-an-object-id")


def test_validate_assignment():
    acc = Account(user_id=OID)
    acc.user_id = OID
    assert isinstance(acc.user_id, bson.ObjectId)
    with pytest.raises(ValueError):
        acc.amount = "lots"


def test_instance_attributes_and_methods():
    acc = Account(user_id=OID, amount=3)
    assert acc.amount == 3
    assert acc.label() == "active:3.0"
    assert Account.REGISTRY == ["not", "a", "field"]
    assert "REGISTRY" not in Account.model_fields


def test_doc_maps_id_and_keeps_native_types():
    acc = Account(user_id=OID)
    doc = acc.model_dump_doc()
    assert doc["_id"] == acc.id and "id" not in doc
    assert isinstance(doc["user_id"], bson.ObjectId)
    assert doc["address"] == {"city": "", "pin": None}
    assert "REGISTRY" not in doc
    assert acc.doc(include={"amount"}) == {"amount": 0.0}


def test_parse_doc_round_trip_and_extra_keys():
    raw = {
        "_id": bson.ObjectId(OID),
        "user_id": bson.ObjectId(OID),
        "amount": 10.5,
        "address": {"city": "Kochi"},
        "undeclared_key": "kept in mongo, ignored here",
    }
    acc = Account.parse_doc(raw)
    assert acc.id == bson.ObjectId(OID)
    assert acc.address.city == "Kochi"
    assert acc.__fields_modified__ == set()
    again = Account.model_validate_doc(acc.model_dump_doc())
    assert again == acc


def test_parse_doc_missing_required_field():
    with pytest.raises(DocumentParsingError):
        Account.parse_doc({"_id": bson.ObjectId()})


def test_modification_tracking():
    acc = Account(user_id=OID)
    assert acc.__fields_modified__ == set(Account.model_fields)
    loaded = Account.parse_doc(acc.model_dump_doc())
    assert loaded.__fields_modified__ == set()
    loaded.amount = 99
    assert loaded.__fields_modified__ == {"amount"}
    assert loaded.model_copy().__fields_modified__ == set(Account.model_fields)


def test_mutable_fields():
    assert Account.__mutable_fields__ == {"partner_ids", "address", "tags"}


def test_primary_key_reassignment_rejected():
    acc = Account(user_id=OID)
    with pytest.raises(NotImplementedError):
        acc.id = bson.ObjectId()


def test_default_embedded_instances_not_shared():
    a = Account(user_id=OID)
    b = Account(user_id=OID)
    a.address.city = "changed"
    assert b.address.city == ""


def test_field_rejects_odmantic_only_options():
    with pytest.raises(NotImplementedError):
        Field(primary_field=True)


def test_full_model_as_embedded_field():
    class Txn(Model):
        amount: float = 0

    class Wrapper(Model):
        txn: Optional[Txn] = None

    w = Wrapper(txn=Txn(amount=5))
    doc = w.model_dump_doc()
    assert doc["txn"]["amount"] == 5
    parsed = Wrapper.parse_doc(doc)
    assert parsed.txn.amount == 5
    assert parsed.txn.id == w.txn.id


def test_subclassing_a_model():
    class Base(Model):
        model_config = {"collection": "things"}
        name: str = ""

    class Child(Base):
        extra: int = 0

    assert Child.__collection__ == "things"
    assert +Child.name == "name"
    assert Child(name="x").name == "x"
