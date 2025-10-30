import pytest

from ..counter import CounterModel


def test_increment_advances_value():
    model = CounterModel()
    model.increment()
    assert model.value == 1


@pytest.mark.xfail(reason="decrement adds instead of subtracting", strict=True)
def test_decrement_reduces_value():
    model = CounterModel(value=2)
    model.decrement()
    assert model.value == 1
