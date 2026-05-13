import asyncio


class AsyncLifecycleError(Exception):
    pass


async def load_session():
    return {"closed": True, "user_id": 42}


async def fetch_profile():
    session = await load_session()
    if session["closed"]:
        raise AsyncLifecycleError("session was closed before profile fetch")
    return {"name": "Ada"}


asyncio.run(fetch_profile())
