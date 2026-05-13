class PaymentWorkflowError(Exception):
    pass


def normalize_amount(raw):
    return int(raw)


def create_charge(form):
    try:
        cents = normalize_amount(form["amount_cents"])
    except ValueError as exc:
        raise PaymentWorkflowError("checkout amount_cents must be numeric before creating charge") from exc
    return {"amount": cents}


print(create_charge({"amount_cents": "12.50"}))
