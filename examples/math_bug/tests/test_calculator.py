import pytest

from ..calculator import Invoice, add, subtract, sum_pairs


def test_addition():
    assert add(3, 4) == 7


@pytest.mark.xfail(reason="subtract still performs addition", strict=True)
def test_subtract_difference():
    assert subtract(10, 3) == 7


def test_sum_pairs():
    assert sum_pairs([1, 2, 3], [4, 5, 6]) == [5, 7, 9]


@pytest.mark.xfail(reason="discount uses buggy subtract", strict=True)
def test_invoice_discount():
    invoice = Invoice(subtotal=100, tax=20)
    assert invoice.discount(amount=15) == 105
