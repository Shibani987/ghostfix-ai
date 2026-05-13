from dataclasses import dataclass


class DataclassInitMismatchError(Exception):
    pass


@dataclass
class Invoice:
    number: str
    total: float


def build_invoice(row):
    try:
        return Invoice(number=row["number"], total=row["total"], currency=row["currency"])
    except TypeError as exc:
        raise DataclassInitMismatchError("row contains fields that the Invoice dataclass constructor does not accept") from exc


print(build_invoice({"number": "INV-9", "total": 99.0, "currency": "USD"}))
