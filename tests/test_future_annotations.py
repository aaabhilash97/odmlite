"""Models declared in a module using string (postponed) annotations."""

from __future__ import annotations

from typing import List, Optional

import bson

from odmlite import EmbeddedModel, Model


class Item(EmbeddedModel):
    sku: str = ""
    qty: int = 0


class Order(Model):
    model_config = {"collection": "orders"}

    user_id: Optional[bson.ObjectId] = None
    items: List[Item] = []


def test_postponed_annotations_resolve():
    order = Order(user_id="64b7f0c2a1b2c3d4e5f60718", items=[{"sku": "a", "qty": 2}])
    assert isinstance(order.user_id, bson.ObjectId)
    assert order.items[0].qty == 2
    assert +Order.items == "items"
    assert Order.__mutable_fields__ == {"items"}
    assert Order.parse_doc(order.model_dump_doc()) == order
