import asyncio

import pytest

from shop.inventory import Inventory, OutOfStock


async def test_reserve_takes_one_item() -> None:
    inventory = Inventory(stock=3)

    await inventory.reserve()

    assert inventory.stock == 2


async def test_reserve_fails_when_sold_out() -> None:
    inventory = Inventory(stock=0)

    with pytest.raises(OutOfStock):
        await inventory.reserve()


async def test_concurrent_orders_each_take_an_item() -> None:
    inventory = Inventory(stock=2)

    await asyncio.gather(inventory.reserve(), inventory.reserve())

    assert inventory.stock == 0
