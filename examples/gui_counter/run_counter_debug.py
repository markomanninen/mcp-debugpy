import sys
import time
from pathlib import Path


# Ensure the repository root is on sys.path so package imports work
def ensure_repo_root_on_path():
    p = Path(__file__).resolve()
    # Walk upwards looking for repository root markers
    for parent in p.parents:
        if (parent / "pyproject.toml").exists() or (parent / "README.md").exists():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return
    # Fallback: add two levels up (examples/<example> -> repo root)
    fallback = str(p.parents[2])
    if fallback not in sys.path:
        sys.path.insert(0, fallback)


ensure_repo_root_on_path()

try:
    from examples.gui_counter.counter import CounterModel
except Exception:
    # Fallback to local import if package import fails
    from counter import CounterModel

# Small sleep to give debuggers a moment to attach and set breakpoints
# Reduced to 0.75s to keep demos snappy but reliable in CI and local runs
time.sleep(0.75)

m = CounterModel()
print("initial", m.value)
print("inc ->", m.increment())
print("dec ->", m.decrement())
print("reset ->", m.reset())
print("final", m.value)
