class NonePropagationChainError(Exception):
    pass


def load_customer():
    return None


def build_context():
    customer = load_customer()
    try:
        return {"email_domain": customer.email.split("@")[1]}
    except AttributeError as exc:
        raise NonePropagationChainError("customer lookup returned None and propagated into email context builder") from exc


print(build_context())
