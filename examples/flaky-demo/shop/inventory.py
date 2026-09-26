"""Stock keeping for the shop's checkout service."""

import asyncio
import random


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, stock: int) -> None:
        self.stock = stock

    async def reserve(self) -> None:
        """Reserve one item for an order."""
        current = self.stock
        if current <= 0:
            raise OutOfStock
        await self._confirm_with_warehouse()
        self.stock = current - 1

    async def _confirm_with_warehouse(self) -> None:
        # Most confirmations are answered from the local cache; roughly half need a
        # round-trip to the warehouse service, which suspends this coroutine.
        if random.random() < 0.5:
            await asyncio.sleep(0)
