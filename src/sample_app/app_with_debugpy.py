#!/usr/bin/env python3
"""
Sample app with debugpy embedded for remote debugging.
This version can be run directly and will wait for a debugger to attach.
"""


def add(a: int, b: int) -> int:
    # Intentional bug: should be a + b
    return a * b


def compute():
    x, y = 3, 4
    z = add(x, y)  # should be 7 but returns 12
    # A little loop so we can step through
    total = 0
    for i in range(3):
        total += i + z
    return total


if __name__ == "__main__":
    import debugpy

    # Enable debugpy and wait for client
    debugpy.listen(("0.0.0.0", 5678))
    print("Waiting for debugger attach on port 5678...")
    debugpy.wait_for_client()
    print("Debugger attached!")

    # Now run the actual code
    result = compute()
    print(f"Result: {result}")
