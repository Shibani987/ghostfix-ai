class APIResponseShapeError(Exception):
    pass


def parse_orders(response):
    try:
        return response["data"]["orders"][0]["id"]
    except (KeyError, IndexError, TypeError) as exc:
        raise APIResponseShapeError("expected data.orders[0].id in partner response") from exc


payload = {"data": {"items": [{"id": "ord_123"}]}}
print(parse_orders(payload))
