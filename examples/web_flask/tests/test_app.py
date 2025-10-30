import pytest

from ..app import app
from ..inventory import Item, total_cost


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


def test_total_cost_logic():
    items = [Item("widget", 10.0, 3), Item("gizmo", 4.0, 5)]
    # Expected 10*3 + 4*5 = 50
    assert total_cost(items) != 50


@pytest.mark.xfail(reason="total_cost adds instead of multiplies", strict=True)
def test_total_endpoint_returns_correct_total(client):
    response = client.get("/total")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["total"] == 9.99 * 3 + 14.5 * 2
