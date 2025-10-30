"""Tkinter GUI demo that uses the buggy CounterModel."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .counter import CounterModel


class CounterApp(ttk.Frame):
    def __init__(self, master: tk.Tk | None = None):
        super().__init__(master)
        self.pack(padx=16, pady=16)
        self.model = CounterModel()

        self.value_var = tk.StringVar(value="0")

        ttk.Label(self, text="Counter value:").pack(anchor="w")
        self.value_label = ttk.Label(
            self, textvariable=self.value_var, font=("Menlo", 18)
        )
        self.value_label.pack(anchor="center", pady=(0, 12))

        btn_row = ttk.Frame(self)
        btn_row.pack()
        ttk.Button(btn_row, text="Increment", command=self.on_increment).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_row, text="Decrement", command=self.on_decrement).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_row, text="Reset", command=self.on_reset).pack(
            side=tk.LEFT, padx=4
        )

    def update_display(self, value: int) -> None:
        self.value_var.set(str(value))

    def on_increment(self) -> None:
        self.update_display(self.model.increment())

    def on_decrement(self) -> None:
        self.update_display(self.model.decrement())

    def on_reset(self) -> None:
        self.update_display(self.model.reset())


def main() -> None:
    root = tk.Tk()
    root.title("Counter Demo (intentional bug)")
    CounterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
