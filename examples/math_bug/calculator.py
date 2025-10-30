"""
Tiny calculator module with an intentional bug in `subtract` to showcase debugging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    # BUG: should be `a - b`
    return a + b


def sum_pairs(xs: Iterable[int], ys: Iterable[int]) -> List[int]:
    return [add(x, y) for x, y in zip(xs, ys)]


@dataclass
class Invoice:
    subtotal: int
    tax: int

    @property
    def total(self) -> int:
        return add(self.subtotal, self.tax)

    def discount(self, amount: int) -> int:
        """Return the discounted total using the buggy subtract."""
        return subtract(self.total, amount)


def main() -> None:
    """
    Simple CLI: apply a discount and print the result.
    Breakpoint-friendly on the `discount` call.
    """
    invoice = Invoice(subtotal=120, tax=24)
    discounted = invoice.discount(amount=30)
    print(f"Discounted total: {discounted}")


if __name__ == "__main__":
    main()
