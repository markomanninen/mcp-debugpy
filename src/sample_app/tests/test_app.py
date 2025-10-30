import pytest

from src.sample_app.app import add, compute


@pytest.mark.xfail(reason="Intentional bug: sample app multiplies instead of adding")
def test_add_should_sum():
    assert add(2, 5) == 7


@pytest.mark.xfail(reason="Intentional bug: compute relies on faulty add() implementation")
def test_compute():
    assert compute() == (7 + 0) + (7 + 1) + (7 + 2)
