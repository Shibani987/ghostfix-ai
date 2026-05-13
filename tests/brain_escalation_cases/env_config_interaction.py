import os


class ConfigInteractionError(Exception):
    pass


def build_database_config():
    engine = os.environ.get("DB_ENGINE", "sqlite")
    ssl_mode = os.environ.get("DB_SSL_MODE", "require")
    if engine == "sqlite" and ssl_mode == "require":
        raise ConfigInteractionError("sqlite configuration cannot use DB_SSL_MODE=require")
    return {"engine": engine, "ssl_mode": ssl_mode}


print(build_database_config())
