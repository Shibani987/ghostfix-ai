class CacheHydrationError(Exception):
    pass


def read_cache():
    return {"profile": None}


def hydrate_profile():
    try:
        profile = read_cache()["profile"]
        return profile["email"]
    except TypeError as exc:
        raise CacheHydrationError("cache profile entry is None after hydration chain") from exc


print(hydrate_profile())
