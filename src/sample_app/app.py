
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
    print(compute())
