"""Flask web app whose endpoint uses the buggy total_cost helper."""

from __future__ import annotations

from flask import Flask, jsonify, request

from .inventory import Item, total_cost


app = Flask(__name__)


SAMPLE_ITEMS = [
    Item(name="widget", price=9.99, quantity=3),
    Item(name="gadget", price=14.5, quantity=2),
]


@app.get("/total")
def get_total() -> tuple[str, int] | tuple[dict[str, float], int]:
    use_payload = request.args.get("payload") == "1"
    items = SAMPLE_ITEMS
    if use_payload:
        payload = request.get_json(silent=True) or {}
        items = [Item(**data) for data in payload.get("items", [])]

    total = total_cost(items)
    return jsonify({"total": round(total, 2)}), 200


def main() -> None:
    # Intended for debugging with dap_launch; enables reloader=False to keep PID stable.
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
