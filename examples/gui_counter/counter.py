"""Business logic for the Tkinter counter demo."""

from dataclasses import dataclass


@dataclass
class CounterModel:
    value: int = 0

    def increment(self) -> int:
        self.value += 1
        return self.value

    def decrement(self) -> int:
        # BUG: should subtract, but accidentally adds
        self.value += 1
        return self.value

    def reset(self) -> int:
        self.value = 0
        return self.value
