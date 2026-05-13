import json
from decimal import Decimal


class SerializationEdgeCaseError(Exception):
    pass


def encode_payload(payload):
    try:
        return json.dumps(payload)
    except TypeError as exc:
        raise SerializationEdgeCaseError("payload contains Decimal value that JSON cannot serialize") from exc


print(encode_payload({"total": Decimal("12.50")}))
