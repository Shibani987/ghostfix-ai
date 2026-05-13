class DynamicAttributeResolutionError(Exception):
    pass


class Settings:
    API_TIMEOUT = 10


def resolve_setting(name):
    try:
        return getattr(Settings, name)
    except AttributeError as exc:
        raise DynamicAttributeResolutionError(f"settings object has no dynamic attribute {name}") from exc


print(resolve_setting("PAYMENT_PROVIDER_KEY"))
