"""FastAPI-like env validation fixture."""

from __future__ import annotations

import os

API_TOKEN = os.environ["FASTAPI_API_TOKEN"]

try:
    from fastapi import FastAPI
except ModuleNotFoundError:
    class FastAPI:
        def get(self, _path):
            def decorator(func):
                return func

            return decorator


app = FastAPI()


@app.get("/token")
def token_status() -> dict[str, str]:
    return {"token": API_TOKEN[:4]}
