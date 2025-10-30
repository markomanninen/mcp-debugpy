"""Business logic used by the Flask demo."""

from dataclasses import dataclass
from typing import Iterable


@dataclass
class Item:
    name: str
    price: float
    quantity: int


def total_cost(items: Iterable[Item]) -> float:
    total = 0.0
    for item in items:
        # BUG: should multiply price * quantity
        total += item.price + item.quantity
    return total
